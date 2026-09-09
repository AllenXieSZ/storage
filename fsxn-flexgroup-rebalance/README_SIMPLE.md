# FSx for NetApp ONTAP：单 HA pair → 2 HA pair + FlexVol → FlexGroup 就地转换

一份面向"第一次接触"的简明操作指南：把一个 FSxN 文件系统从**单 HA pair 扩成 2 HA pair**，再把卷从 **FlexVol 就地转成 FlexGroup**（只转换、不做数据重新分布），并给出每步的完整 CLI 与实测耗时。

> 环境：AWS us-east-2，FSx ONTAP **Gen2（SINGLE_AZ_2）**，ONTAP 9.18.x。

---

## 背景概念（30 秒读懂）

- **HA pair**：FSxN 文件系统由一对或多对"高可用文件服务器"组成，每个 HA pair 自带一个 **aggregate（一组物理磁盘的逻辑集合）**。Gen2 Single-AZ 最多可扩到 12 个 HA pair，横向扩容量和性能。
- **FlexVol**：传统单卷，数据只落在**一个** aggregate 上，容量/性能受限于该 aggregate。
- **FlexGroup**：由多个 **constituent（成员卷）** 组成的"大卷"，可横跨多个 aggregate，把数据/元数据分散到多个 HA pair，实现横向扩展。
- **就地转换（in-place conversion）**：把已有 FlexVol 原地变成 FlexGroup，**只改卷的元数据**，不复制/搬迁数据。

---

## 目标流程

1. 建一个**单 HA pair、吞吐较高**的 FSxN（吞吐要够高，才能直接扩 2 HA pair）
2. 写入数据
3. **扩成 2 HA pair**（记录耗时）
4. **FlexVol → FlexGroup 就地转换**（只转，不做 rebalance；记录耗时）

---

## 关键结论（先看这里）

| 操作 | 实测耗时 | 说明 |
|---|---|---|
| 单 HA → 2 HA pair 扩展 | **约 12 分钟** | 官方称通常几分钟；不中断在线服务 |
| **FlexVol → FlexGroup 就地转换（只转，不 rebalance）** | **⚡ 秒级（<1 分钟）** | **只改卷 style 元数据、不移动任何数据块，与卷内数据量无关** |

**为什么"只转"是秒级**：转换只是把卷的类型从 flexvol 标记改成 flexgroup，生成**一个 constituent，仍留在原来的 aggregate 上**，一个数据块都不搬。所以无论卷里是 5 GB 还是 5 TB，都是秒级完成。
如果之后想让数据真正分散到第二个 aggregate（HA pair），才需要额外做 `volume expand`（加 constituent）+ `volume rebalance`（搬数据）——那一步才耗时，本指南不做。

---

## 两个必须知道的前提

1. **起点吞吐要够高**：单 HA pair 若吞吐太低（如 384 MBps），无法直接扩到 2 HA pair（2 HA 每对最低要 1536 MBps）。**建议创建时就把吞吐设为 1536 MBps**，直接满足扩 2 HA 的条件。
2. **扩 HA 时要同时翻倍容量、并保留 per-HA 吞吐**：只传 `HAPairs=2` 会被 API 拒绝，必须同时给 `--storage-capacity`（翻倍）和 `ThroughputCapacityPerHAPair`（保持原值）。

---

## 完整 CLI

占位符：`<FSID>` `<SVM>` `<VOL>` `<SUBNET_ID>` `<SG_ID>` `<MGMT_IP>` `<NFS_IP>` `<PASSWORD>`

### 1. 建单 HA pair 文件系统（吞吐 1536，可直接扩 2 HA 的起点）
```bash
aws fsx create-file-system --file-system-type ONTAP \
  --storage-capacity 1024 \
  --subnet-ids <SUBNET_ID> \
  --security-group-ids <SG_ID> \
  --ontap-configuration '{
    "DeploymentType":"SINGLE_AZ_2",
    "ThroughputCapacityPerHAPair":1536,
    "HAPairs":1,
    "PreferredSubnetId":"<SUBNET_ID>",
    "FsxAdminPassword":"<PASSWORD>"
  }' \
  --region us-east-2
```

### 2. 建 SVM 和 FlexVol
```bash
aws fsx create-storage-virtual-machine --file-system-id <FSID> --name mysvm --region us-east-2

aws fsx create-volume --volume-type ONTAP --name myvol \
  --ontap-configuration '{
    "StorageVirtualMachineId":"<SVM>",
    "SizeInMegabytes":665600,
    "JunctionPath":"/myvol",
    "SecurityStyle":"UNIX",
    "StorageEfficiencyEnabled":false
  }' \
  --region us-east-2
```

### 3. 挂载并写入数据（示例：写几个大文件）
```bash
mount -t nfs -o nfsvers=3 <NFS_IP>:/myvol /mnt/myvol
for i in 1 2 3 4 5; do
  dd if=/dev/zero of=/mnt/myvol/big_$i.dat bs=1M count=102400 oflag=direct
done
```

### 4. ⏱️ 扩成 2 HA pair（storage 必须同时翻倍 + 显式保留 per-HA 吞吐）
```bash
aws fsx update-file-system --file-system-id <FSID> \
  --storage-capacity 2048 \
  --ontap-configuration '{"HAPairs":2,"ThroughputCapacityPerHAPair":1536}' \
  --region us-east-2

# 轮询直到 Lifecycle 回到 AVAILABLE
aws fsx describe-file-systems --file-system-ids <FSID> --region us-east-2 \
  --query 'FileSystems[].Lifecycle' --output text
```

### 5. ⏱️ FlexVol → FlexGroup 就地转换（只转，不 rebalance）
通过跳板机登录 ONTAP CLI（`sshpass -p <PASSWORD> ssh fsxadmin@<MGMT_IP>`），转换命令是 diag 级：
```bash
# 进入 diag 权限
set -privilege diagnostic -confirmations off

# 转换前查看卷类型（应为 flexvol）
volume show -vserver <SVM> -volume <VOL> -fields volume-style-extended,aggr-list

# （可选）先关 storage efficiency，避免出现 warning
volume efficiency off -vserver <SVM> -volume <VOL>

# （可选）check-only 预检，确认只有 warning、无 error
volume conversion start -vserver <SVM> -volume <VOL> -check-only true

# 正式转换 —— 秒级返回 Job succeeded
volume conversion start -vserver <SVM> -volume <VOL> -foreground true

# 转换后确认：已变 flexgroup，单 constituent <VOL>__0001，仍在原 aggregate
volume show -vserver <SVM> -volume <VOL> -fields volume-style-extended,aggr-list
volume show -vserver <SVM> -volume <VOL>* -fields aggregate,used -is-constituent true
```

---

## 常见注意事项

- **转换不可逆**：FlexGroup 不能转回 FlexVol。
- **转换前置条件**：卷需 online；建议先关 storage efficiency（FSx 上只警告不拦截）；卷不能是某些 SnapMirror 关系的一方、不能有 SAN LUN、quota 需关闭等。若 check-only 报 error，按提示修复。
- **只转 vs 转+均衡**：本指南只做"转换"（秒级）。若要数据真正分布到 2 个 HA pair 的 aggregate 上，转换后再执行：
  ```bash
  volume expand -vserver <SVM> -volume <VOL> -aggr-list aggr1,aggr2 -aggr-list-multiplier 4
  ```
  并写入足够多的文件（FlexGroup 按文件哈希分散，文件越多越均匀），或使用 `volume rebalance`。这一步会真正搬数据，耗时取决于数据量。

---

## 命令速查

```
建 FS（1HA/1536）        → aws fsx create-file-system ... HAPairs:1, ThroughputCapacityPerHAPair:1536
扩 2HA                   → aws fsx update-file-system ... --storage-capacity 2048 ... HAPairs:2, ThroughputCapacityPerHAPair:1536
只转 FlexGroup（秒级）    → set -priv diag; volume conversion start -vserver <SVM> -volume <VOL> -foreground true
转后再均衡（可选，耗时）  → volume expand ... -aggr-list aggr1,aggr2 -aggr-list-multiplier 4
```
