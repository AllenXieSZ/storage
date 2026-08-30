# RETRY_AFTER_DELETE_BACKUP — 删 FSx Backup 后能否转 FlexGroup？（闭环验证）

> 实验日期：2026-08-30（承接同目录 REPORT.md 的 H1 实验，资源全部保留复用）
> 区域：us-east-2 | ONTAP 9.18.1P5 | Gen2 SINGLE_AZ_2 | FSxN fs-0184d1e4b81ce12a8 / SVM bkpfgsvm
> **本结论仅代表本次测试环境实测结果，不代表官方结论。**

---

## 一、结论先行（一句话）

**删除 FSx 卷级 Backup 后 → bkpvol 能转 FlexGroup 了，且转换只报 Warning、`[Job 54] Job succeeded`。**

坐实了 REPORT.md 的推断：**备份底层的 copy-to-cloud（SnapMirror-to-Cloud）关系是"可解除的软阻塞"，根因确是 FSx Backup，删除该备份即可解除阻塞。**

| 阶段 | backup-xxx 参考快照 | snapmirror show | conversion check-only | 结果 |
|---|---|---|---|---|
| **解除前（基线）** | 在 | 空 | **Error**（copy to cloud relationship） | bkpvol 仍 flexvol |
| 删 backup 后 t0（~30s） | **仍在** | 空 | **仍 Error**，snap delete 仍被拒 | 后台尚未释放 |
| 删 backup 后 ~1min | **消失** | 空 | **仅 Warning** | 阻塞解除 |
| 转换 start | 快照转 pre-conversion | 空 | — | **bkpvol → flexgroup ✓，Job 54 succeeded** |

---

## 二、逐字实测（每步命令 + 完整输出）

### 2.1 解除前基线（复用保留资源，确认仍处阻塞态）
- `volume snapshot show -vserver bkpfgsvm -volume bkpvol` → 含 `backup-01aaa29249100f88b`（+ 若干 hourly.*）。
- `volume conversion start ... -check-only true`（diag）逐字：
```
Error: command failed: Cannot convert volume "bkpvol" in Vserver "bkpfgsvm" to
       a FlexGroup. Correct the following issues and retry the command:
       * Conversion failed because the destination of a SnapMirror relationship
       with source volume "bkpvol" is not a FlexVol volume.  Delete and release
       the copy to cloud relationship from the source FlexVol volume "bkpvol".
```
- `snapmirror show` / `list-destinations` → 均空；`volume-style-extended = flexvol`。

### 2.2 删除 FSx 卷级备份（Step 2）
```
delete API @ 13:06:54 UTC
$ aws fsx delete-backup --backup-id backup-01aaa29249100f88b --region us-east-2
{ "BackupId": "backup-01aaa29249100f88b", "Lifecycle": "DELETED" }
```
- `describe-backups` 轮询：**~10s 后**报 `BackupNotFound ... does not exist`（AWS 侧记录消失）。

### 2.3 删 backup 后 t0（约删后 30s）——后台尚未释放
- `volume snapshot show` → `backup-01aaa29249100f88b` **仍在**。
- `volume conversion start -check-only true` → **仍 Error**（同 copy-to-cloud 报错）。
- `volume snapshot delete ... -snapshot backup-01aaa29249100f88b` → **仍被拒**：
```
Error: command failed: This snapshot is currently used as a reference snapshot
       by one or more SnapMirror relationships. ...
```
→ 说明 AWS `delete-backup` API 返回 DELETED 只是登记删除，**底层 copy-to-cloud/SnapMirror-to-Cloud 关系的释放是异步的**，t0 时刻尚未完成。

### 2.4 删 backup 后 ~1min（轮询 ROUND 1）——阻塞解除
- `volume snapshot show -fields snapshot` → **`backup-01aaa29249100f88b` 已消失**，只剩 hourly.*。
- `snapmirror show` / `list-destinations` → 仍空。
- `volume conversion start -check-only true`（diag）逐字，**从 Error 变成仅 Warning**：
```
Conversion of volume "bkpvol" in Vserver "bkpfgsvm" to a FlexGroup can proceed
with the following warnings:
* After the volume is converted to a FlexGroup, it will not be possible to change it back to a flexible volume.
* Converting flexible volume "bkpvol" ... snapshots ... set to "pre-conversion". Pre-conversion snapshots cannot be restored.
* Converting the volume to a FlexGroup will not add additional resources for capacity. ... use the "volume expand" command ...
```

### 2.5 实际转换 start（Step 4）——Job succeeded
```
$ volume conversion start -vserver bkpfgsvm -volume bkpvol
[Job 54] Job is queued: Converting flexible volume to FlexGroup.
[Job 54] Renaming volume.
[Job 54] success
[Job 54] Job succeeded: success
```

### 2.6 转换后终态
```
vserver  volume         volume-style-extended
bkpfgsvm bkpvol         flexgroup             ← 成功转换
bkpfgsvm bkpvol__0001   flexgroup-constituent
bkpfgsvm cleanvol       flexgroup             （对照组，早前已转）
...
snapshot: hourly.* + convert.2026-08-30_130826（pre-conversion 快照，正常产物）
snapmirror show / list-destinations → 空
```

---

## 三、时间线（耗时记录）

| 事件 | 时刻 (UTC) | 相对删除 |
|---|---|---|
| `aws fsx delete-backup` 调用，返回 DELETED | 13:06:54 | 0 |
| `describe-backups` 报 BackupNotFound | 13:07:04 | ~10s |
| t0 复查：backup 快照仍在 / 转换仍 Error / snap delete 仍被拒 | ~13:07:25 | ~30s |
| ROUND1：backup 快照消失 / 转换 check-only 变 Warning | ~13:07:58 | **~1min** |
| `volume conversion start` → Job 54 succeeded，bkpvol=flexgroup | ~13:08:10 | ~1.5min |

**后台释放 copy-to-cloud 关系 + 移除 backup 参考快照的实测耗时窗口：删除后约 30s～1min 之间。** 非常快，无需等 10–30min。

---

## 四、机制闭环（结合 REPORT.md）

1. 开 FSx 卷级 Backup → 源卷内打 `backup-<id>` 参考快照 + 底层建 **SnapMirror-to-Cloud（copy-to-cloud）关系**（对客户 CLI 隐藏，`snapmirror show` 空）。
2. 该关系令源卷成为"活动 SnapMirror source" → 违反 FlexVol→FlexGroup 转换前置条件 → **check-only/start 均报 Error 阻塞**。
3. `aws fsx delete-backup` → AWS 侧记录 ~10s 删除；**底层 copy-to-cloud 关系与 backup 参考快照的释放为异步**，本次约 **30s～1min** 内完成。
4. 释放完成后：backup 参考快照消失 → 转换 check-only 仅剩 Warning → `volume conversion start` **Job succeeded，bkpvol 成功变 flexgroup**。

**⇒ Backup 造成的 copy-to-cloud 阻塞是可解除的软阻塞：删除该卷的 FSx 备份、等后台异步释放（本次 ≤1min），即可正常转 FlexGroup。**

---

## 五、资源（全部保留，删除前先问伟伟）

复用 REPORT.md 的资源：FSxN `fs-0184d1e4b81ce12a8`，SVM `bkpfgsvm`，bkpvol `fsvol-0b96244abc8fcb7bd`（现已 flexgroup），cleanvol `fsvol-0ff9b92f659a38ed5`，EC2 `i-0e64df080d1d36235`。
**本次已删除的仅一个对象**：FSx 卷级备份 `backup-01aaa29249100f88b`（实验必需，已删）。其余资源默认保留。

逐字 log 见 `logs/`：`baseline_conv_checkonly_before_delete.txt`、`delete_backup.txt`、`after_delete_snap_and_sm_t0.txt`、`after_delete_snap_delete_attempt_t0.txt`、`after_delete_conv_checkonly_t0.txt`、`release_poll.txt`、`after_delete_conv_start.txt`、`after_delete_final_state.txt`。

---

*本结论仅代表本次测试环境实测结果，不代表官方结论。*
