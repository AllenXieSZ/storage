# B300 (p6-b300.48xlarge) + FSx Lustre over EFA + GPUDirect Storage 配置与验证

> 实测时间：2026-08-13（UTC）  区域：us-west-2a  
> 目标读者：需要在 B300 上把 FSx for Lustre over EFA + NVIDIA GPUDirect Storage(GDS) 配起来并验证的人。  
> 配套脚本：`configure-fsx-lustre-efa-gds.sh`（真机验证版，严格对齐 AWS 官方 User Guide）。  
> 结论标注：【实测】= 本次真机跑出；【推测】= 未实测的推断。  
> 完整命令+输出流水见 `transcript-16efa-rebuild.log`。

---

## 0. 一句话结论

> **说明**：截至 2026-08-13，AWS 官方 User Guide 与 configure 脚本的 GDS 支持机型列表**尚未收录 p6-b300.48xlarge**（仅列 p5/p5e/p5en/p6-b200）。因此下述并非"官方声明支持"，而是**本次在真机上实测配置并验证通过**的结果。

**【实测】在 p6-b300.48xlarge 上，FSx for Lustre over EFA + NVIDIA GPUDirect Storage(GDS) 配置并验证通过。**
16 个 EFA NI 全配上、2 个 OST 全 IDLE；FIO 顺读 **45.2 GB/s** / 顺写 **10.9 GB/s**；`lnetctl -v 4` 前后对比证实数据走 EFA；`gdscheck -p` → Platform verification succeeded，8×B300 全支持 GDS，gdsio GPUD 路径正常。

### 按官方文档，哪些要改 / 哪些已预装（用 DLAMI 的前提下）

| 项目 | 官方 User Guide | 在 B300 上是否要动手 |
|---|---|---|
| Lustre client | Step 2 安装 | ✅ **DLAMI 已预装**（2.15.6），无需改 |
| EFA driver | Step 2 安装 | ✅ **DLAMI 已预装**（3.0.0g / installer 1.47.0），无需改 |
| CUDA / NVIDIA driver | — | ✅ **DLAMI 已预装**（driver 595.71.05 / CUDA 13.2），无需改 |
| GDS 驱动 nvidia-fs (≥2.24.2) | Step 2 GDS 节安装 | ✅ **DLAMI 已预装**（2.29），无需改 |
| **GDS 白名单** | 脚本内 `GDS_SUPPORTED_INSTANNCES` | ⚠️ **唯一需要改的一处**：手动把 `p6-b300.48xlarge` 加进白名单数组（因官方尚未收录 b300） |
| EFA 配置 setup.sh | Step 3 运行 `setup.sh --optimized-for-gds` | ✅ 原样运行，加完白名单后逻辑不用改 |
| 挂载 / FIO / lnet / gdscheck | Step 4 + 验证 | ✅ 官方命令原样用 |

> **结论**：用 DLAMI 时，**脚本层面唯一改动 = 加 GDS 白名单**，其余驱动全预装、其余命令全原样。
> （若用普通 AMI，则还需按 Step 2 自行安装 Lustre/EFA/nvidia-fs 驱动——那是环境准备，不是改这个 configure 脚本。）
> 另有两件**脚本外的 EC2 层准备**（不属于本文档脚本范畴）：起实例时声明 16 个 EFA 网卡、用 Capacity Block 起实例的特殊参数——见附录 A/B。

---

## 1. 资源与环境

| 项 | 值 |
|---|---|
| 实例类型 | p6-b300.48xlarge（us-west-2a） |
| GPU | 8 × NVIDIA B300 SXM6 AC（每卡 275040 MiB / ~268 GB，bar1 512 GiB） |
| **AMI** | **`ami-0a7b058a8e9a433af`**（AWS Deep Learning AMI, Ubuntu 24.04.4, kernel 6.17.0-1019-aws；预装 Lustre client / EFA driver / CUDA / GDS 工具，见下方版本表） |
| CPU/NUMA | 192 vCPU，2 NUMA 节点 |
| 网卡布局 | card0 = 1 普通 interface（SSH/管理）+ card1~16 = **16 个 EFA**（传数据） |
| FSx Lustre | PERSISTENT_2，250 MB/s/TiB，`EfaEnabled=true`，同 AZ(us-west-2a)，2×OST 各 18.4T，共 36.8T |

### 软件 / 内核 / 驱动版本（实例内实测）

| 组件 | 版本【实测】 |
|---|---|
| OS 发行版 | **Ubuntu 24.04.4 LTS (Noble Numbat)**（VERSION_ID 24.04） |
| Kernel | **6.17.0-1019-aws**（x86_64） |
| NVIDIA driver | **595.71.05**（Nvidia Open Driver） |
| CUDA（driver 支持） | **13.2**（Cuda Driver Version 13020；实例含 cuda-12.8/12.9/13.0/13.2 多版本，`/usr/local/cuda`→默认） |
| EFA 内核模块 (efa kmod) | **3.0.0g** |
| EFA installer | **1.47.0** |
| kefalnd（P6+ LNet EFA 驱动） | **1.2.2**（要求 ≥1.1.1） |
| Lustre client（userspace + kmod） | **2.15.6** |
| nvidia-fs（GDS 内核模块） | **2.29**（已 insmod，要求 ≥2.24.2） |
| libcufile（GDS 用户态） | **2.12** |

> **AMI 强烈建议用 DLAMI**：Lustre client、EFA driver、CUDA、GDS 工具都已预装，脚本可加 `--skip-driver` 跳过装驱动步骤。

前置条件（这三条不满足，后面全白搭）：
1. **EFA 客户端必须与 FSx Lustre 同一 AZ**（跨 AZ 会 OST DISCONN）。
2. **安全组自引用全放行**（客户端 SG 与 FSx SG 互放行所有 EFA 流量）。
3. 客户端 OS：AL2023 / RHEL9.5+ / Ubuntu22.04+(kernel 6.8+)。

---

## 2. 配置 EFA + GDS（按 AWS 官方 User Guide 步骤）

官方文档：<https://docs.aws.amazon.com/fsx/latest/LustreGuide/configure-efa-clients.html>

一条命令跑完（脚本封装了官方 Step 1~4 + 挂载 + 验证）：

```bash
sudo FSX_DNS=<fsid>.fsx.us-west-2.amazonaws.com \
     FSX_MOUNTNAME=<mountname> MNT=/fsx \
     bash configure-fsx-lustre-efa-gds.sh --gds --skip-driver
```

脚本内部按官方流程做的事：
1. **Step 2b（GDS 驱动）**：DLAMI 若未加载 nvidia-fs，按官方从 `github.com/NVIDIA/gds-nvidia-fs` 源码编译并 `insmod`（`NVFS_MAX_PEER_DEVS=128 NVFS_MAX_PCI_DEPTH=16`）。要求 nvidia-fs ≥ 2.24.2。
2. **加 GDS 白名单**（B300 专属，见第 6 节）。
3. **Step 3（配 EFA）**：下载 AWS `configure-efa-fsx-lustre-client.zip`，跑 `sudo ./setup.sh --optimized-for-gds` —— 导入 Lustre 模块、配 TCP+EFA 接口、建重启自动配置的 systemd 服务。
4. **Step 4（看接口）**：列 EFA 网卡 + `lnetctl net show`。

### 配置结果【实测】

`setup.sh --optimized-for-gds` 自动配满 **16 个 @efa NI**，无 "No EFA devices found for NUMA node X" 报错：

```
options libcfs cpu_npartitions=16 cpu_pattern="0[0..11] 1[12..23] 2[24..35] 3[36..47]
  4[96..107] 5[108..119] 6[48..59] 7[60..71] 8[72..83] 9[84..95]
  10[144..155] 11[156..167] 12[168..179] 13[180..191] 14[120..131] 15[132..143]"
```
- 16 个 EFA 干净映射到 16 个 CPT（CPU Partition Table），横跨 2 个 NUMA 节点。
- `lnetctl net show` 输出：1 × tcp NI（card0，走 SSH/管理）+ **16 × @efa NI**（传数据）。

---

## 3. 挂载 FSx for Lustre（官方挂载命令）

```bash
sudo mkdir -p /fsx
sudo mount -t lustre -o relatime,flock <fsid>.fsx.us-west-2.amazonaws.com@tcp:/<mountname> /fsx
```

**⚠️ 挂载后 OST 会先短暂 `CONNECTING`（~15s），必须等它转 `FULL`/`IDLE` 再跑 IO**，否则 IO 会失败/无流量。验证：

```bash
lctl get_param -n osc.*.ost_server_uuid
#  <mountname>-OST0000_UUID  IDLE
#  <mountname>-OST0001_UUID  IDLE      ← FULL/IDLE=连通；DISCONN=断(多半跨AZ或SG没自引用)
lfs df -h /fsx
#  MDT 549.9G + 2×OST 18.4T = 36.8T
```

---

## 4. FIO 性能测试【实测】

```bash
# 顺写
sudo fio --name=sw --directory=/fsx/fiotest --rw=write --bs=1M --size=8G \
  --numjobs=8 --ioengine=libaio --direct=1 --iodepth=32 --group_reporting
# 顺读（先 drop_caches）
sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
sudo fio --name=sr --directory=/fsx/fiotest --rw=read  --bs=1M --size=8G \
  --numjobs=8 --ioengine=libaio --direct=1 --iodepth=32 --group_reporting
# 随机读
sudo fio --name=rr --directory=/fsx/fiotest --rw=randread --bs=64k --size=4G \
  --numjobs=4 --ioengine=libaio --direct=1 --iodepth=16 --group_reporting
```

结果：

| 测试 | 带宽 |
|---|---|
| 顺写 1M×8jobs iodepth32 | **10.9 GB/s** (10.2 GiB/s) |
| 顺读 1M×8jobs iodepth32 | **45.2 GB/s** (42.1 GiB/s) |
| 随机读 64k×4jobs iodepth16 | **3.26 GB/s** (3112 MiB/s) |

> 顺读 45.2 GB/s ≈ 362 Gbps，16 个 EFA NI 聚合带宽很高。读远高于写（写要落 2 OST + 元数据同步）。

---

## 5. 用 LNet 验证数据确实走 EFA【实测·铁证】

**最直接的证明方法** = 对比 FIO 前后每个 EFA NI 的 LNet 统计（`lnetctl net show -v 4` 是官方 troubleshooting 的最详细级别，输出每个 NI 的 `send_count/recv_count/drop_count`）：

```bash
# FIO 前后各跑一次，对比增量
sudo lnetctl net show --net efa -v 4 | awk '/send_count:/{s+=$2}/recv_count:/{r+=$2}END{print s,r}'
```

| LNet efa 计数（16 NI 汇总） | FIO 前 | FIO 后 | 增量 |
|---|---|---|---|
| send_count | 196,819 | **998,780** | +801,961 |
| recv_count | 262,355 | **1,211,772** | +949,417 |

> 大量 FIO 读写后 send/recv_count 暴涨 → **铁证 Lustre 数据面在 EFA NI 上收发**。
> 【实测细节】流量主要集中在部分 EFA NI 上（因本次只有 2 个 OST，Lustre 只在部分 NI 建活跃 OSC 连接）；要 16 卡全均摊需更多 OST 或更高并发。【推测，待验证】

---

## 6. 用 gdscheck / gdsio 验证 GDS【实测】

```bash
sudo /usr/local/cuda/gds/tools/gdscheck -p        # 平台自检
sudo /usr/local/cuda/gds/tools/gdsio -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 0 -I 1  # GPUD 写
```

### gdscheck -p 关键输出
```
Platform verification succeeded          ← 核心：GDS 全栈可用
DDN EXAScaler : Supported                ← Lustre GDS 路径受支持
fs.lustre.posix_gds_min_kb : 0
GPU index 0..7 NVIDIA B300 SXM6 AC : supports GDS   ← 8 卡全支持
Nvidia Driver Info Status: Supported (Nvidia Open Driver Installed)
```

### gdsio 吞吐（8 线程，1MB IO，4G/线程）
| XferType | 读 | 写 |
|---|---|---|
| **GPUD (GPUDirect Storage，存储直达显存)** | **3.53 GiB/s** | **3.73 GiB/s** |
| CPUONLY | 4.56 GiB/s | 4.88 GiB/s |

> GPUD 路径正常跑通（存储直达显存，绕过 CPU bounce buffer）。**本配置下 CPUONLY 略快属正常** —— GDS 的价值在更高并发 / 更大 IO / 省 CPU 内存带宽的场景才凸显；此处核心是**证明 GPUD 全栈可用**。

---

## 7. 脚本用法

```bash
# 普通 EFA（无 GDS）
sudo FSX_DNS=<fsid>.fsx.us-west-2.amazonaws.com FSX_MOUNTNAME=<mountname> \
     bash configure-fsx-lustre-efa-gds.sh

# 启用 GDS（B300 用法；DLAMI 已带 Lustre/EFA 驱动，加 --skip-driver 跳过装驱动）
sudo FSX_DNS=<fsid>.fsx.us-west-2.amazonaws.com FSX_MOUNTNAME=<mountname> MNT=/fsx \
     bash configure-fsx-lustre-efa-gds.sh --gds --skip-driver
```

脚本会自动完成第 2~6 节的全部步骤（含 OST 就绪等待、fio 自动安装、EFA 前后对比、gdscheck/gdsio）。

---

## 8. B300(16EFA) vs B200(8EFA)

| 维度 | p6-b300.48xlarge | p6-b200.48xlarge |
|---|---|---|
| EFA 接口数 | **16**【实测】 | 8 |
| MaximumNetworkCards | 17【实测 describe】 | 9【推测】 |
| GPU | 8×B300 SXM6（~268GB/卡）【实测】 | 8×B200 |
| GDS 官方白名单 | 尚未收录，需手动加【实测】 | 已在白名单 |
| 配置流程 | 与 B200 相同（同一 setup.sh），仅多加白名单 | 原生支持 |

> B300 相对 B200 = EFA 网卡翻倍(16 vs 8) + GPU 换代，FSx Lustre EFA/GDS 配置流程完全一致，唯一额外动作是把 b300 加进 GDS 白名单（AWS 更新脚本后即可去掉）。

---
---

# 附录 · 踩坑记录（配置无关，供避坑参考）

## A. 坑：B300 的 16 个 EFA 网卡怎么挂才对

B300 的 16 个 EFA 接口分布在 16 张 network card 上（`MaximumNetworkCards=17`）。**`run-instances` 默认只拉起 card0 一张网卡**，实例内只看到 2 个 EFA 设备 —— 必须显式声明全部网卡。

### ✅ 正确做法（启动即 16 EFA，一步到位）
`run-instances` 时用 `--network-interfaces` 一次性声明 17 张网卡：card0 = 普通 interface（SSH/管理），card1~16 = 16 个 efa：

```bash
# 网卡声明（card0 interface + card1~16 efa）；注意：多网卡不能带 AssociatePublicIpAddress
--network-interfaces \
  '{"NetworkCardIndex":0,"DeviceIndex":0,"InterfaceType":"interface","Groups":["<sg>"],"SubnetId":"<subnet>","DeleteOnTermination":true}' \
  '{"NetworkCardIndex":1,"DeviceIndex":1,"InterfaceType":"efa","Groups":["<sg>"],"SubnetId":"<subnet>","DeleteOnTermination":true}' \
  ... （card2~16 同理）
```

两个连带坑：
1. **多网卡不能带 `--associate-public-ip-address`**（报 `InvalidParameterCombination`）→ 去掉。
2. 多网卡实例**不会自动分配公网 IP** → 起来后给 card0 主 ENI 关联 EIP 才能 SSH：
   ```bash
   aws ec2 allocate-address --domain vpc
   aws ec2 associate-address --allocation-id <eipalloc> --network-interface-id <card0-eni>
   ```

### ❌ 走过的弯路（不要学）
第一次用 `--associate-public-ip-address` 单网卡起，只有 2 个 EFA，只能事后补挂：EFA 网卡**只能 stopped 时挂**（running 挂报 `IncorrectState: Interface type 'efa' can only be attached to an instance in state stopped`），要 `create-network-interface --interface-type efa` → `stop` → 逐个 `attach-network-interface --network-card-index N` → `start`，还会释放公网 IP 需重挂 EIP，绕一大圈还只补出 15 个。**正确姿势就是启动时一次性声明。**

## B. 坑：Capacity Block 起实例的特殊参数

B300 现货紧俏，多经 **Capacity Block** 预留。用 Capacity Block 的 Capacity Reservation 起实例，光带 `--capacity-reservation-specification` 会报：
```
InvalidParameterValue: The market type (purchasing) option is not valid
```
- **根因**：该 CR 的 `ReservationType=capacity-block`（独立市场类型，非普通 on-demand CR）。
- **修复【实测】**：`run-instances` 必须**同时**加 `--instance-market-options 'MarketType=capacity-block'`：
  ```bash
  aws ec2 run-instances ... \
    --instance-market-options 'MarketType=capacity-block' \
    --capacity-reservation-specification 'CapacityReservationTarget={CapacityReservationId=<cr-id>}'
  ```

## C. 坑：GDS 白名单不含 B300

`setup.sh --optimized-for-gds` 会报 `Instance type p6-b300.48xlarge does not support Lustre GDS`。
- **根因**：AWS `configure-efa-fsx-lustre-client.py` 的 `GDS_SUPPORTED_INSTANNCES` 白名单只有 `p5/p5e/p5en/p6-b200`，没收录 b300。
- **修复【实测】**：把 `"p6-b300.48xlarge",` 加进白名单数组即可（脚本已自动幂等处理），其余逻辑不动就跑通。
- **脚本幂等 bug（已修）**：不能用 `grep -q '"p6-b300.48xlarge"'` 判是否已加（该字符串在 .py 别处也出现，会误判），要精确匹配白名单数组行 `^    "p6-b300\.48xlarge",$`。

## D. 坑：DLAMI 默认没装 fio

`--skip-driver` 路径下若脚本静默装 fio 失败，会导致 FIO 全部 `command not found`。脚本已修：fio 安装独立于装驱动步骤，装不上直接 `exit 1`。
