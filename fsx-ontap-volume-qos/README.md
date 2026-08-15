# FSx for NetApp ONTAP — Volume QoS 限流实测

验证 FSx for NetApp ONTAP 的 volume-level QoS throughput ceiling（吞吐上限）
是否真正生效：给一个 volume 限制 **50 MB/s + 2000 IOPS**，用 fio 实测对比。

> 环境标识（文件系统 ID / SVM / IP / 实例 ID 等）已脱敏为 `REDACTED`。

## 背景：ONTAP QoS 是什么

ONTAP 提供 **volume（及 file / LUN / SVM）级别的 QoS 策略组**，可设置
**throughput ceiling（吞吐上限 / max）**，保证某个 workload 的吞吐不超过指定的
IOPS 或 MB/s，防止低优先级 workload 抢占资源、拖累关键业务。

官方文档：
- Set a throughput ceiling with ONTAP QoS policy groups
  https://docs.netapp.com/us-en/ontap/performance-admin/set-throughput-ceiling-qos-task.html
- Control FlexVol volume I/O performance with QoS
  https://docs.netapp.com/us-en/ontap/volumes/control-io-performance-qos-task.html

要点（来自官方文档）：
- QoS max/ceiling 保证 workload 吞吐不超过指定 IOPS 或 MBps。
- 可同时指定 IOPS 和 MB/s，**谁先达到限额就先触发限流**（whichever limit is reached first）。
- 默认存在 **burst**：短期可超 ceiling 50%、持续 1 秒（ONTAP 9.18.1 及更早不可修改，
  9.19.1 起可用 burst-percent / burst-duration / burst-iops 调整）。所以看限流效果要
  看**稳态均值**，而非瞬时峰值。
- `-is-shared false`（非共享）：限额对每个 workload 单独生效；共享则策略组内所有
  workload 总吞吐不超过 ceiling。
- **监控要在集群侧用 `qos statistics performance show`**，不要用 host 端工具看。

## 环境

| 项 | 值 |
|---|---|
| 服务 | FSx for NetApp ONTAP |
| 部署 | SINGLE_AZ_1, SSD 1024 GiB, ThroughputCapacity 128 MBps |
| Volume | 100 GiB, SecurityStyle=UNIX, JunctionPath=/qosvol |
| 挂载 | NFS v3（rsize/wsize=64K，ONTAP 服务端钳制）|
| 客户端 | 同 AZ/子网的 EC2（跳板机）|
| fio | 7.x |

## 操作步骤与命令

### 1. 创建文件系统 / SVM / volume（AWS CLI）

```bash
# 创建 FSx ONTAP 文件系统
aws fsx create-file-system \
  --region REDACTED \
  --file-system-type ONTAP \
  --storage-capacity 1024 --storage-type SSD \
  --subnet-ids REDACTED --security-group-ids REDACTED \
  --ontap-configuration '{"DeploymentType":"SINGLE_AZ_1","ThroughputCapacity":128,"PreferredSubnetId":"REDACTED","FsxAdminPassword":"REDACTED"}'

# 创建 SVM
aws fsx create-storage-virtual-machine \
  --region REDACTED --file-system-id REDACTED --name qossvm

# 创建 volume（100 GiB，UNIX 安全风格，不分层）
aws fsx create-volume --region REDACTED \
  --volume-type ONTAP --name qosvol \
  --ontap-configuration '{"StorageVirtualMachineId":"REDACTED","JunctionPath":"/qosvol","SizeInMegabytes":102400,"StorageEfficiencyEnabled":false,"SecurityStyle":"UNIX","TieringPolicy":{"Name":"NONE"}}'
```

### 2. 挂载 + fio 基线（无 QoS）

```bash
sudo mkdir -p /mnt/qosvol
sudo mount -t nfs -o nfsvers=3 <SVM_NFS_IP>:/qosvol /mnt/qosvol

# 基线：顺序写 1M，看未限流时能跑多高
sudo fio --name=seqwrite --directory=/mnt/qosvol \
  --rw=write --bs=1M --size=2G --numjobs=1 --iodepth=16 \
  --direct=1 --runtime=30 --time_based --group_reporting
```

### 3. 创建 QoS 策略组并关联 volume（ONTAP CLI，走 fsxadmin）

```bash
# ssh fsxadmin@<文件系统管理端点IP>   (注意: 是 Management endpoint，不是 SVM 的 IP)

# 建 QoS policy-group: 上限 2000 IOPS + 50 MB/s, 非共享
qos policy-group create -policy-group qos-limit-pg -vserver qossvm \
  -max-throughput 2000iops,50MB/s -is-shared false

# 确认
qos policy-group show -policy-group qos-limit-pg
#  qos-limit-pg  qossvm  user-defined  0  0-2000IOPS,50MB/s  false

# 把 QoS 策略组关联到 volume
volume modify -vserver qossvm -volume qosvol -qos-policy-group qos-limit-pg

# 集群侧监控（跑 fio 时另开一个会话看）
qos statistics performance show
```

### 4. fio 限流后测试

```bash
# TEST1 顺序写 1M —— 预期被 50MB/s 上限卡住
sudo fio --name=w --directory=/mnt/qosvol --rw=write --bs=1M \
  --size=2G --numjobs=1 --iodepth=16 --direct=1 --runtime=40 --time_based --group_reporting

# TEST2 顺序读 1M —— 预期被 50MB/s 上限卡住
sudo fio --name=r --directory=/mnt/qosvol --rw=read --bs=1M \
  --size=2G --numjobs=1 --iodepth=16 --direct=1 --runtime=40 --time_based --group_reporting

# TEST3 随机读 4k —— 小块，预期被 2000 IOPS 上限卡住
sudo fio --name=rr --directory=/mnt/qosvol --rw=randread --bs=4k \
  --size=2G --numjobs=4 --iodepth=32 --direct=1 --runtime=40 --time_based --group_reporting
```

## 测试结果

### 基线（无 QoS）
- 顺序写 1M：**≈ 139 MB/s**（142,317 KB/s，接近文件系统 128 MBps 吞吐上限）

### 限流后（QoS ceiling: 2000 IOPS + 50 MB/s, non-shared）

| 测试 | I/O 模式 | 实测结果 | 限额 | 命中 |
|---|---|---|---|---|
| 顺序写 | write bs=1M | 51,327 KB/s ≈ **50.1 MB/s** | 50 MB/s | ✅ MB/s ceiling |
| 顺序读 | read bs=1M | 51,540 KB/s ≈ **50.3 MB/s** | 50 MB/s | ✅ MB/s ceiling |
| 随机读 | randread bs=4k | **2,023 IOPS**（8,095 KB/s）| 2000 IOPS | ✅ IOPS ceiling |

## 结论

1. **ONTAP volume QoS throughput ceiling 真实有效**：无 QoS 顺序写 139 MB/s，
   加 50 MB/s ceiling 后精确压到 ~50 MB/s（误差 <2%）。

2. **IOPS 与 MB/s 双限，谁先到限谁生效**（实测印证官方文档）：
   - **大块 I/O（1M）**：MB/s 先触顶 → 限到 50 MB/s（此时 IOPS 仅约 50，远未到 2000）。
   - **小块 I/O（4k）**：IOPS 先触顶 → 限到 ~2023 IOPS（此时带宽仅 8 MB/s，远未到 50 MB/s）。

3. 实测值略微超限（50.1 / 50.3 MB/s、2023 IOPS）符合官方文档的默认 **burst** 行为
   （短期可超 ceiling 50%、持续 1 秒），稳态均值仍紧贴限额。

4. 限流粒度精准，是隔离多租户/多 workload、防止资源抢占的有效手段。

## 注意事项

- ONTAP CLI 用 `fsxadmin` 登录时，连的是**文件系统 Management endpoint IP**，
  不是 SVM 的 NFS/mgmt IP（登错 IP 会一直 Permission denied）。
- FSx ONTAP 服务端会把 NFS 请求的 rsize/wsize 钳制为 64K。
- 测限流效果看**稳态均值**，避开 burst 造成的瞬时超限误读。
- 监控在集群侧 `qos statistics performance show`，host 端工具看到的是被限后的实际值。
