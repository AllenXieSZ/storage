# HANDOFF RUN2：FSxN 升吞吐对 IO Latency 影响 —— 删旧资源 + 重测一次 + 两次对比推 GitHub

## 背景（先读）
- 伟伟 2026-09-06 04:30 UTC 指令：**"这个资源删除，然后再重新测一测。安排那个子agent去测试，之前配置的那个子agent，一样画图，把两次测试总结推送到 github。"**
- "这个资源" = 第一次测试起的 FSxN **`fs-0d7924d394930c95f`**（tag fsxn-tp-latency），**现已升到 3072 MBps**，无法再在它身上测"1536→3072 升级过程"，所以必须删掉重建一个 1536 的干净 FS。
- 第一次（RUN1）已完成，产物归档在 `fsxn-throughput-latency/run1/`（REPORT_RUN1.md + latency_curve_run1.png + results_run1.csv）。RUN1 结论摘要：升级总耗时 ~20.5min；写延迟峰值 12.3ms @ +167s（约基线17×）；+770s 附近次级读/写抖动；升级完成后写均值降~45%、写p99从~18ms降到sub-ms。
- 原始完整任务说明见同目录 `HANDOFF.md`（fio 参数、环境、步骤都在里面，**严格照它**）。

## 本次（RUN2）要做的事
1. **删旧资源**（严格按顺序，等每步删完再下一步）：
   ```bash
   R=us-east-2
   aws fsx delete-volume --volume-id fsvol-0f81981b69e53e9b6 --region $R
   # 轮询 describe-volumes 直到该 volume 消失
   aws fsx delete-storage-virtual-machine --storage-virtual-machine-id svm-05b23cf0627829b64 --region $R
   # 轮询直到 SVM 消失
   aws fsx delete-file-system --file-system-id fs-0d7924d394930c95f --region $R
   # 轮询 describe-file-systems 直到 FileSystemNotFound
   # SG sg-02326ca1dc0af5246 可复用给新 FS（不用删，省得重建放行规则）；若复用则跳过删 SG。
   ```
   ⚠️ delete-file-system 对 ONTAP 不接受 --ontap-configuration {SkipFinalBackup}（会报 Unknown options），直接 --file-system-id 即可。delete-volume 才用 --ontap-configuration '{"SkipFinalBackup":true}'。

2. **重建干净 FSxN（1536 档）+ SVM + vol1**，完全照 HANDOFF.md 的规格：
   - Gen2 SINGLE_AZ_2，1 HA pair，storage 1024 GiB，**ThroughputCapacityPerHAPair=1536**（最小合法档，RUN1 已确认 SINGLE_AZ_2 只有 1536/3072/6144）。
   - subnet-0c551a33e366d52d4 (us-east-2c)，**复用 SG sg-02326ca1dc0af5246**（已放行 NFS+SSH）。
   - fsxadmin 密码：`FsxOntap#2026TPtest`。
   - SVM 用 `aws fsx create-storage-virtual-machine`，vol1 512GiB junction /vol1 UNIX SE关闭。

3. **重测**：完全照 HANDOFF.md 步骤 5-7 —— baseline 5 轮 → 发起升吞吐 1536→3072 → 每 ~10s 采一轮 read fio + 一轮 write fio（bs=16k sync direct=1 numjobs=1 iodepth=1 runtime=8 time_based），记 clat mean + p99，直到 AdministrativeAction COMPLETED 再收尾 3-5 轮。数据写本地 /root/tp_results2.csv（不写 NFS）。走 SSM 驱动跳板机 i-0dffb881b2a90daa2，S3 中转取回。

4. **画图**：用 plot.py 同款风格画 RUN2 曲线 `latency_curve_run2.png`（x=elapsed_sec，read/write mean + p99，标升吞吐窗口+峰值）。

5. **两次对比总结（核心交付）**：
   - 写 `REPORT_COMPARISON.md`：并排对比 RUN1 vs RUN2 的 —— 升吞吐总耗时、baseline 读/写延迟、升级中峰值 mean/p99 及出现时刻、升级后延迟改善幅度、峰值尖刺出现的位置/次数。
   - 画一张对比图 `comparison.png`（RUN1 vs RUN2 两次 write mean 曲线叠加，或 2×2 子图 read/write mean+p99 两次对照），直观看两次升吞吐的延迟冲击是否一致/可复现。
   - 结论要回答：**升吞吐对延迟的冲击是否可复现？峰值量级两次是否一致？** 实测为准，不推理。

6. **交付**：
   - GitHub `AllenXieSZ/storage` 路径 `fsxn-throughput-latency/`：更新 README + 推 run1/ + run2/（RUN2 报告/图/csv）+ REPORT_COMPARISON.md + comparison.png + 脚本。commit message 注明 RUN2 + 两次对比。
   - PNG + CSV 上传 s3://s3lambdatest2/fsxn-tp-latency/run2/ 和 /comparison/，给 `--region us-east-2` 预签名链接（7天）。
   - 完成 push 通知**当前 webchat 窗口**：一句话结论（两次是否一致/峰值量级）+ GitHub commit + 对比图链接。

7. **清理**：RUN2 测完 **默认保留**新资源（伟伟习惯），报告注明新资源 ID + 清理命令。删前问伟伟。

## 铁律
- 技术问题查 AWS/NetApp 官方文档核实（SOUL）。
- 实测高于推理，延迟以 fio 实测为准，变量隔离（RUN2 规格与 RUN1 完全一致才可比）。
- 私网挂载/取数据走 SSM + S3 中转。
- 严禁手写伪 tool call。
- 起真实资源前若需报预算：本次约 $3-6 量级（1 个 1536 档 FSxN 跑 ~1h + 一次升吞吐），伟伟本条指令已明确"重新测"= 已预批，直接执行不必停等。
