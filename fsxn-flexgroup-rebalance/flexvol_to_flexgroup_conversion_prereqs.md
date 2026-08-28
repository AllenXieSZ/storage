# FlexVol→FlexGroup 转换前置条件（NetApp 官方文档）
来源: https://docs.netapp.com/us-en/ontap/flexgroup/convert-flexvol-volume-task.html
ONTAP 9.7+ 支持就地转换（无需复制数据、无需额外空间）。

## 会阻止转换的条件（逐项检查）
1. 卷必须 online。
2. 7-Mode 转换来的卷（9.7 不行，9.8+ 可）。
3. 卷上启用了 FlexGroup 尚不支持的功能：SAN LUN、Windows NFS、SMB1、snapshot 命名/autodelete、vmalign、SnapLock(<9.11.1)、space SLO、logical space enforcement/reporting。
4. <9.10.1 且 SVM 在用 SVM-DR。
5. 存在 FlexClone 卷且本卷是 parent；本卷不能是 parent 或 clone。
6. 本卷是 FlexCache origin 卷。
7. 快照数：9.7- ≤255；9.8+ ≤1023。
8. **启用了存储效率（storage efficiency）→ 必须先禁用，转换后可重启。**
9. **本卷是 SnapMirror 关系的 source，且 destination 尚未转换。**  ← 关键嫌疑
10. **本卷处于 active（未 quiesce）的 SnapMirror 关系中。**  ← 关键嫌疑
11. 启用了 Autonomous Ransomware Protection（ARP）→ 需禁用，转换完再启。
12. **启用了 quota → 必须先禁用，转换后可重启。**
13. 卷名 >197 字符。
14. 卷关联了 application（仅 9.7）。
15. 有 ONTAP 进程在跑：mirroring、jobs、wafliron、NDMP backup、inode conversion。
16. 卷是 SVM root 卷。
17. 卷太满（≥80% max capacity 时官方建议改用复制而非就地转）。

## 步骤
- `set -privilege advanced`（FSx 上可能需 diagnostic）
- `volume conversion start -vserver X -volume Y -check-only true`  ← 先 check
- `volume conversion start -vserver X -volume Y`  ← 正式转
- 转换后是**单 constituent FlexGroup**，可再 `volume expand` 加 constituent。
- ⚠️ 不可逆：FlexGroup 不能转回 FlexVol；快照会被置为 pre-conversion。
