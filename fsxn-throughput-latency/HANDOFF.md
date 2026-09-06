# HANDOFF：FSxN 升吞吐过程对 IO Latency 影响实测（Ohio us-east-2）

## 目标（伟伟 2026-09-06 定）
在 Ohio 建一个**最小的 Gen2 FSx ONTAP** → 挂载后先跑 baseline → **发起"升吞吐"变更** → 从发出变更起，**每 10 秒跑一轮测延迟的 fio**，直到升吞吐完成 → 统计每 10 秒的 latency → **画 PNG 曲线图**，看升吞吐过程中 latency 最高到多少。本实验 = 测"升吞吐操作本身对 IO 延迟的冲击"。

## fio 参数（严格按伟伟要求，不许改）
- `bs=16k`
- `ioengine=sync`
- `direct=1`
- `numjobs=1`
- `iodepth=1`
- 读和写都要测（rw：分别跑一轮 randread 和 randwrite，或用 rw=readwrite；建议**分开跑 read 一轮 + write 一轮**，各自记录 latency，曲线分两条）
- 每轮 fio **runtime 要短**（如 `runtime=8 -time_based`），确保一轮在 10 秒窗口内跑完，然后 sleep 到下一个 10 秒点。目标是"每 10 秒采一个延迟样本"。
- 关注指标：**clat/lat 的均值 + p99**（sync/direct/iodepth=1 下 latency 才是真实单请求延迟）。

## AWS 环境
- Region: **us-east-2**，账号 386094880462（user admin）
- 跳板/挂载机 = **MySQL-Master EC2 `i-0dffb881b2a90daa2`**（SSM Online，Amazon Linux）
  - AZ **us-east-2c**，subnet **subnet-0c551a33e366d52d4**，vpc **vpc-0c28d2a9082ef222e**
  - 已装 sshpass/expect；通过 `aws ssm start-session` 或 `aws ssm send-command` 驱动
- **FSxN 建在同 AZ 同子网**（us-east-2c / subnet-0c551a33e366d52d4），让跳板机能挂 NFS
- 工作区脚本参考：`ontap_run.sh <mgmt-ip> "<cmd>"`（走 SSM→EC2→sshpass 连 ONTAP CLI）
- fsxadmin 密码本次自定：**FsxOntap#2026TPtest**（创建时 --fsx-admin-password 设定）

## 关键规格（Gen2 最小 + 升吞吐）
- **Gen2 = SINGLE_AZ_2**（DeploymentType=SINGLE_AZ_2）。⚠️Gen2 单文件系统最小吞吐档需确认：Gen2 SINGLE_AZ_2 的 ThroughputCapacityPerHAPair 合法档位（如 384/768/1536/3072/6144）。**最小档创建**（先查 `aws fsx create-file-system help` 或直接试最小 384）。
- 存储最小：**1024 GiB**（FSxN 最小 SSD 容量 1024GiB）。
- **升吞吐动作** = `aws fsx update-file-system --file-system-id fs-xxx --ontap-configuration ThroughputCapacityPerHAPair=<更高档>`（如 384→768 或 384→1536）。⚠️Gen2 用 ThroughputCapacityPerHAPair 不是 ThroughputCapacity。
- ⚠️注意 FSxN 死锁坑（TOOLS.md 记过）：扩 HA 才有"必须先升吞吐到1536"的约束；**本次只升吞吐、不扩 HA**，不涉及该死锁。单纯 update ThroughputCapacityPerHAPair 应可直接做。

## 执行步骤（子 agent 按此跑）
1. **建 SG**：新建专用 SG（vpc-0c28d2a9082ef222e），入站放行来自跳板机 SG `sg-0d67509101b407583` 的 NFS（2049,111,635,4045-4046 tcp/udp）+ SSH(22) + ONTAP mgmt(如需)。
2. **建 FSxN**：`aws fsx create-file-system --file-system-type ONTAP --storage-capacity 1024 --subnet-ids subnet-0c551a33e366d52d4 --security-group-ids <新SG> --ontap-configuration DeploymentType=SINGLE_AZ_2,ThroughputCapacityPerHAPair=384,FsxAdminPassword=FsxOntap#2026TPtest,PreferredSubnetId=subnet-0c551a33e366d52d4`（参数名以 create-file-system help 为准；SINGLE_AZ 可能不用 PreferredSubnetId）。等 AVAILABLE（~15-25min，轮询 describe-file-systems）。
3. **建 SVM + volume**：`aws fsx create-storage-virtual-machine`（SVM）→ 建一个 FlexVol（`aws fsx create-volume` 或 ONTAP CLI），junction path 如 /vol1。拿 NFS mount IP（describe-storage-virtual-machines 的 Endpoints.Nfs.IpAddresses）。
4. **跳板机挂载**（走 SSM send-command，base64 传脚本避免转义）：
   - `mkdir -p /mnt/fsxtp`
   - 配 /etc/hosts 或直接用 IP：`mount -t nfs -o nfsvers=3 <nfs-ip>:/vol1 /mnt/fsxtp`
   - 装 fio：`yum install -y fio`（AL2023 用 dnf）
5. **baseline**：升吞吐前先跑 3~5 轮 fio（read+write）记基线延迟。
6. **发起升吞吐 + 边升边测（核心）**：
   - 记录 T0 = 发出 update-file-system 的时刻。
   - 立即启动循环：**每 10 秒**跑一轮 read fio（runtime≈8s）+ 记 clat 均值/p99，再一轮 write fio + 记，时间戳相对 T0。
   - 循环判停：轮询 `describe-file-systems ... AdministrativeActions`，当升吞吐的 action 状态变 COMPLETED（或 ThroughputCapacityPerHAPair 变为目标值且无 IN_PROGRESS action）→ 再多测 3~5 轮收尾 → 停。
   - 每轮把 `{elapsed_sec, op(read/write), lat_mean_us, lat_p99_us}` 追加写到 `/mnt/fsxtp/../results.csv`（放本地非 NFS 路径，如 /root/tp_results.csv，避免 NFS 写自己干扰测量）。
7. **取回数据 + 画图**：
   - 把 results.csv 从跳板机取回（走 S3 中转：跳板机 `aws s3 cp /root/tp_results.csv s3://s3lambdatest2/fsxn-tp-latency/` → 本地下载）。
   - 用 python matplotlib 画 PNG：x=elapsed_sec，y=latency(us)，两条线（read/write，画均值线，p99 可选虚线）；标出升吞吐区间（T0 到 COMPLETED）；标注峰值延迟点。
   - 输出 `latency_curve.png`。
8. **交付**：
   - 报告写 `REPORT.md`（环境/规格/升吞吐耗时/baseline延迟/升级中峰值延迟/结论）。
   - 脱敏后推 GitHub `AllenXieSZ/storage` 路径 `fsxn-throughput-latency/`（README+脚本+results.csv+latency_curve.png）。
   - PNG + CSV 上传 s3://s3lambdatest2/fsxn-tp-latency/，给 `--region us-east-2` 预签名链接（7天）。
9. **清理**：测完删 volume→SVM→FSxN→新建SG。**除非伟伟说保留**（伟伟习惯保留资源，完成时问一句或默认保留并在报告注明资源ID+清理命令）。

## 注意
- 技术问题查 AWS 官方文档核实（SOUL 铁律）；create-file-system 的确切参数名以 `aws fsx create-file-system help` 为准，别硬套。
- 实测高于推理：延迟数据以 fio 实测为准。
- 私网挂载/取数据走 SSM + S3 中转（TOOLS.md 记过的模式）。
- 完成后 push 通知主会话。
