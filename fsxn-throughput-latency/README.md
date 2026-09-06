# fsxn-throughput-latency

实测 **FSx for NetApp ONTAP（Gen2 / SINGLE_AZ_2）在线升吞吐操作对单请求 IO 延迟的冲击**。

- 升吞吐路径：**1536 → 3072 MBps**（`ThroughputCapacityPerHAPair`）
- fio：`bs=16k ioengine=sync direct=1 numjobs=1 iodepth=1`，read/write 各一轮，`runtime=8 -time_based`
- 从升吞吐触发起每 ~10s（实际 ~17s/样本对）采一个 clat 均值+p99，直到 AdministrativeAction COMPLETED

## 关键结论
- 升吞吐总耗时 ≈ **20.5 min**，IO 全程在线。
- **最大冲击 = 写延迟峰值 12.3 ms @ +167s**（约基线 17×），次级读/写抖动在 +770s 附近。
- 升级完成后写延迟均值降 ~45%、写 p99 从 ~18ms 降到 sub-ms，读延迟更低更稳。

详见 [REPORT.md](./REPORT.md)，曲线见 `latency_curve.png`。

## 文件
| 文件 | 说明 |
|---|---|
| REPORT.md | 完整报告（环境/时间线/峰值/结论/资源+清理命令） |
| latency_curve.png | 延迟曲线（mean + p99，标出升级窗口与峰值） |
| results.csv | 原始采样数据 |
| latency_loop.sh | 跳板机上的 10s 循环采样脚本 |
| plot.py | 画图脚本 |

> 规格提示：官方 `create-file-system` 文档确认 **SINGLE_AZ_2 合法吞吐档仅 1536/3072/6144 MBps**（384/768 属 MULTI_AZ_2）。
