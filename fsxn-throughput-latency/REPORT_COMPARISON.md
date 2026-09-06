# FSxN 升吞吐对 IO Latency 影响 —— RUN1 vs RUN2 两次实测对比报告

**日期**: 2026-09-06 | **区域**: AWS us-east-2 (Ohio) | **账号**: 386094880462
**核心问题**: 升吞吐（1536→3072 MBps）对单请求 IO 延迟的冲击**是否可复现？峰值量级两次是否一致？**

---

## 0. 一句话结论（实测为准）

**部分可复现：读延迟的双段瞬时抖动两次高度一致（可复现）；写延迟的"大尖峰"不可复现——RUN1 出现 12.3ms 写均值尖峰，RUN2 完全没有（最大仅 ~1.0ms）。写 p99 的 10-20ms 抖动带、以及升级完成后延迟显著改善，两次都一致。**

即：升吞吐**必然会带来瞬时延迟抖动**（读侧两次都在 +250s 与 +780s 附近，写侧 p99 全程震荡），但**冲击的量级有随机性**，不能保证每次都出现 RUN1 那种十几毫秒级别的写尖峰。

---

## 1. 两次实验规格（完全一致，可比）

| 项目 | RUN1 | RUN2 |
|---|---|---|
| 文件系统类型 | FSxN Gen2 SINGLE_AZ_2, 1 HA pair | 同 |
| 起始/目标吞吐 | 1536 → 3072 MBps | 同 |
| 存储容量 | 1024 GiB SSD | 同 |
| Volume | 512 GiB FlexVol, /vol1, UNIX, SE 关闭 | 同 |
| 子网/AZ | subnet-0c551a33e366d52d4 / us-east-2c | 同 |
| SG | sg-02326ca1dc0af5246 | **复用同一 SG** |
| 挂载/压测机 | i-0dffb881b2a90daa2 (SSM) | 同一台 |
| 挂载参数 | nfsvers=3, rsize/wsize=64K | 同 |
| fio 参数 | bs=16k sync direct=1 numjobs=1 iodepth=1 runtime=8 time_based | 完全相同 |
| FileSystemId | fs-0d7924d394930c95f (已删) | fs-0a1bf6a382dc76343 |

> RUN2 为满足"必须重测升级过程"而**删掉已升到 3072 的旧 FS，重建全新 1536 档 FS**。除文件系统实例 ID 外，规格逐项一致 → 两次可比。

---

## 2. 逐项对比

### 2.1 升吞吐总耗时
| | RUN1 | RUN2 |
|---|---|---|
| 触发→COMPLETED | **~20.5 min** (1234 s) | **~25.8 min** (1546 s) |

两次都在 20-26 分钟量级，RUN2 略长 ~5 分钟。属同一数量级，AWS 后台重配置耗时本身有波动。

### 2.2 基线延迟（升级前，两次几乎一致）
| op | RUN1 mean/p99 | RUN2 mean/p99 |
|---|---|---|
| read | ~224 / ~316 µs | ~197 / ~327 µs |
| write | ~733 / ~18300 µs | ~631 / ~15270 µs |

基线读均值 ~200µs、写均值 ~600-730µs、写 p99 ~15-18ms（16k sync 写受 NFS 提交抖动，p99 本就高），**两次一致**。

### 2.3 升级过程中的峰值（核心差异）
| op / 指标 | RUN1 | RUN2 | 是否复现 |
|---|---|---|---|
| **write 峰值 mean** | **12,336 µs (12.3 ms) @ +167s** | **1,038 µs (1.0 ms) @ +604s** | ❌ **不复现**（差 12×）|
| write 峰值 p99 | 22,656 µs @ +0s | 20,864 µs @ +67s | ✅ 一致（~21-23ms 同量级，基本是基线 p99 带）|
| **read 峰值 mean** | **904 µs @ +784s** | **808 µs @ +805s** | ✅ **高度一致**（量级+时刻都吻合）|
| read 峰值 p99 | 1,400 µs @ +768s | 1,272 µs @ +788s | ✅ **高度一致** |

### 2.4 冲击尖刺的位置/次数（读侧可复现，见 comparison.png 左列）
- **两次都有两段读抖动窗口**：
  - 第一段 **+200~350s**：读均值/p99 短暂抬升（RUN1 峰 ~700µs，RUN2 峰 ~700µs）。
  - 第二段 **+770~810s**：读均值飙到 ~800-900µs、p99 ~1.2-1.4ms（两次几乎重叠）。
- **写侧 p99 全程在 ~10-20ms 带内震荡**（两次都是），无法单点定位；写均值 RUN1 有一个孤立的 12.3ms 尖峰、RUN2 没有。

### 2.5 升级完成后的改善（两次都一致，可复现）
| op | RUN1 完成后 | RUN2 完成后 |
|---|---|---|
| read mean | ~184 µs（低于基线） | ~232 µs（≈基线） |
| write mean | ~390-410 µs（比基线降 ~45%） | ~440-468 µs（比基线降 ~28%） |
| write p99 | 从 ~18ms 降到 ~500-570 µs | 从 ~15ms 降到 ~556-652 µs |

**两次都出现"写 p99 从十几毫秒骤降到 sub-ms、写均值下降"的明确改善** → 升到 3072 后单请求写延迟与尾延迟均更低更稳，**这是最稳定可复现的收益**。

---

## 3. 回答核心问题

**Q1: 升吞吐对延迟的冲击是否可复现？**
> **部分可复现。** 读延迟的双段瞬时抖动（+250s 与 +780s 附近）两次高度一致，可复现；写 p99 的十几毫秒震荡带、以及升级完成后的延迟改善也两次一致。但**写均值的"大尖峰"不可复现**——它是随机出现的单点事件。

**Q2: 峰值量级两次是否一致？**
> **读侧一致，写侧不一致。** 读峰值两次都在 ~800-900µs mean / ~1.2-1.4ms p99（吻合）。写峰值 RUN1 达 12.3ms（mean），RUN2 只有 1.0ms（mean），**相差 ~12 倍，量级不一致**。写 p99 峰值两次都 ~21-23ms（但这基本落在基线 p99 带内，不算升级独有）。

**结论**：FSxN Gen2 在线升吞吐是"在线、总体低影响"操作，绝大多数时刻延迟接近基线；它**会**引入瞬时延迟抖动（读侧位置可复现），但**是否出现十几毫秒级的写尖峰带有随机性**，不保证每次复现。对延迟极敏感的同步小 IO 生产负载，建议把升吞吐排在低峰窗口；升级完成后的延迟改善两次都确认成立。

---

## 4. 产物与资源

- 图：`comparison.png`（RUN1 vs RUN2 的 read/write × mean/p99 四宫格叠加），`run2/latency_curve_run2.png`，`run1/latency_curve_run1.png`
- 数据：`run2/results_run2.csv`（105 read + 105 write 样本），`run1/results_run1.csv`
- 报告：本文件 + `run1/REPORT_RUN1.md` + `run2/REPORT_RUN2.md`
- 脚本：`latency_loop.sh`（RUN1）、RUN2 采样脚本内嵌于流程、`plot.py` / `plot_run2.py` / `plot_comparison.py`

### RUN2 新资源（默认保留，伟伟习惯）
```
FileSystem : fs-0a1bf6a382dc76343   (SINGLE_AZ_2, 现 3072 MBps, 1024 GiB)
SVM        : svm-023b0ef9483889a55  (NFS IP 172.31.33.250)
Volume     : fsvol-062bcc45eb084f209 (vol1, /vol1)
SG         : sg-02326ca1dc0af5246   (复用)
挂载机     : i-0dffb881b2a90daa2 (共用跳板机)
```
RUN1 资源（fs-0d7924d394930c95f 等）已在 RUN2 前按顺序删除。

### RUN2 清理命令（需要时执行）
```bash
R=us-east-2
aws fsx delete-volume --volume-id fsvol-062bcc45eb084f209 --ontap-configuration '{"SkipFinalBackup":true}' --region $R
# 等 volume 删完：
aws fsx delete-storage-virtual-machine --storage-virtual-machine-id svm-023b0ef9483889a55 --region $R
# 等 SVM 删完：
aws fsx delete-file-system --file-system-id fs-0a1bf6a382dc76343 --region $R
# 如需删 SG（复用的，通常保留）：
# aws ec2 delete-security-group --group-id sg-02326ca1dc0af5246 --region $R
```

## 5. 方法学备注（诚实标注）
- RUN2 采样循环的 T0 比实际升吞吐触发早 16s（先起循环再发 update）；分析时已把 upgrade 阶段的 elapsed 统一减 16s，使 T0=触发时刻，与 RUN1 对齐。原始未校正数据见 `run2/tp_results2_raw.csv`。
- 每轮 read(8s)+write(8s)+开销 ≈ 每 ~17s 一个 read/write 样本对（runtime 严格保留 8s），节奏略大于名义 10s，两次一致。
- 延迟均为 fio clat（sync/direct/iodepth=1 下即真实单请求延迟）实测，非推理。
