# TPC-DS on Iceberg: S3 Tables vs 自管 Iceberg — SF2000 (2TB) 结果

**日期:** 2026-08-11
**环境:** AWS EMR on EC2 (emr-7.13.0, Spark 3.5.6, Iceberg), us-east-2
**集群:** 1× m5.xlarge master + 6× r6i.4xlarge core (96 vCPU)
**规模:** SF2000 (TPC-DS scale factor 2000 ≈ 2TB 原始数据; 源 Parquet 压缩后 ~604 GB)

> 本报告为**阶段2 (SF2000 / 2TB)**。方法学与阶段1 (SF200) 完全一致。SF200 结果见 `tpcds-iceberg-bench-2026-08-11.md`。

---

## 1. 对比设计（与 SF200 完全一致）

三组唯一变量 = catalog + 存储 + compaction：

| 组 | Catalog | 存储 | Compaction |
|----|---------|------|-----------|
| **A** | Amazon **S3 Tables** | S3 Tables 托管桶 (ns=tpcds2000) | **自动**（后台 maintenance，target 512MB） |
| **B** | 自管 Iceberg (Hadoop catalog) | S3 `warehouse-b2000` | **手动** `rewrite_data_files`（target 512MB） |
| **C** | 自管 Iceberg (Hadoop catalog) | S3 `warehouse-c2000` | **无** |

- Executor 资源三组完全一致：22 exec × 4 core × 18g，shuffle=800，dynamicAllocation off。
- B/C 用相同 8MB 小文件 CTAS 写入，只对 B compaction，C 不动。
- 数据完整性校验（三组行数一致）：`store_sales`=**5,500,744,798**，`catalog_sales`=**2,865,643,695**（恰为 SF200 的 10×）。
- 查询集 tpcds_2_4（103 SQL）× 3 轮；主指标 = warm 均值（第 2、3 轮平均）。

---

## 2. 总体结果（103 条 SQL 汇总，秒）

| 指标 | A (S3 Tables) | B (自管 compaction) | C (无 compaction) |
|---|---:|---:|---:|
| 第1轮冷启动 总和 | 2387.3 | 2186.4 | 5404.2 |
| 中位数 总和 | 2268.0 | 2075.8 | 5213.8 |
| **warm(2,3轮) 总和** | **2256.7** | **2065.2** | **5195.7** |

**相对 B 基准的 warm 总耗时比：**

| 组 | 比值 | 结论 |
|----|-----:|------|
| A (S3 Tables) | **1.09** | 比自管 compaction 慢约 9% |
| B (自管 compaction) | 1.00 | 基准 |
| **C (无 compaction)** | **2.52** | 比 compaction **慢约 152%（2.5×）** |

**要点：**
- **无 compaction 在 2TB 下慢 2.5×**（SF200 时仅 1.58×）——**小文件惩罚随数据规模显著放大**。103 条查询中 **94 条**（91%）C 比 B 慢超过 20%。
- **A 与 B 非常接近**（平均每查询 |A−B|/B ≈ 8.4%）。SF2000 下 A 比 B 略慢 ~9%（SF200 时 A 略快 8%）。两者大表最终文件数完全一致（见下），差异在合理波动范围，无系统性优劣——可认为**托管自动 compaction 与手动 compaction 查询性能等价**。

---

## 3. 文件数对比（Iceberg live snapshot `.files`）

| 表 | A (S3 Tables) | B (compaction) | C (无 compaction) |
|----|---:|---:|---:|
| store_sales | 389 | 389 | **27142** |
| catalog_sales | 312 | 312 | **22108** |
| web_sales | 144 | 144 | **10726** |
| inventory | 7 | 7 | 522 |

- C 的 store_sales 小文件数是 A/B 的 **~70 倍**（27142 vs 389）。
- **A 与 B 大表最终文件数完全一致**——托管自动 compaction 与手动 rewrite 收敛到相同结果。
- **注意 inventory**：本次 SF2000 下 A 也压到了 7（与 B 一致），与 SF200 时 S3 Tables 不压 inventory 的行为不同——可能因 SF2000 下 inventory 更大（522 小文件），越过了自动策略阈值。

---

## 4. ⚠️ 关键发现：S3 Tables 自动 compaction 触发时间随规模显著变长

这是本次 2TB 测试**最重要的运维发现**：

| 规模 | S3 Tables 把大事实表(store_sales) 自动压完所需时间 |
|------|------|
| SF200 (68GB parquet, 2674 小文件) | **~70 分钟** |
| SF2000 (604GB parquet, 27142 小文件) | **~2.5–3 小时** |

- 写完 A 表后立即查看，大表仍是 27142 小文件未压；小表（web_sales/inventory）先被压。
- 大表（store_sales 246GB / catalog_sales）约 **2.5–3 小时**后才被后台 maintenance 压到与手动一致。
- **含义**：S3 Tables 自动 compaction 是**异步后台**、由 AWS 调度、随数据量放大延迟增加。
  - 对"写完立即高频查询"或"对新数据延迟敏感"的场景，**刚落地时仍是小文件、查询会慢**，直到后台压完。
  - 自管手动 compaction 可**立即、按需**触发（本次手动压 store_sales 27142→389 约 10 余分钟即完成，可控性强）。
- 本报告为公平对比，**等 A 大表自动压完后才测 A**，故 A 的查询数字反映"已压完"稳态。

---

## 5. 受 compaction 影响最大的查询（warm 均值，C vs B）

| 查询 | A | B | C | C/B | C−B(秒) |
|------|--:|--:|--:|----:|-------:|
| q14a | 58.66 | 54.97 | 184.26 | 3.35 | 129.29 |
| q14b | 57.80 | 54.94 | 172.15 | 3.13 | 117.21 |
| q75  | 72.00 | 64.61 | 170.05 | 2.63 | 105.44 |
| q23b | 59.67 | 50.06 | 134.24 | 2.68 | 84.18 |
| q23a | 57.92 | 48.39 | 131.85 | 2.72 | 83.46 |
| q31  | 33.23 | 30.66 | 103.05 | 3.36 | 72.40 |
| q11  | 40.46 | 35.33 | 101.05 | 2.86 | 65.72 |
| q4   | 80.49 | 72.58 | 134.31 | 1.85 | 61.73 |
| q76  | 21.54 | 19.51 | 74.15 | 3.80 | 54.64 |
| q56  | 23.16 | 21.32 | 75.62 | 3.55 | 54.29 |

- 最大放大 q92 达 **4.52×**。扫描密集查询绝对增量巨大（q14a 单查询 C 比 B 多耗 **129 秒**）。
- C 的 3 轮耗时基本不随轮次下降（小文件的 planning/list 开销是**结构性**的，非缓存可缓解）。

---

## 6. 结论（SF2000 / 2TB）

1. **规模越大，compaction 越关键**：无 compaction 从 SF200 的慢 58% 恶化到 SF2000 的慢 **152%（2.5×）**。小文件问题在大数据量下急剧放大。
2. **托管 vs 自管 compaction 查询性能等价**：A 与 B 最终文件数一致、warm 耗时差异 ~9%（无系统性优劣）。
3. **S3 Tables 自动 compaction 的代价是"异步延迟"，且延迟随规模增长**（SF200 ~70min → SF2000 ~2.5-3h）。省运维，但**新写入数据在压完前查询会慢**；自管手动 compaction 可即时按需触发、可控性强。
4. 数据完整性校验通过，对比公平有效。

---

## 附录
- 原始逐查询逐轮结果：`s3://tpcds-iceberg-bench-20260811/results/sf2000/bench_{a,b,c}.csv`
- 汇总表：`tpcds_results/sf2000/summary_sf2000.csv`
