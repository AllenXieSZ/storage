# LESSONS — backup-flexgroup-rootcause

> 仅本次测试环境实测（us-east-2 / ONTAP 9.18.1P5 / Gen2 SINGLE_AZ_2），不代表官方结论。

## 1. FSx 原生 Backup 是 FlexVol→FlexGroup 转换的真凶（Error 硬阻塞）
- 同 FSxN/SVM 内两个内容一致的 FlexVol，唯一变量=是否备份过一次：备份过的 → conversion 报 `Error: ... Delete and release the copy to cloud relationship`，Job 未成功，仍是 flexvol；从不备份的 → 同命令 `Job succeeded` 转成 flexgroup。
- 与 DataSync 无关（DataSync 走 NFS 不留 SnapMirror，早前已纠错）。

## 2. Backup 的 copy-to-cloud 关系对客户 CLI 隐藏，但真实存在
- `snapmirror show` / `list-destinations`（含 diag `-expand`）**始终为空**，看不到该关系。
- 但 `volume snapshot delete backup-<id>` 会被拒：`used as a reference snapshot by one or more SnapMirror relationships` —— 证明底层确有 SnapMirror-to-Cloud 关系。

## 3. 删 Backup 后转换即可放行，但底层释放是【异步】的（关键坑）
- `aws fsx delete-backup` 返回 `Lifecycle: DELETED` 只是 AWS 侧登记删除（~10s 后 describe-backups 报 BackupNotFound）。
- **删除后立刻（t0，~30s）复查：backup 参考快照仍在、转换仍 Error、snap delete 仍被拒** —— 后台还没释放 copy-to-cloud 关系。
- **约 30s～1min 后**：backup 参考快照消失、转换 check-only 从 Error 变成仅 Warning、`volume conversion start` Job succeeded。
- 教训：**删 backup 后别立即断言"没用/还阻塞"，要等后台异步释放（本次 ≤1min）再复查**。若一删完就测会误判为"删备份不足以解除阻塞"。

## 4. 结论：Backup 造成的阻塞是可解除的软阻塞
- 删除该卷的所有 FSx 备份 → 等后台释放 copy-to-cloud（本次 ≤1min）→ 转换只报 Warning、Job succeeded、卷变 flexgroup。
