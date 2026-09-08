# HANDOFF: FSxN 单HA→2HA + FlexVol→FlexGroup（只转不平衡）测试

**日期**: 2026-09-08　**区域**: us-east-2　**账号**: 386094880462
**发起人**: 伟伟　**执行**: 后台子 agent（继承 workspace）

## 测试目标（伟伟原话）
做一个「单 FSx ONTAP HA pair 转 2 个 HA pair，并且将原来 FlexVol 转 FlexGroup」的测试：
1. 创建单 AZ、单 HA pair，但**单个吞吐比较高**（是可以直接扩 2HA 的起点，避免死锁）
2. 放 **500GB** 数据
3. 开始转 **2 HA pair** → **记录耗时** ⏱️
4. 转完后，把原来单 HA pair 的 FlexVol **转 FlexGroup**，**只转、不做数据重新平衡（no rebalance / 不 expand）** → **记录耗时** ⏱️，看是不是很快

## 关键前置知识（已查官方文档 + 历史实测，2026-09-08）
- **Gen2 Single-AZ 支持加 HA pair（1→12）**，加 HA **不中断、官方说通常几分钟**（8-28 实测约 26min，以本次实测为准）。
- **加 HA 时不能改吞吐/SSD/IOPS**；新 HA 沿用现有吞吐容量。这是"死锁"根因：单 HA 起点吞吐若太低（如 384），扩 2HA 会冲突。
- **解法（本次采用）**：**创建时就把单 HA 吞吐设为 1536 MBps**（Gen2 Single-AZ 档位 384/768/1536/3072/6144），直接满足可扩 2HA 起点，跳过"先升吞吐"步骤（省 ~44min）。
- FSxN Gen2 = `DeploymentType=SINGLE_AZ_2`，ONTAP 9.18.x。
- **FlexVol→FlexGroup 就地转换** = ONTAP diag 级命令 `volume conversion start -vserver <svm> -volume <vol>`。转换产生**单 constituent FlexGroup**，**不自动 rebalance**——这正是伟伟要的"只转不平衡"，本身就不会搬数据，预期极快（历史实测 <1min，Job succeeded）。
- **转换前置条件**（历史已固化，见 TOOLS.md / workspace/flexvol_conversion_prereqs.md）：卷 online；无 SAN LUN；**先禁用 storage efficiency**（FSx 上实测只警告不拦，但先禁更稳）；不能是 DataSync source（有隐藏 SnapMirror-to-Cloud 会阻塞——**本卷全程不碰 DataSync/Backup**）；无 active SnapMirror；ARP 禁；quota 禁；快照数 OK。
- **不要 expand、不要 volume rebalance、不要写成百上千文件**——伟伟明确"只转不平衡"。500GB 用少量大文件写即可（写入速度快）。

## 访问方式（标准）
- 跳板机 **i-0dffb881b2a90daa2**（SSM Online），已装 sshpass/expect。
- 登录：`aws ssm start-session --target i-0dffb881b2a90daa2 --region us-east-2`
- 或直接 SSM send-command 跑命令（AWS-RunShellScript）。
- ONTAP fsxadmin 密码：`<REDACTED_FSXADMIN_PASSWORD>`（沿用；创建时用此密码）
- 连 ONTAP：`sshpass -p '<REDACTED_FSXADMIN_PASSWORD>' ssh fsxadmin@<FS-Management-IP> "<cmd>"`
- ⚠️ fsxadmin 用**文件系统 Management endpoint IP**（`describe-file-systems ... OntapConfiguration.Endpoints.Management.IpAddresses`），不是 SVM IP。
- diag 命令需先 `set -privilege diagnostic`（用 expect 或 ssh 带 `set -priv diag; volume conversion start ...`）。
- 挂载写数据：在跳板机或另起 EC2（同 AZ/子网），`mount -t nfs -o nfsvers=3 <SVM-NFS-IP>:/<junction> /mnt/xxx`。
- 跳板机与目标 FSxN 要同 VPC/子网可达；SG 放行 NFS(2049/111)+ONTAP mgmt(22)。若跳板机网络不通，按 TOOLS.md 用 SSM send-command 在能通的 EC2 上操作，或新建 EC2。

## 执行步骤
1. **建 FSxN**：`aws fsx create-file-system --file-system-type ONTAP --storage-capacity 1024 --subnet-ids <subnet> --security-group-ids <sg> --ontap-configuration DeploymentType=SINGLE_AZ_2,ThroughputCapacity=1536,HAPairs=1,FsxAdminPassword=<REDACTED_FSXADMIN_PASSWORD>,PreferredSubnetId=<subnet> --region us-east-2`
   - storage 1024GB 起（500GB 数据够放）。选一个有 Gen2 SINGLE_AZ_2 支持的 AZ（us-east-2a/b/c，创建失败换 AZ 重试）。
   - SG 需放行来源(跳板机/EC2)到 2049/111(NFS) + 22(mgmt)。
2. 建 **SVM** + **FlexVol**（`aws fsx create-storage-virtual-machine`；卷用 ONTAP CLI `volume create` 或 `aws fsx create-volume`，指定 junction path，SecurityStyle UNIX，**先不开 dedup/efficiency** 或建后禁用）。卷大小≥600GB 容纳 500GB。
3. **写 500GB 数据**：挂 NFS，`dd`/`fallocate` 写若干大文件（如 10×50GB 或 5×100GB，少量大文件即可，别写海量小文件）。记录写入耗时（非考核项）。
4. **⏱️ 扩 2 HA pair**：`aws fsx update-file-system --file-system-id <fsid> --ontap-configuration HAPairs=2 --region us-east-2`。**记录开始→LifeCycle 回到 AVAILABLE 的耗时**。用 `describe-file-systems` 轮询 Lifecycle（UPDATING→AVAILABLE）+ 看 AdministrativeActions 状态/进度。确认扩到 2 HA（aggr1+aggr2）、storage 翻倍。
5. **⏱️ FlexVol→FlexGroup 只转不平衡**：
   - 先禁 storage efficiency：`volume efficiency off -vserver <svm> -volume <vol>`（忽略警告）
   - 确认无 SnapMirror/quota/ARP。
   - diag：`set -privilege diagnostic; volume conversion start -vserver <svm> -volume <vol> -foreground true`（或默认后台，轮询 `volume show -fields volume-style-extended`）。**记录开始→转换完成(Job succeeded / style 变 flexgroup)的耗时**。
   - **不 expand、不 rebalance**。转完 `volume show -volume <vol> -fields volume-style-extended,aggr-list` 确认变 flexgroup（单 constituent，仍在原 aggr）。
6. **记录两个关键耗时** + 转换前后卷状态截图/文本。

## 交付
- 结果写 workspace 文件：`fsxn-1ha-to-2ha-flexgroup/REPORT.md`（含两个耗时、命令输出、卷状态）。
- 推 GitHub `AllenXieSZ/storage` 路径 `fsxn-1ha-to-2ha-flexgroup/`（SSH deploy key 已配，仓库 storage）。
- 关键数据脱敏（密码不入库）。
- **资源保留**（伟伟习惯：实验后保留备复现），除非另有指示。记录所有资源 ID 到 REPORT.md 便于后续清理。
- 完成后 push 通知伟伟：两个耗时 + 结论（FlexVol→FlexGroup 只转是否很快）。

## 记录本次实测新数据（对比 8-28）
- 单 HA 直接以 1536 起点建（省升吞吐 44min）→ 扩 2HA 实际耗时 = ?（文档说"几分钟"，8-28 实测 26min）
- FlexVol→FlexGroup 只转不平衡实际耗时 = ?（预期 <1min）
