# FSxN 升吞吐过程对 IO Latency 影响实测报告 —— RUN2

**日期**: 2026-09-06 | **区域**: AWS us-east-2 (Ohio) | **账号**: 386094880462

## 1. 目的
第二次实测 FSxN Gen2 在线升吞吐（1536→3072 MBps）对单请求 IO 延迟的冲击，
与 RUN1 对照验证可复现性。fio 参数与环境与 RUN1 **完全一致**。

## 2. 环境与规格

| 项目 | 值 |
|---|---|
| 文件系统 | FSxN **Gen2 / SINGLE_AZ_2**，1 HA pair |
| FileSystemId | `fs-0a1bf6a382dc76343` |
| 存储容量 | 1024 GiB SSD |
| SVM | `svm-023b0ef9483889a55`，NFS IP `172.31.33.250` |
| Volume | `fsvol-062bcc45eb084f209`（vol1，512 GiB，junction `/vol1`，UNIX，SE 关闭） |
| 子网 / AZ | `subnet-0c551a33e366d52d4` / us-east-2c |
| SG | `sg-02326ca1dc0af5246`（复用 RUN1 的 SG） |
| 挂载/压测机 | `i-0dffb881b2a90daa2`（SSM 驱动） |
| 挂载参数 | `nfsvers=3`（rsize/wsize=64K） |
| fio 参数 | bs=16k sync direct=1 numjobs=1 iodepth=1 runtime=8 time_based，read+write 各一轮 |

## 3. 时间线
| 事件 | 时刻 (UTC) |
|---|---|
| baseline 采样（5 轮） | 05:19:48 – 05:20:55 |
| **发起升吞吐 1536→3072** | **05:21:42** (T0) |
| **升吞吐 COMPLETED (TP=3072)** | **05:47:28** |
| 收尾采样结束 | 05:49:04 |

**升吞吐总耗时 ≈ 25.8 分钟**（1546 s）。

## 4. 结果

### 4.1 基线
| op | mean (µs) | p99 (µs) |
|---|---|---|
| read | ~197 | ~327 |
| write | ~631 | ~15270 |

### 4.2 升级过程中峰值
| op | 峰值 mean | 时刻 | 峰值 p99 | 时刻 |
|---|---|---|---|---|
| **read** | **808 µs** | **+805 s** | 1,272 µs | +788 s |
| **write** | **1,038 µs (1.0 ms)** | **+604 s** | 20,864 µs | +67 s |

- **本次无 12ms 级写尖峰**（RUN1 有 12.3ms@+167s，RUN2 写均值最大仅 ~1.0ms）。
- 读侧有两段瞬时抖动：**+200~350s**（均值/p99 抬升）与 **+770~810s**（均值飙 ~800µs、p99 ~1.3ms），与 RUN1 位置吻合。
- 写 p99 全程在 ~10-20ms 带震荡（与基线同带）。

### 4.3 升级完成后
- read mean ~232 µs（≈基线），p99 ~415 µs 稳定。
- write mean 降到 ~440-468 µs（比基线 ~631 降 ~28%），**write p99 从 ~15ms 骤降到 ~556-652 µs**。

## 5. 结论
在线升吞吐总体低影响、IO 未中断；读侧两段抖动与 RUN1 一致（可复现），
写侧大尖峰未复现，升级完成后写延迟改善明确。详见 `../REPORT_COMPARISON.md`。

## 6. 资源（默认保留）
```
FileSystem : fs-0a1bf6a382dc76343   (SINGLE_AZ_2, 现 3072 MBps, 1024 GiB)
SVM        : svm-023b0ef9483889a55
Volume     : fsvol-062bcc45eb084f209
SG         : sg-02326ca1dc0af5246 (复用)
```
清理命令见 `../REPORT_COMPARISON.md` 第 4 节。

## 7. 产物
- `results_run2.csv` — 采样数据（校正后 T0=触发时刻）
- `tp_results2_raw.csv` — 原始未校正数据（T0 早 16s）
- `latency_curve_run2.png` — RUN2 延迟曲线
