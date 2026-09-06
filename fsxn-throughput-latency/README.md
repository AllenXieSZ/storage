# fsxn-throughput-latency

实测 **FSx for NetApp ONTAP（Gen2 / SINGLE_AZ_2）在线升吞吐操作对单请求 IO 延迟的冲击**，并做**三次实测对比（RUN1 vs RUN2 vs RUN3）**验证可复现性、判定写大尖峰是偶发还是必现。

- 升吞吐路径：**1536 → 3072 MBps**（`ThroughputCapacityPerHAPair`）
- fio：`bs=16k ioengine=sync direct=1 numjobs=1 iodepth=1`，read/write 各一轮，`runtime=8 -time_based`
- 从升吞吐触发起每 ~10s（实际 ~17s/样本对）采一个 clat 均值+p99，直到 AdministrativeAction COMPLETED

## 三次对比核心结论（实测为准）
> **写延迟 12.3ms 大尖峰 = 偶发（3 次仅 RUN1 出现 1 次）；读侧双段瞬时抖动 = 必现（3 次全一致）；升级完成后写延迟改善 = 必现（3 次全一致）。**

| 指标 | RUN1 | RUN2 | RUN3 | 判定 |
|---|---|---|---|---|
| 升级耗时 | ~20.5 min | ~25.8 min | ~22.3 min | 同量级 |
| **write 峰值 mean** | **12.3 ms** @+167s | 1.0 ms @+604s | **1.13 ms** @+837s | ❌ **偶发**（1/3）|
| read 峰值 mean | 904 µs @+784s | 808 µs @+805s | 781 µs @+854s | ✅ 一致 |
| read 峰值 p99 | 1.4 ms @+768s | 1.27 ms @+788s | 1.24 ms @+854s | ✅ 一致 |
| 读双段抖动窗口 | +250s / +780s | +250s / +790s | +250s / +840s | ✅ **必现**(3/3) |
| 升级后写 p99 | ~18ms → sub-ms | ~15ms → sub-ms | ~16ms → sub-ms | ✅ **必现**(3/3) |

> RUN3 特有：+191s 出现一个 read 均值 14.8ms 的孤立采样，但同轮 p99 仅 394µs → 单个 IO 在重配置瞬间卡了几秒的 fio 统计假象（99% 请求仍亚毫秒），已诚实标注。

详见 [REPORT_COMPARISON.md](./REPORT_COMPARISON.md)，三方对比图见 `comparison3.png`。

## 目录结构
| 路径 | 说明 |
|---|---|
| REPORT_COMPARISON.md | **三次对比主报告**（逐项对比 + 偶发/必现判定） |
| comparison3.png | RUN1 vs RUN2 vs RUN3 四宫格三线叠加图（read/write × mean/p99） |
| comparison.png | 旧 RUN1 vs RUN2 两方对比图（保留） |
| run1/ | RUN1 产物：REPORT + latency_curve_run1.png + results_run1.csv |
| run2/ | RUN2 产物：REPORT + latency_curve_run2.png + results_run2.csv + raw |
| run3/ | RUN3 产物：REPORT_RUN3.md + latency_curve_run3.png + results_run3.csv + raw |
| latency_loop.sh / loop3 | 跳板机 10s 循环采样脚本 |
| plot*.py / plot_comparison3.py | 画图脚本 |
| HANDOFF*.md | 任务说明 |

> 规格提示：官方 `create-file-system` 文档确认 **SINGLE_AZ_2 合法吞吐档仅 1536/3072/6144 MBps**。三次 RUN 规格完全一致（除 FS 实例 ID），可比。
>
> **✅ 资源已全部清理，无残留计费**（RUN3 为本系列最后一次，volume→SVM→FSxN→SG 全删；共用跳板机 i-0dffb881b2a90daa2 保留、仅卸载 RUN3 挂载）。
