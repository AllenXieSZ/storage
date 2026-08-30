# HANDOFF: 开启 FSx 原生 Backup 的卷能否就地转 FlexGroup（H1 真凶验证）

> 任务交给 storage-bench 子 agent。全程实测，按 ROLE.md 铁律执行。
> 排期：2026-09-01（后天）由 cron 触发本 HANDOFF。
> **注明"仅本次测试环境实测,不代表官方结论"。**

## 背景（先读，别重蹈覆辙）
- 2026-08-28 曾把「FlexVol→FlexGroup 转换被 `copy to cloud relationship` 阻塞」的根因**错误归给 DataSync**。
- 2026-08-30 纠错实验（`datasync-snapmirror-rootcause`, commit 11768de）已**证伪**该归因：DataSync 走 **NFS 协议**传输后源卷 snapmirror/snapshot 前后逐条对照**完全一致(全空)**，不留 SnapMirror/backup 快照，也**不阻塞**转换（转换 Job succeeded）。
- 缩小范围后的**候选真凶(H1，本次要验证)**：旧 fs-0ab60 被阻塞，最可能是那个 FS **开过 FSx 原生 Backup（AWS Backup / FSx 每日自动备份）**——FSx ONTAP 原生备份底层用 **SnapMirror-to-Cloud**，会在卷上留客户 CLI 看不见的隐藏关系 + `backup-xxx` 参考快照。当年看到的 `backup-xxx` 很可能来自原生 Backup，被误记到 DataSync 头上。

## 核心假设（本次要裁定）
- **H1（主）**：卷被 **FSx 原生 Backup 备份过**后，会在源卷留下 SnapMirror-to-Cloud 隐藏关系 + `backup-xxx` 参考快照，并**阻塞** FlexVol→FlexGroup 就地转换（报 `copy to cloud relationship`）。
- **H0（对照，已知）**：干净卷（从没备份、没 DataSync）能成功转 FlexGroup（2026-08-28/29/30 已多次坐实，本次沿用作对照）。

### ⚠️ 伟伟的质疑（2026-08-30，本实验真正裁判点）
伟伟认为**很可能根本不是 Backup 的原因**——那句 `copy to cloud relationship` 很可能只是 **Warning 而非 Error**，转换其实照样 succeeded。查 AWS FSx ONTAP 官方 backup user guide（using-backups.html）确认：FSx 原生备份会"take a snapshot of your volume，backup snapshot 存在卷里并保留到下次备份"——所以**备份过的卷确实会留一个 backup 参考快照，但"留快照" ≠ "阻塞转换"**。
**→ 本实验真正要回答的是：备份产生 backup 参考快照后，`volume conversion start` 到底是被 Error 阻塞，还是只是 Warning 照样 Job succeeded。** 别预设 H1 成立。

### 两点硬性要求（伟伟补充）
1. **备份要真正执行过再测**：不要 create-backup 后立刻测。把 bkpvol 备份安排在**约 1 小时后触发/完成**（FSx 自动每日备份窗口设到 ~1h 后，或 create-backup 后等它真正到 AVAILABLE 且 backup 参考快照在卷里稳定留存），确认备份确实发生、卷里确有 `backup-xxx` 快照后，再做对照 + 转换。
2. **逐字区分 Warning vs Error**：check-only 和实际 start 的输出**逐字完整记录**，明确标注哪些行是 `Warning:` 哪些是 `Error:`，以及 **Job 最终是否 succeeded**。即使出现 "copy to cloud relationship" 字样，也要看它是 Warning 还是 Error、Job 结不结束成功。对 backup 参考快照也试 `volume snapshot delete`，记录能不能删、报 warning 还是 error。
   - 若 Job succeeded（哪怕带 copy-to-cloud warning）→ 证明"备份/copy-to-cloud 只是 warning，不阻塞转换"，则 08-28 把它当 error 硬阻塞的结论**又是一个误读**（连同 DataSync 归因一起纠正）。

## 实验设计（严格对照，隔离单一变量 = 是否开过 Backup）

### 0. 起资源（Gen2 SINGLE_AZ_2, us-east-2, ONTAP 最新；沿用 rootcause 实验模板）
- **1 个 FSxN**：Gen2 SINGLE_AZ_2，1 HA pair，**throughput 直接选 1536 MB/s**（便于后面扩 2HA），storage 2048GB。
- **1 个 SVM** + **2 个 FlexVol**（**关键：同一 FS 内建两个卷做对照**）：
  - `bkpvol`（junction /bkpvol, unix, 512GB）→ **实验组：会开 Backup**
  - `cleanvol`（junction /cleanvol, unix, 512GB）→ **对照组：从不开 Backup**
- 1 台小 EC2（c6i.large, ohio key, SSM instance profile）挂卷灌数据。
- ⚠️ SVM 用 `aws fsx create-storage-virtual-machine`（ONTAP CLI vserver create 无权限）。私网不通用 **SSM RunShellScript** 驱动 EC2 → sshpass `ssh -tt` 连 ONTAP CLI（fsxadmin）。可直接复用 rootcause 目录里的 `ssmrun.sh` / `ontap_script.sh`。

### 1. 灌数据
- 两个卷各挂载后写 **10 GiB = 100 文件 × 100MiB**（dd urandom）。两卷数据量一致。

### 2. ⭐ Backup【前】基线（两卷都查，diag 级 `set -privilege diagnostic`，完整记录）
对 **bkpvol 和 cleanvol 各查**：
- `snapmirror show` / `snapmirror list-destinations` / `snapmirror show-history`
- `volume snapshot show -vserver <svm> -volume <vol>`（看有无 backup-* 快照）+ snapshot-count
- 预期：两卷此时都全空。

### 3. ⭐ 对 bkpvol 开 FSx 原生 Backup 并**实际产生一次备份**
优先用 **FSx 自身的备份**（这是"FSx 原生 Backup"最贴合语义的路径）：
- 方式A（首选，FSx 卷级备份）：`aws fsx create-backup --volume-id <bkpvol-volid> --region us-east-2`，等 `describe-backups` 到 **AVAILABLE**。记录耗时。
  - 注意：FSx ONTAP 支持**卷级备份**（volume-id）。若该 API 对本配置不可用，退方式B。
- 方式B（备选，AWS Backup 服务）：建 backup vault + plan/on-demand `start-backup-job`，resource = 该卷/文件系统 ARN，IAM 用现成 `AWSBackupDefaultServiceRole`，等 job COMPLETED。
- ⚠️ **cleanvol 全程绝不备份**。只对 bkpvol 备份。

### 4. ⭐ Backup【后】复查（两卷都查，和步骤2逐条对照）
对 **bkpvol 和 cleanvol 各查**同样命令（snapmirror show/list-destinations/show-history + snapshot show + snapshot-count），diag 级完整记录。
- **关键对照**：
  - bkpvol 备份后有没有出现 `backup-xxx` 参考快照？有没有隐藏 SnapMirror 关系（即使 `snapmirror show` 空，也留意快照能否删/报什么）？
  - cleanvol 应仍全空。
- 若 bkpvol 出现 `backup-xxx` 快照 → 试 `volume snapshot delete` 看是否报 `used as a reference snapshot by one or more SnapMirror relationships`（复现旧现象）。

### 5. 两卷各扩 …（可选）/ 直接转 FlexGroup
- 本次**转换阻塞验证不依赖 2HA**（rootcause 已证 2HA 不引入关系）。为省时间与成本，**可跳过扩 2HA**，直接在 1HA 上对两卷分别做转换 check-only + start（1HA 也能转 FlexGroup，转后单 constituent）。
- 若想顺带复测扩 HA 影响，再扩一次并记录耗时（非必须）。

### 6. ⭐ 分别转 FlexGroup（diag 级），对照结果
- 先 **cleanvol**：`volume conversion start -vserver <svm> -volume cleanvol`（先 check-only 再 start）→ 预期 **Job succeeded**（对照基线）。
- 再 **bkpvol**：`volume conversion start -vserver <svm> -volume bkpvol`（先 check-only 再 start）→ **观察是否报 `copy to cloud relationship`**。
- **裁定 H1**：
  - 若 **bkpvol 报 copy-to-cloud error 而 cleanvol 成功** → **H1 成立，坐实真凶 = FSx 原生 Backup**（旧 DataSync 归因彻底纠正）。
  - 若 **bkpvol 也成功转** → H1 不成立，需再缩小范围（记录，别硬下结论；候选转向 FabricPool/capacity tiering，或旧 FS 的其它特性）。

### 7. 结论
明确回答：**开过 FSx 原生 Backup 的卷是否阻塞 FlexVol→FlexGroup 转换**，用步骤2/4/6 的实测输出支撑，不推断。并回填对"旧 fs-0ab60 阻塞真凶"的最终判定。

## ⏱ 耗时记录要求
记录并对比：灌数据、Backup 创建到 AVAILABLE、（如做）扩 HA、转换耗时。对照下表：
| 操作 | 参考实测 |
|---|---|
| FlexVol→FlexGroup 转换 | <1 min（改元数据） |
| 扩 HA pair 1→2 | ~10–26 min（本次可跳过） |
| FSx 卷级 Backup 到 AVAILABLE | 未知，记录本次 |

## 交付
- **结论先行** + PNG（如对照表/时间线图）+ 报告存 S3 presign（`--region us-east-2`）+ 推 GitHub（`storage/`，新目录 `backup-flexgroup-rootcause/`）。
- 完成通知发**当前 webchat 窗口**：附报告链接 + 一句话结论（H1 成立/不成立）。
- 踩坑追加到 `storage/storage-bench-agent/LESSONS.md`。
- 资源**默认保留**，删除前问伟伟。
- 注明"仅本次测试环境实测,不代表官方结论"。
- ⚠️ 若 H1 成立，回来后要提醒主会话再纠正一次 memory/TOOLS.md 的最终结论（把"待验证"改成"已坐实"）。

## 复用资产
- rootcause 目录 `storage/datasync-snapmirror-rootcause/` 里的 `ssmrun.sh` / `ontap_script.sh` / `ontap.sh` 可直接复用（改 fsxadmin 密码为本次新建 FS 的密码）。
- 现有保留的 FSxN（fs-027217e10840009de 等）**不要拿来当本实验对象**——本实验需要"从建卷到开 Backup"全程可控的干净新卷，别用被动过的旧卷污染变量。建议起全新 FSxN。

## 预算（起真实资源前必须先报预算等伟伟确认 —— ROLE.md 铁律的唯一停等闸）
1 个最小 FSxN（1HA/1536/2048GB）+ 1 台 c6i.large + 1 次卷级 Backup（10G）≈ **$3–6 量级**，跑约 1–2 小时，资源保留。
**注意：storage-bench 若被 cron 唤醒执行本任务，起 AWS 资源前仍需在当前 webchat 窗口报预算等伟伟确认（除非伟伟已在 HANDOFF 触发时预批）。**
