# HANDOFF: FSx for Lustre 扩容耗时对照实验 v2（灌满到 ~1.1 TB）

## 任务目标（一句话）
重做上次的 FSx Lustre 扩容耗时实验，**唯一变量 = 灌数据量提高到 ~1.1 TB（接近 1.2 TiB 容量满，约 92%）**，其他参数与上次完全一致。测「接近容量满时，扩容到 2.4 TiB 到 AVAILABLE 的耗时会不会变长」。做完把 v2 报告推到 GitHub。

## 背景 / 上次基线（v1，务必对照）
- v1 目录：`/home/ubuntu/.openclaw/workspace/lustre-expand-timing/`（脚本/日志都在，直接复用）
- v1 参数：PERSISTENT_2 / PerUnitStorageThroughput=500 / 起始 1200 GiB → 扩到 2400 GiB / us-east-2 / us-east-2c
- **v1 灌了 ~900 GB（9×100GiB）**，结果：到 AVAILABLE ≈ **15.7 分钟**；后台 STORAGE_OPTIMIZATION 重分布完成 ≈ 38.9 分钟
- v1 GitHub：`storage/lustre-expand-timing/`（commit 380c8b6 + 643ad1b 分钟版），报告 REPORT.md
- 上次机制观察：扩容=加 OST（1 OST→2 OST），老数据初始全留 OST0000，后台重分布到新 OST（完成后约 549G:361G，非精确 50:50）

## 本次唯一改动
- **灌数据到 ~1.1 TB（约 92% of 1.2 TiB=1200 GiB）**。做法：`dd` 灌 11 个 100 GiB 文件 = 1100 GiB，或 10×100GiB + 追加，凑到 ~1.1 TB。
  - ⚠️ 灌之前用 `lfs df -h` 确认可用空间，别灌爆导致 ENOSPC。1200 GiB 实际可用约 1.06~1.1 TiB（有元数据/预留），**目标灌到 lfs df 显示 ~90-92% 就停**，别追求精确 1100，避免写满失败。稳妥：先灌 10×100GiB(1000GiB)，再看剩余空间追加到 ~92%。
- 其他全部与 v1 一致（机型、AZ、SG、throughput、扩容目标 2400）。

## 复用参数（与 v1 完全相同）
- Region: us-east-2, AZ: us-east-2c
- Subnet: subnet-0c551a33e366d52d4
- VPC: vpc-0c28d2a9082ef222e
- SG: sg-08f2883d5c47ced16（lustre-learn，复用，别新建）
- FSx: DeploymentType=PERSISTENT_2, PerUnitStorageThroughput=500, StorageCapacity=1200（起始）
- 扩容目标: StorageCapacity=2400
- EC2 灌数据机: c6in.2xlarge, AL2023（kernel 6.x 自带 lustre-client 2.15.6，`modprobe lustre` 即可，无需加 aws-fsx repo）, key=ohio
- 挂载: `mount -t lustre -o relatime,flock <dns>@tcp:/<mountname> /mnt/fsx`
- 走 SSM 驱动 EC2（复用 v1 的 ssmrun.sh）

## 执行步骤
1. `cd /home/ubuntu/.openclaw/workspace/lustre-expand-timing-v2`；复用 v1 的 ssmrun.sh（cp 过来）。
2. 创建 1.2 TiB Lustre（同 v1 参数），记录 create T0，轮询到 AVAILABLE 记创建耗时。
3. 起 c6in.2xlarge（同 AZ/SG，AssociatePublicIpAddress，key=ohio），等 SSM online。
4. 挂载 Lustre，`modprobe lustre`。
5. **灌数据到 ~1.1 TB**（≈92%），全程记录聚合吞吐 + 墙钟。灌完 `lfs df -h` 记录 OST 使用率。
6. **扩容计时核心**：记 `expand_t0`=`update-file-system --storage-capacity 2400` 提交时刻。
7. **每 30-45s 轮询** Lifecycle + AdministrativeActions(FILE_SYSTEM_UPDATE / STORAGE_OPTIMIZATION 的 Status/ProgressPercent + Cap)，写日志 expand_poll.log。
   - 记录：到 AVAILABLE（新容量 2400 可用）的秒数/分钟；STORAGE_OPTIMIZATION 从 0→100% 完成的秒数/分钟。
   - 全程轮到 STORAGE_OPTIMIZATION COMPLETED 为止（预计 40min~1h+，接近满可能更久，耐心轮，别提前退）。
8. 记录 OST 分布变化（扩容前单 OST；AVAILABLE 瞬间；重分布完成后两 OST 各多少）。

## 交付物（做完）
1. 写 `REPORT.md`（结构照抄 v1 REPORT.md，**时间线表格用分钟单位**，加免责声明 n=1）。
2. **重点做 v1 vs v2 对照表**：灌数据量(900G vs ~1100G) → 到 AVAILABLE 耗时、重分布耗时、OST 分布，得出「接近满是否变长」的结论（诚实标注 n=1、单次实测，不代表官方）。
3. 画时间线 PNG（复用 v1 的 make_chart.py 思路）。
4. 推 GitHub：新目录 `storage/lustre-expand-timing-v2/`（storage repo 在 `/home/ubuntu/.openclaw/workspace/storage`，remote git@github.com:AllenXieSZ/storage.git，push origin main）。commit message 说明是 v2 灌满对照。
5. 给 REPORT.md + PNG 的 S3 presign 链接（bucket s3lambdatest2，`--region us-east-2 --expires-in 604800`）。可选：上传到 s3://s3lambdatest2/lustre-expand-timing-v2/。

## 清理（做完必须）
- terminate 灌数据 EC2
- delete FSx Lustre（本次新建的）
- SG sg-08f2883d5c47ced16 复用的**不要删**
- ⚠️ 伟伟保留的 learn Lustre `fs-026825936499d3bdb`（4800）**不要动**
- 报告里写清清理结果

## 铁律提醒（来自 SOUL/AGENTS）
- 技术结论基于实测，n=1 明确标注，不把推测当事实。
- 实测高于推理。
- 成本控制：预计 $5-8，测完立即清理。
