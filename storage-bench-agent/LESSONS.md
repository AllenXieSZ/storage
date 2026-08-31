# storage-bench 踩坑汇总 (LESSONS.md)

> 每次实验踩的坑统一累积在这里（追加不覆盖）。固定 URL:
> https://github.com/AllenXieSZ/storage/blob/main/storage-bench-agent/LESSONS.md
> 格式：日期 · 现象 · 根因 · 规避

---

## 2026-08-29 首跑 EBS 端到端

- **DynamoDB Decimal 坑**
  - 现象：create_volume 报 `Invalid type for parameter Size, type: Decimal, valid: int`
  - 根因：DynamoDB 读回的数字是 `decimal.Decimal`，boto3 EC2 API 只接受 `int`
  - 规避：provision 里对 Size/Throughput/Iops 等 `int(...)` 强转

- **默认 instance profile 不存在**
  - 现象：run_instances 报 `Invalid IAM Instance Profile name (PVRE-SSMOnboardingInstanceProfile)`
  - 根因：该 profile 名在本账号不存在（是别的环境的默认）
  - 规避：建 `storage-bench-ec2-profile`（附 AmazonSSMManagedInstanceCore），配到 config.INSTANCE_PROFILE

- **gp3 新卷性能偏低**
  - 现象：randread 4k 仅 6940 IOPS/27MB/s（卷配 16000 IOPS）
  - 根因：新卷首次访问初始化惩罚 + 未预热 + size=10G 随机读未充分打满
  - 规避：测基线前先预热（顺序写满一遍或 fio --rw=write 预热），再测随机；数据先准备好

## 2026-08-30 DataSync 是否阻塞 FlexGroup 转换（根因复核）

- **DataSync(NFS模式)不留 SnapMirror/快照痕迹，不阻塞 FlexGroup 转换**
  - 现象：干净受控实验——源卷灌10G→DataSync(NFS3)传输→扩2HA→转FlexGroup，全程成功([Job]succeeded)
  - 根因/坐实：DataSync 传输【前】vs【后】源卷 `snapmirror show`/`list-destinations`/`snapshot show`(diag级)**逐条对照完全一致(全空)**，snapshot-count 始终0。AWS官方文档明确 DataSync 对 FSx ONTAP 走 NFS/SMB 文件协议，非 SnapMirror。
  - 修正：之前(2026-08-28)把"copy to cloud 阻塞"归因给"DataSync用SnapMirror-to-Cloud"是**误判**。NFS 模式 DataSync 无此副作用。真凶更可能是旧FS开过 **FSx原生Backup(AWS Backup)** —— 它底层才用 SnapMirror-to-Cloud，会留隐藏关系+backup-xxx参考快照(客户CLI看不见/删不掉)。待后续单独验证。
  - 规避：想就地转FlexGroup的卷，**别开FSx原生自动Backup/AWS Backup**；被DataSync(NFS)当过source不影响转换。

- **SSM 驱动 ONTAP CLI 多命令坑**
  - 现象：`===== 分隔符` 让 `aws ssm send-command --parameters commands=[...]` 报 ParamValidation(遇到`=`)；且 `ssh fsxadmin@ip < cmdfile` 不带PTY时命令被吞、CLI只回提示符不执行
  - 根因：`=` 破坏 SSM 参数解析；ONTAP CLI 需 TTY 才逐行执行 stdin
  - 规避：把 ONTAP 命令写文件→base64→EC2 解码→`sshpass ssh -tt`(强制PTY) < cmdfile；命令里别用 `=====`

## 2026-08-30 FSx 原生 Backup 阻塞 FlexVol→FlexGroup 转换（H1 坐实，且是 Error 非 Warning）
- **现象**：同一 FSxN/SVM 内两个内容一致的 FlexVol，只对 bkpvol 做一次 FSx 卷级 Backup，cleanvol 不备份。cleanvol 转 FlexGroup `[Job] Job succeeded`；bkpvol `volume conversion start` 报 **`Error: ... Delete and release the copy to cloud relationship from the source FlexVol volume`**，卷仍是 flexvol，转换未发生。
- **根因**：FSx 卷级 Backup 底层建 **SnapMirror-to-Cloud（copy-to-cloud）关系** + 在卷内留 `backup-<id>` 参考快照。FlexVol→FlexGroup 要求源卷不是任何活动 SnapMirror 的 source → 被阻塞。
- **隐藏性**：`snapmirror show`/`list-destinations`（连 diag `-expand`）**全空**，看不到该关系；但 `volume snapshot delete backup-xxx` 报 **`used as a reference snapshot by one or more SnapMirror relationships`** → 关系真实存在，只是 FSx 后台托管、对客户 CLI 隐藏。
- **关键区分（回应"是否只是 warning"）**：check-only 与实际 start 输出都是 **`Error:`**（不是 `Warning:`），Job 未 succeeded。对比 cleanvol 的 check-only 是三条 `Warning:`（不可逆/pre-conversion 快照/需 volume expand）可继续。所以这次是硬 Error 阻塞，属实。
- **纠正历史误判**：2026-08-28 曾把此阻塞错记到 DataSync 头上；2026-08-30 已证 DataSync 走 NFS 不留关系不阻塞；本次坐实真凶=FSx 原生 Backup。
- **规避/解除**：要转 FlexGroup，先删除该卷的所有 FSx 备份 / 释放 copy-to-cloud 关系后再转。
- **踩坑（无关本题但记）**：process poll 的 timeout 在本环境不会真的阻塞满时长（秒级返回），长等待要用前台 `sleep` + yieldMs 或按 wall-clock 轮询判断，别依赖 poll timeout 计时。

## FSx for Lustre 容量扩容耗时实测（2026-08-31，lustre-expand-timing）
> ⚠️ 仅本次测试环境实测（n=1），不代表官方结论。

- **扩容 1.2 TiB → 2.4 TiB（PERSISTENT_2/500，已灌 ~900G 真实数据），到 Lifecycle 回 AVAILABLE ≈ 15.7 分钟（943s）。** 之后有后台 `STORAGE_OPTIMIZATION`（数据重分布），到完成 ≈ 38.9 分钟（2336s），**不阻塞使用**（AVAILABLE 后即可读写）。
- **扩容 = 加 OST，不是撑大原 OST**：1.2T=1 个 OST；扩到 2.4T→2 个 OST（OST0001 新增，容量翻倍靠它）。MDT 也从 34.4G→69.0G。
- **老数据初始全留原 OST**（AVAILABLE 瞬间 OST0000=910G/OST0001=20G），后台 optimization 把 ~360G 迁到新 OST，完成后 549G:361G（大致均衡但非精确 50:50，按已有文件/条带迁移）。
- **两个 AdministrativeAction 阶段**：①`FILE_SYSTEM_UPDATE`（UPDATING，加 OST，本次 ~15.7min，Lifecycle=UPDATING）；②转 `UPDATED_OPTIMIZING` + `STORAGE_OPTIMIZATION`（IN_PROGRESS 带 ProgressPercent，Lifecycle 已 AVAILABLE）。**测"到 AVAILABLE"看阶段①结束；测"重分布完"看 STORAGE_OPTIMIZATION 从 action 列表消失**（COMPLETED 后 describe 里该 action 会消失，只剩 FILE_SYSTEM_UPDATE=COMPLETED）。
- **STORAGE_OPTIMIZATION ProgressPercent 很"块状"**：会卡在 20%、99% 好几分钟再跳，不是线性；别据单点估总时长。
- **AL2023 (kernel 6.18.41) 默认 dnf repo 已含 lustre-client 2.15.6-32**，`dnf install -y lustre-client` 直接装好，`modprobe lustre` 即可挂载。**无需**加 aws-fsx.repo（那个 repo 对 6.18 内核反而 404/skip）。
- **灌数据**：9×100GiB dd if=/dev/urandom 并行，单路 68.9 MB/s，聚合 ~591 MB/s（贴近 PERSISTENT_2/500 写能力）；900G 约 26min。
- **SSM 驱动私网 EC2 坑**：`send-command` 的 commands 用 JSON 数组逐行传，别传带 shebang 的整段脚本 blob（会报 `cannot execute: required file not found` exit 127）。后台 dd 用 `&` 让父 shell 立即返回，SSM 命令才不会一直挂着等。
