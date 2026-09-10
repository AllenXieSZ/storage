# REPORT: FSxN 单HA→2HA + FlexVol→FlexGroup（只转不平衡）实测

**日期**: 2026-09-08　**区域**: us-east-2 (Ohio)　**账号**: <AWS_ACCOUNT_ID>
**执行**: 后台子 agent　**ONTAP**: 9.18.x　**部署类型**: Gen2 `SINGLE_AZ_2`

---

## 🎯 两个关键耗时（结论先行）

| 操作 | 耗时 | 备注 |
|---|---|---|
| **① 单 HA → 2 HA pair 扩展** | **≈ 11.7 分钟**（703s） | 08:26:31 → ~08:38:14，AdministrativeAction COMPLETED。比 8-28 实测（26min）快一半以上 |
| **② FlexVol → FlexGroup 就地转换（只转不平衡）** | **≈ 数秒（实测 11s 含登录/查询，转换 Job 本身近乎瞬时）** | `[Job 62] Job succeeded` 与 "queued" 几乎同一时刻返回；500GB 数据零搬迁 |

**核心结论**：
- **FlexVol→FlexGroup 只转不做 rebalance/expand，确实极快（秒级）**。因为"只转"仅是把卷的 style 元数据从 flexvol 改为 flexgroup（产生单 constituent FlexGroup），**不移动任何数据块**——503GB 数据全程留在原 aggr1，不搬迁，所以与数据量无关，秒级完成。

---

## 📋 操作 → CLI 命令 → 耗时（完整补全）

| # | 操作 | 完整 CLI / ONTAP 命令 | 耗时 |
|---|---|---|---|
| 1 | 建 Gen2 单 HA（高吞吐起点，可直接扩 2HA） | `aws fsx create-file-system --file-system-type ONTAP --storage-capacity 1024 --subnet-ids subnet-0c551a33e366d52d4 --security-group-ids sg-00ca35d004d81089b --ontap-configuration '{"DeploymentType":"SINGLE_AZ_2","ThroughputCapacityPerHAPair":1536,"HAPairs":1,"PreferredSubnetId":"subnet-0c551a33e366d52d4","FsxAdminPassword":"<REDACTED>"}' --region us-east-2` | ~13min（AVAILABLE） |
| 2 | 关自动备份（避免隐藏 copy-to-cloud 阻塞转换） | `aws fsx update-file-system --file-system-id <fsid> --ontap-configuration '{"AutomaticBackupRetentionDays":0}' --region us-east-2` | 秒级 |
| 3 | 建 SVM | `aws fsx create-storage-virtual-machine --file-system-id <fsid> --name fgsvm --region us-east-2` | ~1min |
| 4 | 建 FlexVol（关 storage efficiency） | `aws fsx create-volume --volume-type ONTAP --name fgvol --ontap-configuration '{"StorageVirtualMachineId":"<svm>","SizeInMegabytes":665600,"JunctionPath":"/fgvol","SecurityStyle":"UNIX","StorageEfficiencyEnabled":false}' --region us-east-2` | ~1min |
| 5 | 挂载 + 写 500GB（5×100GB 大文件） | `mount -t nfs -o nfsvers=3 172.31.37.39:/fgvol /mnt/fgvol` ；`for i in 1 2 3 4 5; do dd if=/dev/zero of=/mnt/fgvol/big_$i.dat bs=1M count=102400 oflag=direct; done` | ~15.8min（~540MB/s） |
| **6** | **⏱️① 单 HA → 2 HA pair 扩展**（StorageCapacity 必须同时翻倍 + 显式保留 per-HA 吞吐） | `aws fsx update-file-system --file-system-id <fsid> --storage-capacity 2048 --ontap-configuration '{"HAPairs":2,"ThroughputCapacityPerHAPair":1536}' --region us-east-2` | **≈ 11.7 分钟** |
| **7** | **⏱️② FlexVol → FlexGroup 就地转换（只转，不 rebalance / 不 expand）** | ONTAP CLI（diag 级）：`set -privilege diagnostic -confirmations off` ；`volume conversion start -vserver fgsvm -volume fgvol -foreground true` | **≈ 秒级（Job 62 succeeded，数据零搬迁）** |

> **重点说明（本次新增结论）**：**第 7 步「只做 style 转换、不做数据 rebalance」耗时是秒级**，与卷内数据量（本次 503GB）无关——转换只改元数据、生成单 constituent（`fgvol__0001` 仍在原 aggr1），**不移动任何数据块**。若之后想让数据均分到 aggr2，才需额外执行 `volume expand`（加 constituent）+ `volume rebalance`（搬数据），那才是耗时的部分（本次未做）。
- **扩 2 HA pair 本次约 11.7min**（比历史 8-28 的 ~26min 快很多，可能与本次 storage 较小/后台调度差异有关）。
- **以 1536 MBps 单 HA 起点建**（而非 384）成功避开"扩 2HA 吞吐冲突死锁"；扩 HA 时 API 强制 `StorageCapacity 1024→2048` 且 `ThroughputCapacityPerHAPair` 保持 1536（总吞吐变 3072）。

---

## 关键前置发现（本次实测新增，纠正 HANDOFF 假设）

HANDOFF 里写的扩 HA 命令 `--ontap-configuration HAPairs=2` **单独提交会被 API 拒绝**。实测报错：

```
An error occurred (BadRequest) when calling the UpdateFileSystem operation:
To change HAPairs from 1 to 2, please include the following in your request
(and only the following): StorageCapacity must be updated to 2048, and either
(ThroughputCapacity must be updated to 3072 or ThroughputCapacityPerHAPair
must be explicitly passed with the current value of 1536).
```

**正确命令**（本次采用，成功）：
```bash
aws fsx update-file-system --file-system-id fs-065cd1eb595443c6d \
  --storage-capacity 2048 \
  --ontap-configuration '{"HAPairs":2,"ThroughputCapacityPerHAPair":1536}' \
  --region us-east-2
```
即：**加 HA pair 时必须同时把 StorageCapacity 翻倍（每 HA 一份 aggregate），并显式保留 per-HA 吞吐**。这印证了官方"加 HA 沿用现有 per-HA 吞吐、容量按 HA 均分"的设计。

---

## 完整执行时间线

| 时间 (UTC) | 事件 |
|---|---|
| 07:53:00 | 创建 FSxN fs-065cd1eb595443c6d（SINGLE_AZ_2, 1024GB, 1536MBps, 1 HA） |
| 07:53 | `update-file-system AutomaticBackupRetentionDays=0` 关闭自动备份（避免隐藏 copy-to-cloud 阻塞转换） |
| 08:06:21 | FSxN AVAILABLE（创建 ~13min） |
| 08:07:45 | SVM `fgsvm` CREATED（NFS IP 172.31.37.39） |
| 08:08:49 | FlexVol `fgvol` CREATED（650GB, UNIX, junction /fgvol, StorageEfficiency 关闭） |
| 08:09 | NFS 挂载到跳板机 /mnt/fgvol |
| 08:09:27 → 08:25:16 | 写 500GB 数据（5×100GB, dd oflag=direct）= **949s ≈ 15.8min（~540MB/s）** |
| **08:26:31** | **⏱️① 提交扩 2 HA pair（START）** |
| **08:38:14** | **⏱️① 扩 2 HA COMPLETED（HA=2, SC=2048）≈ 11.7min** |
| 08:38 | 确认 2 个 aggregate：aggr1(node-01) + aggr2(node-03) |
| 08:39 | 前置检查：efficiency Disabled、quota off、snapmirror 空、卷 online |
| **08:39:15** | **⏱️② FlexVol→FlexGroup 转换（diag, foreground）START** |
| **08:39:26** | **⏱️② [Job 62] Job succeeded — style 变 flexgroup（≈11s 含登录/查询，转换本身秒级）** |

---

## 命令输出（关键片段）

### 扩 HA 前卷状态（flexvol, aggr1）
```
vserver volume     aggr-list size  state  volume-style volume-style-extended junction-path
fgsvm   fgvol      aggr1     650GB online flex         flexvol               /fgvol
```

### 扩 2HA 后 aggregate（2 个 aggr = 2 HA pair）
```
aggregate node                      size
aggr1     FsxId065cd1eb595443c6d-01 907.0GB
aggr2     FsxId065cd1eb595443c6d-03 907.0GB
```

### FlexVol→FlexGroup 转换（diag foreground）
```
FsxId...::> set -privilege diagnostic -confirmations off
FsxId...::*> volume show -vserver fgsvm -volume fgvol -fields volume-style-extended
   fgsvm   fgvol  flexvol
FsxId...::*> volume conversion start -vserver fgsvm -volume fgvol -foreground true
   [Job 62] Job is queued: Converting flexible volume to FlexGroup.
   [Job 62] success
   [Job 62] Job succeeded: success
FsxId...::*> volume show -vserver fgsvm -volume fgvol -fields volume-style-extended,aggr-list
   fgsvm   fgvol  aggr1  flexgroup
```

### 转换后：单 constituent FlexGroup（未 expand，仍全在 aggr1）
```
vserver volume      aggr-list size  volume-style-extended
fgsvm   fgvol__0001 aggr1     650GB flexgroup-constituent
```
- FlexGroup `fgvol` 仅 **1 个 constituent `fgvol__0001`**，位于 **aggr1**（原 aggregate）。
- **未做 expand / volume rebalance**——数据零搬迁，符合"只转不平衡"。

### 数据完整性（转换后 NFS 可读，503GB 在位）
```
172.31.37.39:/fgvol  618G  503G  115G  82% /mnt/fgvol
big_1.dat ... big_5.dat  各 107374182400 bytes (100GiB)
```

---

## 资源 ID（已于 2026-09-08 全部删除清理）

> ⚠️ 本批测试资源已按 Volume → SVM → FS 顺序删除，无残留计费。以下 ID 仅作记录。

| 资源 | ID / 值 | 状态 |
|---|---|---|
| FSxN 文件系统 | fs-065cd1eb595443c6d（Gen2 SINGLE_AZ_2, 2HA, 2048GB, 3072MBps 总吞吐） | 已删除 |
| SVM | svm-077ec3ac8c23f276c（fgsvm） | 已删除 |
| Volume | fsvol-0e3bc4652e5c0f8e4（fgvol / FlexGroup 单 constituent fgvol__0001 @ aggr1） | 已删除 |
| VPC / Subnet | vpc-0c28d2a9082ef222e / subnet-0c551a33e366d52d4 (us-east-2c) | 保留（共用） |
| Security Group | sg-00ca35d004d81089b | 保留（共用） |
| 跳板机 | i-0dffb881b2a90daa2 (SSM Online) | 保留（共用，已 umount /mnt/fgvol） |

**清理顺序（已执行）**：umount /mnt/fgvol → 删 volume → 删 SVM → 删 FS。

---

## 铁律遵守情况
- ✅ 全程未碰 DataSync / FSx Backup（并主动关闭 AutomaticBackupRetentionDays=0），避免隐藏 SnapMirror-to-Cloud 阻塞转换 → 转换零阻力（Job succeeded）。
- ✅ 只转不平衡：未 expand、未 volume rebalance、未写海量小文件（500GB=5 个大文件）。
- ✅ diag 命令走 `set -privilege diagnostic`。
- ✅ 技术操作以官方 API 报错/CLI 实测为准，纠正了 HANDOFF 中扩 HA 命令的写法。

## 对比 8-28 历史实测
| 项 | 8-28 | 本次 9-08 |
|---|---|---|
| 单 HA 起点吞吐 | 384（需先升 1536，~44min） | **直接 1536 起点，省掉升吞吐步骤** |
| 扩 HA 耗时 | ~26min | **~11.7min** |
| FlexVol→FlexGroup 只转 | <1min（Job succeeded） | **~秒级（Job 62 succeeded，与 8-28 一致）** |
| 转换阻塞 | 备份过的卷被 copy-to-cloud 阻塞 | 本卷从不备份 → 零阻塞，秒转 |
