# FSx ONTAP：开过 FSx 原生 Backup 的 FlexVol 能否就地转 FlexGroup？（H1 真凶验证）

> 实验日期：2026-08-30 | 区域：us-east-2 | ONTAP 9.18.1P5 | Gen2 SINGLE_AZ_2
> **本结论仅代表本次测试环境实测结果，不代表官方结论。**

---

## 一、结论先行

**H1 成立，且是硬 Error 阻塞（不是 Warning）。**

在同一 FSxN / 同一 SVM 内建两个内容一致（各 10 GiB / 100 文件）的 FlexVol 做对照，**唯一变量 = 是否被 FSx 卷级 Backup 备份过一次**：

| 卷 | 是否备份 | backup-xxx 参考快照 | conversion check-only | conversion start | 转换后 |
|---|---|---|---|---|---|
| **cleanvol**（对照） | 从不备份 | 无 | 仅 **Warning**，可继续 | `[Job 48] Job succeeded` | **flexgroup ✓** |
| **bkpvol**（实验） | 卷级备份 1 次 | 有（留存 60min+ 稳定） | **Error**（copy to cloud） | **Error，转换未发生** | 仍 **flexvol ✗** |

三点定案（均为逐字实测输出，非推断）：

1. **备份过的卷报的是 `Error:` 而非 `Warning:`**——check-only 与实际 start 输出里明确是 `Error: command failed: Cannot convert...`，不是 warning。
2. **Job 未 succeeded、卷仍是 flexvol**——实际 `volume conversion start` 直接以 Error 收场，`volume show` 确认 bkpvol 仍为 `flexvol`，转换根本没发生。
3. **对照组 cleanvol 同环境同命令成功转 flexgroup**——证明阻塞的唯一原因就是"备份留下的 copy-to-cloud 关系"，别无其它变量。

**因此：对"旧 fs-0ab60 被 copy-to-cloud relationship 阻塞"的最终判定 = 真凶是 FSx 原生 Backup（会留隐藏 SnapMirror-to-Cloud 关系 + backup 参考快照），与 DataSync 无关。**
2026-08-30 早前那次"DataSync 走 NFS 不留 SnapMirror、不阻塞转换"的纠错结论也一并被本实验佐证——DataSync 无辜，Backup 才是元凶。

> ⚠️ 对伟伟"可能只是 warning 不阻塞"这一质疑的回答：**在本次实测里它确实是 Error，且确实阻塞。** 但请注意语义边界——阻塞的不是"留了个 backup 快照"本身，而是"备份底层建立的 copy-to-cloud（SnapMirror-to-Cloud）关系"。留快照 ≠ 阻塞；有 copy-to-cloud 关系 = 阻塞。

---

## 二、实验设计（严格隔离单一变量）

- **1 个全新 FSxN**（不复用任何被动过的旧 FS，避免污染）：Gen2 SINGLE_AZ_2，1 HA pair，1536 MB/s，2048 GB SSD。
- **1 个 SVM（bkpfgsvm）+ 2 个 FlexVol**（同 FS 同 SVM，最大化隔离）：
  - `bkpvol`（/bkpvol, 512GB, UNIX, StorageEfficiency off, Tiering NONE）→ 实验组：备份一次
  - `cleanvol`（/cleanvol, 512GB, 同参数）→ 对照组：从不备份
- 两卷各写 **10 GiB = 100 文件 × 100 MiB**（dd urandom），数据量一致。
- **对照唯一变量**：只对 bkpvol 做一次 FSx 卷级 Backup，cleanvol 全程不备份。

按伟伟修正意见执行的两点：
1. **备份真正跑完并沉淀**：`aws fsx create-backup --volume-id <bkpvol>` 到 AVAILABLE 后，**再等 ~60 分钟**让 backup 参考快照稳定留存，期间 30/60min 复查该快照持续存在，才做转换。
2. **裁判点改为 Warning vs Error**：对 check-only 与实际 start **逐字记录**，明确区分 `Warning:` / `Error:` 及 Job 是否 succeeded，不预设 H1 成立。

---

## 三、关键实测输出（逐字）

### 3.1 备份【前】基线（diag 级，两卷都查）
两卷 `snapmirror show` / `list-destinations` / `show-history` 全空，`volume snapshot show` 无快照，**snapshot-count = 0**。

### 3.2 FSx 卷级 Backup（仅 bkpvol）
- `aws fsx create-backup --volume-id fsvol-0b96244abc8fcb7bd` → `backup-01aaa29249100f88b`
- 到 AVAILABLE 耗时 **~259s（约 4.5 min）**。

### 3.3 备份【后】状态对照（diag 级）
```
bkpvol  snapshots: backup-01aaa29249100f88b + hourly.2026-08-30_0505   snapshot-count=2
cleanvol snapshots: hourly.2026-08-30_0505                              snapshot-count=1
```
- bkpvol 出现 **`backup-01aaa29249100f88b` 参考快照**（cleanvol 没有）——这是两卷唯一实质差异。
- `hourly.*` 是 SVM 默认 snapshot-policy 的定时快照，两卷都有，属公平的同类项。
- backup 参考快照留存 **60min+ 稳定不变**（30min/60min 两次复查一致）。
- **两卷 `snapmirror show`（含 diag `-expand`、`list-destinations`）始终为空**——copy-to-cloud 关系对客户 CLI 隐藏。

### 3.4 cleanvol 转换（对照）
check-only（**仅 Warning**）：
```
Conversion of volume "cleanvol" ... can proceed with the following warnings:
* ... it will not be possible to change it back to a flexible volume.
* ... snapshots ... set to "pre-conversion". Pre-conversion snapshots cannot be restored.
* ... use the "volume expand" command to add resources.
```
实际 start：
```
[Job 48] Job is queued: Converting flexible volume to FlexGroup.
[Job 48] Job succeeded: success
→ volume-style-extended: flexgroup   ✓
```

### 3.5 bkpvol 转换（实验）——**Error，阻塞**
check-only 与实际 start **输出完全一致，都是 Error**：
```
Error: command failed: Cannot convert volume "bkpvol" in Vserver "bkpfgsvm" to
       a FlexGroup. Correct the following issues and retry the command:
       * Conversion failed because the destination of a SnapMirror relationship
       with source volume "bkpvol" is not a FlexVol volume.  Delete and release
       the copy to cloud relationship from the source FlexVol volume "bkpvol".
→ volume-style-extended: flexvol（转换未发生）  ✗
```

### 3.6 佐证：删 backup 快照报 SnapMirror 引用
```
volume snapshot delete ... -snapshot backup-01aaa29249100f88b
Error: command failed: This snapshot is currently used as a reference snapshot
       by one or more SnapMirror relationships. Deleting the snapshot can cause
       future SnapMirror operations to fail.
```
→ 明确存在**引用该 backup 快照的 SnapMirror 关系**，只是 `snapmirror show` 看不到（SnapMirror-to-Cloud 由 FSx 后台托管）。这正是转换错误里"copy to cloud relationship"的来源。

---

## 四、耗时记录

| 操作 | 本次实测 |
|---|---|
| FSxN 创建到 AVAILABLE | ~14 min |
| SVM 创建 | ~2 min |
| 两卷创建 | <1 min |
| 灌数据（2×10GiB） | ~1.5 min |
| **FSx 卷级 Backup 到 AVAILABLE** | **~259s（~4.5 min）** |
| backup 快照稳定沉淀观察 | 60 min（按伟伟要求） |
| FlexVol→FlexGroup 转换（cleanvol 成功） | <1s（改元数据，Job succeeded） |
| bkpvol 转换 | 立即 Error 返回，未发生 |

---

## 五、机制总结（基于本次实测 + AWS 文档语义）

1. FSx 原生**卷级 Backup** 会在源卷内打一个 `backup-<backupId>` 参考快照，并在底层建立 **SnapMirror-to-Cloud（copy-to-cloud）关系**把数据搬到 S3。
2. 该 SnapMirror-to-Cloud 关系**对客户 ONTAP CLI 隐藏**（`snapmirror show` 空），但真实存在——可由"删 backup 快照被拒（reference snapshot by SnapMirror relationships）"证明。
3. FlexVol→FlexGroup 就地转换要求源卷**不能是任何活动 SnapMirror 关系的 source**（NetApp 官方前置条件）。备份留下的 copy-to-cloud 关系正好违反此条 → 转换报 **Error** 阻塞。
4. 因此："留 backup 快照"不是阻塞原因，"备份底层的 copy-to-cloud 关系"才是。要转 FlexGroup，需先解除该关系（本环境下删除该卷的所有 FSx 备份 / 释放 copy-to-cloud，再重试；本次未做破坏性解除，资源保留）。

---

## 五之补 — AWS 官方文档原话（英文原文，实锤佐证）

我们的实测结论与 **AWS FSx for ONTAP 官方文档**完全一致。文档在 "Volume styles" 一节明确要求：**用 ONTAP CLI 把 FlexVol 转 FlexGroup 前，必须先删除该 FlexVol 的所有备份。**

> **Note**
> If you want to use the ONTAP CLI to convert a FlexVol volume to a FlexGroup volume, make sure that you delete any backups of the FlexVol volume before converting it. ONTAP doesn't automatically rebalance data as part of the conversion, so the data might be imbalanced across the FlexGroup constituents.

Source: [Managing FSx for ONTAP volumes — Volume styles](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-volumes.html#volume-styles) (docs.aws.amazon.com, retrieved 2026-08-30)

同一节的相关原文（转换语义 + 推荐用 DataSync 迁移以均衡分布）：

> You can convert a volume with the FlexVol style to the FlexGroup style with the ONTAP CLI, which creates a FlexGroup with a single constituent. However, we recommend that you use AWS DataSync to move data between a FlexVol volume and a new FlexGroup volume to ensure that the data is evenly distributed across the FlexGroup's constituents.

**解读**：
- "delete **any backups** of the FlexVol volume before converting it" —— 官方把"有备份"直接列为转换的**前置阻塞项**，与本实验实测（bkpvol 备份后 conversion 报 Error）逐字对应。
- 注意官方这句只点名 **backups**，并未提到 DataSync —— 反过来印证 2026-08-30 早前那次 "DataSync(NFS) 不阻塞转换" 的纠错也是对的。
- 官方还建议**用 DataSync 迁移**来实现 FlexGroup constituent 间的数据均衡（因为就地转换后是单 constituent、且 ONTAP 不自动 rebalance）——DataSync 在这里是"推荐工具"而非"阻塞源"。

---

## 六、资源清单（全部保留，删除前先问伟伟）

见同目录 `RESOURCES.md`。关键：FSxN `fs-0184d1e4b81ce12a8`，SVM `svm-0af4df6f58574e440`（bkpfgsvm），bkpvol `fsvol-0b96244abc8fcb7bd`，cleanvol `fsvol-0ff9b92f659a38ed5`，backup `backup-01aaa29249100f88b`，EC2 `i-0e64df080d1d36235`。

---

*本结论仅代表本次测试环境实测结果，不代表官方结论。*
