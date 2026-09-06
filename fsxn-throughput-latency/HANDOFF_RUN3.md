# HANDOFF RUN3：FSxN 升吞吐对 IO Latency 影响 —— 删旧资源 + 第三次重测 + 三次对比 + 跑完清理

## 背景（先读）
- 伟伟 2026-09-06 05:56 UTC 指令："这个先删除，再跑一次，跑完清理删除文件系统"。
- "这个" = RUN2 保留的 FSxN **`fs-0a1bf6a382dc76343`**（现已升到 3072，无法再测 1536→3072 升级过程），须删掉重建 1536 干净档重测。
- 本次是第三次样本（RUN3），核心目的 = 判断 RUN1 出现、RUN2 未复现的 **写延迟 12.3ms 大尖峰是偶发还是必现**。
- RUN1/RUN2 产物已归档在 `fsxn-throughput-latency/run1/` 和 `run2/`，对比报告 `REPORT_COMPARISON.md`。
  - RUN1：写尖峰 12.3ms @ +167s；升级耗时 ~20.5min。
  - RUN2：无写大尖峰（最大 ~1.0ms）；读双段抖动 +250s/+780s ~800µs 一致；升级耗时 ~25.8min。
  - 已坐实一致的：读侧双段抖动、写 p99 十几ms 震荡带、升级完成后写延迟改善（p99 从~15-18ms 降到 sub-ms）。
- 原始完整任务说明见同目录 `HANDOFF.md`（fio 参数、环境、步骤，**严格照它**）。

## ⚠️ 与前两次的唯一不同：本次跑完要清理删除所有资源
RUN1/RUN2 是"默认保留"，**RUN3 明确要求跑完清理删除文件系统**（伟伟指令）。交付推完 GitHub/S3 后，删掉 RUN3 新建的 FS + SVM + volume。SG sg-02326ca1dc0af5246 可一并删（本系列不再复用），或按你判断保留说明。

## 本次（RUN3）要做的事
1. **删旧资源**（严格按顺序，等每步删完再下一步）：
   ```bash
   R=us-east-2
   # 先查 RUN2 的 vol/SVM id
   aws fsx delete-volume --volume-id fsvol-062bcc45eb084f209 --region $R
   # 轮询 describe-volumes 直到消失
   aws fsx delete-storage-virtual-machine --storage-virtual-machine-id svm-023b0ef9483889a55 --region $R
   # 轮询直到 SVM 消失
   aws fsx delete-file-system --file-system-id fs-0a1bf6a382dc76343 --region $R
   # 轮询 describe-file-systems 直到 FileSystemNotFound
   # SG sg-02326ca1dc0af5246 复用给新 FS（RUN3 结束再统一删）
   ```
   ⚠️ delete-file-system 对 ONTAP 不接受 --ontap-configuration {SkipFinalBackup}。delete-volume 才用 --ontap-configuration '{"SkipFinalBackup":true}'。
   ⚠️ 跳板机可能残留已删 FS 的死 NFS 挂载（RUN2 踩过）→ 挂新 FS 前先 `umount -f -l` 清理旧挂载点。

2. **重建干净 FSxN（1536 档）+ SVM + vol1**，规格与 RUN1/RUN2 **完全一致**：
   - Gen2 SINGLE_AZ_2，1 HA，storage 1024 GiB，ThroughputCapacityPerHAPair=1536。
   - subnet-0c551a33e366d52d4 (us-east-2c)，复用 SG sg-02326ca1dc0af5246。
   - fsxadmin 密码 `FsxOntap#2026TPtest`。SVM 用 create-storage-virtual-machine，vol1 512GiB /vol1 UNIX SE关闭。

3. **重测**：完全照 HANDOFF.md 步骤 —— baseline 5 轮 → 升吞吐 1536→3072 → 每 ~10s 采一轮 read fio + 一轮 write fio（bs=16k sync direct=1 numjobs=1 iodepth=1 runtime=8 time_based），记 clat mean+p99，直到 AdministrativeAction COMPLETED 再收尾 3-5 轮。数据写本地 /root/tp_results3.csv。走 SSM 驱动跳板机 i-0dffb881b2a90daa2，S3 中转取回。

4. **画图**：RUN3 曲线 `run3/latency_curve_run3.png`（同 plot 风格）。

5. **三次对比总结（核心交付）**：
   - 更新 `REPORT_COMPARISON.md` → RUN1 vs RUN2 vs **RUN3** 三方对照：升吞吐耗时、baseline 读/写延迟、升级中峰值 mean/p99 及时刻、升级后改善、写大尖峰是否出现。
   - 画三次对比图 `comparison3.png`（三次 write mean + read mean 叠加，或子图）。
   - **重点结论**：写 12.3ms 大尖峰在 3 次中出现几次？→ 判定"偶发 vs 必现"。读侧双段抖动 3 次是否都一致。实测为准，不推理。

6. **交付**：
   - GitHub `AllenXieSZ/storage` 路径 `fsxn-throughput-latency/`：加 run3/ + 更新 REPORT_COMPARISON.md + comparison3.png + README。commit 注明 RUN3 + 三次对比 + 已清理资源。
   - PNG + CSV 上传 s3://s3lambdatest2/fsxn-tp-latency/run3/ 和 /comparison/，给 `--region us-east-2` 预签名链接（7天）。

7. **⭐ 清理（本次必做）**：交付推完后，删 RUN3 的 volume→SVM→FSxN，再删 SG sg-02326ca1dc0af5246（确认无 ENI 挂载后）。报告注明"资源已全部清理，无残留计费"。跳板机 i-0dffb881b2a90daa2 是共用的**不要删**，只清它上面的 RUN3 NFS 挂载。

8. **完成 push 通知当前 webchat**：三次结论（写尖峰偶发/必现判定 + 峰值量级）+ GitHub commit + 三次对比图链接 + "资源已清理"确认。

## 铁律
- 技术问题查 AWS/NetApp 官方文档核实（SOUL）；实测高于推理；RUN3 规格必须与 RUN1/RUN2 完全一致才可比；私网走 SSM + S3 中转；严禁手写伪 tool call。
- 伟伟本条指令已预批起资源，直接执行不必停等预算。
