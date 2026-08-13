# B300 (p6-b300.48xlarge) + FSx Lustre EFA + GPUDirect Storage 实测报告

> 实测时间：2026-08-13（UTC）  区域：us-west-2a  
> 脚本：`configure-fsx-lustre-efa-gds.sh`（本次已在真机 debug 修正，为"真机验证版"）  
> 结论标注：【实测】= 本次真机跑出；【推测】= 未实测的推断。

---

## 0. 一句话结论

**【实测】p6-b300.48xlarge 完全能跑 FSx for Lustre over EFA + NVIDIA GPUDirect Storage(GDS)。**
- 15 个 EFA NI 全部配上、2 个 OST 全 FULL；
- FIO 顺读 **41.7 GB/s**、顺写 **11.2 GB/s**、随机读 8.8 GB/s；
- LNet/硬件计数器铁证数据走 EFA（rdma_read_bytes 0 → 85.9 GB）；
- `gdscheck -p` → **Platform verification succeeded**，8×B300 全支持 GDS；
- `gdsio` GPUDirect(XferType=GPUD) 读写正常（读 9.22 / 写 9.11 GiB/s）。

需要两处非默认操作才能跑通（下面详述）：①Capacity Block 起实例要加 market-options；②b300 要手动加进 AWS 脚本的 GDS 白名单。

---

## 1. 资源与环境

| 项 | 值 |
|---|---|
| 实例 | <INSTANCE_ID>，p6-b300.48xlarge，us-west-2a |
| GPU | 8 × NVIDIA B300 SXM6 AC（每卡 275040 MiB / ~268 GB，bar1 512 GiB） |
| AMI | <DLAMI_ID>（DLAMI，Ubuntu 24.04.4，kernel 6.17.0-1019-aws） |
| CPU/NUMA | 192 vCPU，2 NUMA 节点 |
| Capacity Reservation | <CAPACITY_RESERVATION_ID>（**类型 capacity-block**，窗口至 2026-08-14 11:30 UTC） |
| FSx Lustre | <FSX_ID>，MountName `<MOUNTNAME>`，同 AZ(us-west-2a)，2×OST 各 18.4T，共 36.8T |
| 网卡能力 | MaximumNetworkCards=17，MaximumEfaInterfaces=16 |
| 软件版本 | Lustre client 2.15.6 / EFA driver 3.0.0 / kefalnd 1.2.2 / nvidia-fs 2.29 / libcufile 2.12 / GDS 1.13.1.3 |

---

## 2. 关键坑 + 根因 + 修复（按遇到顺序）

### 坑① Capacity Block 起实例报 "market type option is not valid"
- **现象**：普通 `run-instances --capacity-reservation-specification 'CapacityReservationTarget={...}'` 直接报
  `InvalidParameterValue: The market type (purchasing) option is not valid`。
- **根因**：<CAPACITY_RESERVATION_ID> 的 `ReservationType=capacity-block`（不是普通 on-demand CR）。Capacity Block 是独立计费/市场类型。
- **修复【实测】**：run-instances 必须加 `--instance-market-options 'MarketType=capacity-block'`（与 `--capacity-reservation-specification` 一起用）。加上后一次起成功。

### 坑② 实例内只看到 2 个 EFA 设备（期望 16）
- **现象**：默认 `--associate-public-ip-address` 单网卡起，实例内 `/sys/class/infiniband/` 只有 `ibp198s0f0`/`ibp199s0f0` 两个，`describe-instances` 只有 1 个 NetworkInterface（card0，type=interface）。
- **根因**：B300 的 16 个 EFA 接口分布在多张 network card 上，**run-instances 不会自动把它们都拉起来**——必须显式挂 EFA 网卡。
- **修复【实测】**：EFA 网卡**只能在实例 stopped 状态**挂（running 时挂报 `IncorrectState: Interface type 'efa' can only be attached to an instance in state stopped`）。流程：
  1. `create-network-interface --interface-type efa`（建 15 个）
  2. `stop-instances` → 等 stopped
  3. 逐个 `attach-network-interface --interface-type... --device-index 1 --network-card-index 1..15`
  4. `modify-network-interface-attribute ... DeleteOnTermination=true`（方便清理）
  5. `start-instances`
- **副作用**：stop 会释放自动分配的公网 IP → 需 `allocate-address` + `associate-address` 挂 EIP 到主 ENI 才能再 SSH。
- **结果**：重启后 `/sys/class/infiniband/` 出现 17 个设备（card0 的 2 个 `ibp*` + card1~15 的 15 个 `rdmap*`）。**setup.sh 最终配了 15 个 @efa NI**（card0 的 EFA 未纳入池，card0 走 TCP 做管理/SSH）。
- **备选【推测】**：更干净的做法是 launch 时直接用 `--network-interfaces` 一次性声明 16 张 EFA 网卡，可省去 stop/start 与 EIP 重挂。本次为保住 Capacity Block 槽位选了"先起再 stop 挂网卡"，同样跑通。

### 坑③ setup.sh --optimized-for-gds 报 "p6-b300.48xlarge does not support Lustre GDS"
- **现象**：AWS 官方 `configure-efa-fsx-lustre-client.py` 的 `filter_efa_gds()` 检查机型是否在 `GDS_SUPPORTED_INSTANNCES` 白名单里，b300 不在 → 直接 raise。
- **根因**：白名单目前只有 `p5 / p5e / p5en / p6-b200`，还没收录 b300（AWS 侧未更新）。
- **修复【实测】**：把 `"p6-b300.48xlarge",` 加进白名单数组即可，其余逻辑不动，setup.sh 顺利跑通。
- **⚠️脚本自身的 bug（本次已修）**：原脚本用 `grep -q '"p6-b300.48xlarge"' "$PY"` 判"是否已加"来做幂等——**这是错的**：`p6-b300.48xlarge` 字符串在 .py 别处也出现，grep 误判"已加"→ 跳过 sed → 白名单其实没加 → 仍报错。**修复**：幂等判断改为精确匹配白名单数组行 `^    "p6-b300\.48xlarge",$`，sed 也锚定行首行尾只改数组那一行。已写回脚本。

### 其它观察（无坑，正常）
- nvidia-fs 在此 DLAMI 未预装模块 → 脚本按官方从 `github.com/NVIDIA/gds-nvidia-fs` 源码编译 `insmod` 成功（gdscheck 报 nvidia-fs 2.29）。
- **无** `No EFA devices found for NUMA node X` 报错：15 个 EFA 干净映射到 15 个 CPT（`cpu_npartitions=15`），NUMA=2，cpu_pattern 自动生成。
- OST 挂载后先短暂 `CONNECTING`，~15s 后转 `FULL`（正常握手，非故障）。

---

## 3. 硬验证结果（逐项对齐任务清单）

### (a) FSx Lustre over EFA 挂载成功 + OST 全 FULL 【实测✅】
```
mount -t lustre -o relatime,flock <FSX_ID>.fsx.us-west-2.amazonaws.com@tcp:/<MOUNTNAME> /fsx
lctl get_param -n osc.*.ost_server_uuid:
  <MOUNTNAME>-OST0000_UUID  FULL
  <MOUNTNAME>-OST0001_UUID  FULL
lfs df -h /fsx: MDT 549.9G + 2×OST 18.4T = 36.8T
lnetctl net show: 1×tcp + 15×efa NI
```

### (b) FIO 吞吐/延迟 【实测✅】
| 测试 | 带宽 | 延迟(avg) |
|---|---|---|
| 顺写 seqwrite 1M×8jobs iodepth32 | **11.2 GB/s** (10.4 GiB/s) | ~24 ms |
| 顺读 seqread 1M×8jobs iodepth32 | **41.7 GB/s** (38.8 GiB/s) | ~6.2 ms |
| 随机读 randread 64k×4jobs iodepth16 | **8.8 GB/s** (8393 MiB/s) | ~464 µs |

> 顺读 41.7 GB/s ≈ 333 Gbps，说明多 EFA NI 聚合带宽很高。读远高于写（FSx Lustre 写要落 2 OST + 元数据同步）。

### (c) EFA 真有收发包（LNet 统计前后对比）【实测✅ 铁证】
| 计数器 | FIO 前 | FIO 后 | 增量 |
|---|---|---|---|
| LNet efa 总 send_count | 8 | 797,690 | +797,682 |
| LNet efa 总 recv_count | 8 | 945,146 | +945,138 |
| HW rx_pkts | 40 | 13,937,778 | +~13.9M |
| HW tx_pkts | 40 | 22,110,729 | +~22.1M |
| HW **rdma_read_bytes** | 0 | **85,899,345,920 (~85.9 GB)** | 与读入量吻合 |

> **rdma_read_bytes 从 0 涨到 85.9 GB**，与 FIO 读入的 ~64GB+重复读吻合 → **铁证 Lustre 数据面走 EFA/RDMA**。
> 【实测细节】15 个 EFA NI 中 **8 个承载了绝大部分流量**（每个 send_count ≈ 10 万），其余 7 个几乎为 0。原因【推测】：2 个 OST × 每 OST 的连接/多路复用，Lustre 只在部分 NI 上建立了活跃 OSC 连接；要 16 卡全均摊需更多 OST 或更高并发。这点值得后续验证。

### (d) GDS 验证 【实测✅】
- `gdscheck -p` → **`Platform verification succeeded`**；`DDN EXAScaler: Supported`（即 Lustre GDS 路径）；`fs.lustre.posix_gds_min_kb: 0`；8×B300 全 `supports GDS`；Nvidia Open Driver。
- `gdsio` 实测（8 线程，1MB IO，4G/线程）：
  | XferType | 读 | 写 |
  |---|---|---|
  | **GPUD (GPUDirect Storage)** | **9.22 GiB/s** @847µs | **9.11 GiB/s** @857µs |
  | CPUONLY | 9.70 GiB/s @805µs | 10.31 GiB/s @758µs |
  > GPUD 路径正常跑通（存储直达显存）。本配置下 CPUONLY 略快属正常——GDS 优势在更高并发/更大 IO/省 CPU bounce 场景更明显；此处核心是**证明 GPUD 全栈可用**。

---

## 4. B300(16EFA) vs B200(8EFA) 对比

| 维度 | p6-b300.48xlarge | p6-b200.48xlarge |
|---|---|---|
| EFA 接口数 | **16**（本次实配 15，card0 留 TCP）【实测】 | 8【文档/既往】 |
| 网卡数 MaximumNetworkCards | 17【实测 describe】 | 9【推测，对应 8EFA+1】 |
| GPU | 8×B300 SXM6（~268GB/卡）【实测】 | 8×B200【推测】 |
| GDS 官方白名单 | 尚未收录，需手动加【实测】 | 已在白名单【实测：脚本原生含 p6-b200】 |
| EFA 聚合带宽 | 更高（16 卡）；本次顺读 41.7 GB/s【实测】 | 8 卡，理论约一半聚合上限【推测】 |
| 配置流程 | 与 B200 相同（同一 setup.sh），仅多加白名单 + 网卡更多 | 原生支持 |

> 结论：**B300 相对 B200 主要是 EFA 网卡翻倍(16 vs 8) + GPU 换代**，FSx Lustre EFA/GDS 配置流程完全一致，唯一额外动作是把 b300 加进 GDS 白名单（AWS 更新脚本后即可去掉）。

---

## 5. 脚本用法（真机验证版）

```bash
# 普通 EFA（无 GDS）
sudo FSX_DNS=fs-xxxx.fsx.us-west-2.amazonaws.com FSX_MOUNTNAME=abcd1234 \
     bash configure-fsx-lustre-efa-gds.sh

# 启用 GDS（本次 B300 用法，DLAMI 已带 Lustre/EFA 驱动可 --skip-driver）
sudo FSX_DNS=<FSX_ID>.fsx.us-west-2.amazonaws.com \
     FSX_MOUNTNAME=<MOUNTNAME> MNT=/fsx \
     bash configure-fsx-lustre-efa-gds.sh --gds --skip-driver
```
前置（脚本外，务必先做）：
1. **建实例**：Capacity Block 加 `--instance-market-options 'MarketType=capacity-block'`；
2. **挂 EFA 网卡**：launch 时用 `--network-interfaces` 声明多张 EFA 网卡，或 stopped 时 `attach-network-interface --interface-type efa --network-card-index N`；
3. **同 AZ**：EFA 客户端必须与 FSx Lustre 同一 AZ（跨 AZ 会 OST DISCONN，见历史教训）；
4. **SG 自引用全放行**。

---

## 6. 费用与清理

- **清理动作【已按任务要求：stop 不 terminate】**：测完 `stop-instances`（保留实例，Capacity Block 窗口内可再起）；**删 FSx** <FSX_ID>；释放 EIP <EIP_ALLOC_ID>；DeleteOnTermination 已设，terminate 时 15 个 EFA ENI 自动删。
- **花费**：见任务汇总（Capacity Block 按预留时长计费；FSx Lustre 按存储/吞吐计费；EIP 关联时免费、未关联收费）。

---

## 附：本次关键命令速查
```bash
# 起 Capacity Block 实例
aws ec2 run-instances --region us-west-2 --instance-type p6-b300.48xlarge \
  --image-id <DLAMI_ID> --subnet-id <SUBNET_ID> \
  --security-group-ids <SECURITY_GROUP_ID> --key-name <KEY_NAME> \
  --associate-public-ip-address \
  --instance-market-options 'MarketType=capacity-block' \
  --capacity-reservation-specification 'CapacityReservationTarget={CapacityReservationId=<CAPACITY_RESERVATION_ID>}'

# 挂 EFA 网卡（实例 stopped 后）
aws ec2 create-network-interface --subnet-id ... --groups ... --interface-type efa
aws ec2 attach-network-interface --instance-id ... --network-interface-id ... --device-index 1 --network-card-index N

# 验证 EFA 收发（FIO 前后各跑一次对比 send/recv_count）
sudo lnetctl net show --net efa -v 4 | grep -E "nid:|send_count:|recv_count:"

# GDS 验证
sudo gdscheck -p                 # 期望 Platform verification succeeded
sudo gdsio -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 0 -I 1   # GPUD 写
```
