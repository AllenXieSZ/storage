# fsxn-throughput-latency

实测 **FSx for NetApp ONTAP（Gen2 / SINGLE_AZ_2）在线升吞吐操作对单请求 IO 延迟的冲击**，并做**两次实测对比（RUN1 vs RUN2）**验证可复现性。

- 升吞吐路径：**1536 → 3072 MBps**（`ThroughputCapacityPerHAPair`）
- fio：`bs=16k ioengine=sync direct=1 numjobs=1 iodepth=1`，read/write 各一轮，`runtime=8 -time_based`
- 从升吞吐触发起每 ~10s（实际 ~17s/样本对）采一个 clat 均值+p99，直到 AdministrativeAction COMPLETED

## 两次对比核心结论（实测为准）
> **升吞吐延迟冲击部分可复现：读延迟的双段瞬时抖动（+250s / +780s 附近）两次高度一致；写延迟"大尖峰"不可复现——RUN1 出现 12.3ms 写均值尖峰，RUN2 完全没有（最大仅 ~1.0ms）。写 p99 十几毫秒震荡带 + 升级完成后延迟改善，两次都一致。**

| 指标 | RUN1 | RUN2 | 复现 |
|---|---|---|---|
| 升级耗时 | ~20.5 min | ~25.8 min | 同量级 |
| write 峰值 mean | **12.3 ms** @+167s | **1.0 ms** @+604s | ❌ |
| read 峰值 mean | 904 µs @+784s | 808 µs @+805s | ✅ |
| read 峰值 p99 | 1.4 ms @+768s | 1.27 ms @+788s | ✅ |
| 升级后写 p99 | ~18ms → sub-ms | ~15ms → sub-ms | ✅ |

详见 [REPORT_COMPARISON.md](./REPORT_COMPARISON.md)，对比图见 `comparison.png`。

## 目录结构
| 路径 | 说明 |
|---|---|
| REPORT_COMPARISON.md | **两次对比主报告**（逐项对比 + 回答"是否可复现/峰值是否一致"） |
| comparison.png | RUN1 vs RUN2 四宫格叠加图（read/write × mean/p99） |
| run1/ | RUN1 产物：REPORT_RUN1.md + latency_curve_run1.png + results_run1.csv |
| run2/ | RUN2 产物：REPORT_RUN2.md + latency_curve_run2.png + results_run2.csv + 原始 raw csv |
| latency_loop.sh | 跳板机 10s 循环采样脚本 |
| plot.py / plot_run2.py / plot_comparison.py | 画图脚本（RUN1 / RUN2 / 对比） |
| HANDOFF.md / HANDOFF_RUN2.md | 任务说明 |

> 规格提示：官方 `create-file-system` 文档确认 **SINGLE_AZ_2 合法吞吐档仅 1536/3072/6144 MBps**（384/768 属 MULTI_AZ_2）。两次 RUN 规格完全一致（除 FS 实例 ID），可比。
