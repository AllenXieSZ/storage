# RUN3：FSxN 升吞吐对 IO Latency 影响 —— 第三次实测报告

**日期**: 2026-09-06 | **区域**: AWS us-east-2 (Ohio) | **账号**: 386094880462

## 规格（与 RUN1/RUN2 完全一致）
- FSxN Gen2 SINGLE_AZ_2，1 HA pair，存储 1024 GiB SSD，起始吞吐 **1536 MBps**
- FileSystemId: `fs-01230588a0f9ecfd5`（本次新建，测完已删）
- SVM `svm-01aaa77e47f61b240`（NFS IP 172.31.42.21），Volume `fsvol-0eaffa632fa4a7ef0`（vol1, 512 GiB, /vol1, UNIX, SE 关闭）
- 子网/AZ: subnet-0c551a33e366d52d4 / us-east-2c，SG sg-02326ca1dc0af5246（复用）
- 挂载/压测机: i-0dffb881b2a90daa2（SSM），nfsvers=3，rsize/wsize=64K，mountproto=tcp
- fio: bs=16k sync direct=1 numjobs=1 iodepth=1 runtime=8 time_based（每轮 read + write）

## 关键结果
- **升吞吐耗时**: 触发 06:30:37 → COMPLETED 06:52:53 = **~22.3 min**（介于 RUN1 20.5m 与 RUN2 25.8m 之间）。
- **基线**: read mean ~194µs / p99 ~321µs；write mean ~657µs / p99 ~16ms（与 RUN1/RUN2 一致）。
- **写侧大尖峰**: **未出现**。升级全程写均值最大仅 **~1.13ms @ +837s**，与 RUN2（1.0ms）同量级，与 RUN1（12.3ms）差 10× 以上。→ **RUN1 的 12.3ms 写尖峰第三次仍未复现。**
- **读侧双段抖动**: **复现**。第一段 +250~470s（p99 抬到 ~700µs-1.3ms），第二段 +837~1038s（p99 ~1.2ms、mean ~780µs），与 RUN1/RUN2 位置/量级高度一致。
- **⚠️ 新现象（诚实标注）**: RUN3 在 **+191s 出现一个 read 均值 14.8ms 的孤立采样**，但**同一轮 p99 仅 394µs**。mean ≫ p99 说明这是**单个/极少数 IO 在重配置瞬间卡了几秒**把均值拉高的 fio 统计假象——99% 的请求仍然亚毫秒。这是升级过程中一次瞬时读停顿的真实证据，但不代表整体读延迟真的到 15ms。它出现在读侧、发生在升级早期，与 RUN1 的写侧 12ms 尖峰性质不同。
- **升级完成后改善**: write mean 从 ~657µs 降到 ~387µs，write p99 从 ~16ms 骤降到 ~480µs（sub-ms）。与 RUN1/RUN2 一致，是最稳定可复现的收益。

## 图
- `run3/latency_curve_run3.png`：RUN3 单次 mean/p99 曲线
- 三方对比见 `comparison3.png` 与 `REPORT_COMPARISON.md`

## 方法学备注
- 采样循环 T0 比实际触发早 **10s**（先起 loop 再发 update）；分析时已把 upgrade 阶段 elapsed 统一减 10s 使 T0=触发时刻，与 RUN1/RUN2 对齐。原始未校正数据见 `run3/tp_results3_raw.csv`，校正后 `run3/results_run3.csv`。
- 每轮 read(8s)+write(8s)+开销 ≈ 每 ~17s 一个样本对。

## 资源清理
本次所有新建资源（Volume→SVM→FileSystem）测完已按顺序删除，SG sg-02326ca1dc0af5246 亦已删除。**资源已全部清理，无残留计费。** 跳板机 i-0dffb881b2a90daa2 为共用资源不删，其上 RUN3 的 NFS 挂载已卸载。
