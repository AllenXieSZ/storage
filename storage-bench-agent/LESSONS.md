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
