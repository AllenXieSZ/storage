# TPC-DS on Iceberg: S3 Tables vs 自管 Iceberg (compaction) vs 自管 Iceberg (no compaction)

**日期:** 2026-08-11
**环境:** AWS EMR on EC2 (emr-7.13.0, Spark 3.5.6, Iceberg), us-east-2
**集群:** 1× m5.xlarge master + 6× r6i.4xlarge core (96 vCPU, 768 GB core 总内存)
**规模:** SF200 (TPC-DS scale factor 200 ≈ 200 GB 原始数据; 源 Parquet 压缩后 ~68 GB)

> ⚠️ 本报告为**阶段1 (SF200) 初步结果**。阶段2 (SF2000 / 2TB) 待跑。

---

## 1. 对比设计（公平性）

三组**唯一变量 = catalog + 存储 + compaction**，其余完全对齐：

| 组 | Catalog | 存储 | Compaction |
|----|---------|------|-----------|
| **A** | Amazon **S3 Tables**（托管 Iceberg） | S3 Tables 托管桶 | **自动**（后台 maintenance，target 512MB，auto 策略） |
| **B** | 自管 Iceberg（Hadoop catalog） | 普通 S3 桶 `warehouse-b` | **手动** `rewrite_data_files`（target 512MB, min-input-files=5） |
| **C** | 自管 Iceberg（Hadoop catalog） | 普通 S3 桶 `warehouse-c` | **无**（保持小文件） |

**完全对齐项：**
- 同一 EMR 集群、同一 Spark 运行时（3.5.6）、同一 Iceberg 版本、同一 S3 region。
- **Executor 资源三组完全一致**：`spark.executor.instances=22`, `cores=4`, `memory=18g`, `driver=8g`, `shuffle.partitions=352`, `dynamicAllocation=false`。
- 三组数据来自**同一份源 Parquet**（`tpcds-source-parquet/sf200/`），CTAS 写入方式、表结构、行数完全相同（已校验，见下）。
- **B 与 C 初始写入方式完全相同**（都用 `write.target-file-size-bytes=8MB` 强制产生小文件，模拟流式摄入积累的小文件场景），随后**只对 B 执行 compaction**，C 保持不动。因此 B vs C 的唯一差异 = compaction。

**数据完整性校验（三组行数一致）：**
- `store_sales` = 550,091,607 行（A=B=C）
- `catalog_sales` = 286,551,322 行（A=B=C）

**测量方法：**
- TPC-DS 查询集 = `spark-sql-perf` 仓库 `tpcds_2_4`（99 个查询，含 q14a/b、q23a/b、q24a/b、q39a/b 变体，共 **103 条可执行 SQL**）。
- 每查询用 PySpark `spark.sql(q).write.format("noop")` **完整执行**（触发全部计算但不把结果拉回 driver，避免 collect 偏差）。
- 每查询 **跑 3 轮**。报告主指标 = **warm 均值（第 2、3 轮平均，剔除第 1 轮冷启动）**；同时给出中位数与冷启动值。

---

## 2. 总体结果（103 条 SQL 汇总）

| 指标（三组总耗时，秒） | A (S3 Tables) | B (自管+compaction) | C (自管 无compaction) |
|---|---:|---:|---:|
| 第1轮冷启动 总和 | 521.5 | 555.2 | 825.8 |
| 中位数 总和 | 459.2 | 494.1 | 765.4 |
| **warm(2,3轮) 总和** | **451.8** | **489.4** | **770.6** |

**相对 B（compaction）基准的 warm 总耗时比：**

| 组 | 比值 | 结论 |
|----|-----:|------|
| A (S3 Tables) | **0.92** | 比自管 compaction **快约 8%** |
| B (自管 compaction) | 1.00 | 基准 |
| **C (无 compaction)** | **1.58** | 比 compaction **慢约 58%** |

**要点：**
- **Compaction 收益巨大**：无 compaction 的 C 整体比 compaction 后慢 **~58%**。103 条查询中有 **86 条**（83%）C 比 B 慢超过 20%。
- **S3 Tables（A）略优于自管 compaction（B）**，warm 总耗时快约 8%，103 条中 **64 条** A 比 B 快。推测原因（待进一步验证）：S3 Tables 自动 compaction 产出的文件布局/排序更优，且托管侧可能有额外优化——但两者大表最终文件数一致（见下），差异不大，8% 在合理波动+布局差异范围内。

---

## 3. 文件数对比（Iceberg live snapshot `.files` 元数据，非 S3 裸对象）

| 表 | A (S3 Tables) | B (compaction) | C (无 compaction) |
|----|---:|---:|---:|
| store_sales | 38 | 38 | **2674** |
| catalog_sales | 31 | 31 | **2230** |
| web_sales | 15 | 15 | **1093** |
| store_returns | 5 | 5 | **359** |
| inventory | 261 | 4 | 261 |

**要点：**
- C 的大事实表小文件数是 A/B 的 **~70 倍**（store_sales 2674 vs 38），这正是查询变慢的直接原因（大量小文件 → 更多 task/list/open 开销、planning 变慢、扫描效率低）。
- **A 与 B 大表最终文件数完全一致**（都压到 512MB target），说明 S3 Tables 自动 compaction 与手动 `rewrite_data_files` 效果相当。
- **例外 — inventory 表**：S3 Tables（A=261）**没有** compact，而手动 B=4。inventory 是按 `inv_date_sk` 高度分区的中等表，S3 Tables auto 策略判定其无需 compaction（每分区文件已达标或收益不足），手动 rewrite 则强制合并。这是**托管自动策略 vs 手动可控**的一个真实差异点：自动策略更保守。

---

## 4. 受 compaction 影响最大的查询（warm 均值，C vs B）

| 查询 | A | B | C | C/B | C−B(秒) |
|------|--:|--:|--:|----:|-------:|
| q14a | 11.33 | 11.98 | 24.17 | 2.02 | 12.19 |
| q14b | 10.24 | 9.92 | 21.74 | 2.19 | 11.82 |
| q75  | 10.99 | 10.58 | 20.30 | 1.92 | 9.73 |
| q55  | 1.56 | 1.46 | 10.53 | **7.19** | 9.07 |
| q23b | 8.59 | 8.37 | 16.21 | 1.94 | 7.84 |
| q31  | 6.71 | 6.58 | 13.95 | 2.12 | 7.37 |
| q23a | 8.03 | 8.35 | 15.70 | 1.88 | 7.35 |
| q60  | 3.64 | 3.69 | 10.10 | 2.74 | 6.41 |
| q4   | 14.11 | 13.73 | 19.88 | 1.45 | 6.15 |
| q33  | 3.86 | 3.59 | 9.21 | 2.57 | 5.63 |

- 扫描密集型查询（大事实表全扫/多表 join：q14、q75、q23、q4）绝对耗时增加最多。
- q55 出现 **7.19×** 极端放大：该查询本身很轻（B 仅 1.46s），小文件的固定 planning/list 开销占比被放大。

---

## 5. 结论（SF200 阶段）

1. **Compaction 对 Iceberg 查询性能是决定性的**：无 compaction 全套查询慢 ~58%，扫描密集型查询普遍 ~2×，轻查询可达 7×+。小文件问题真实且严重。
2. **S3 Tables 的托管自动 compaction 有效**：加载后 ~70 分钟内后台自动把大事实表压到与手动 compaction 相同的文件数，查询性能甚至略优（~8%），**无需运维介入**。
3. **托管 vs 自管的取舍**：
   - S3 Tables 省去手动 compaction/snapshot 运维，自动策略保守（如 inventory 不压），触发有**异步延迟**（本次 ~70min）——刚写完立即查、或对延迟敏感的场景需注意。
   - 自管 + 手动 compaction 完全可控（可强制压任意表、任意时机），但需自己调度、承担运维与计算成本。
4. **数据完整性**：三组行数完全一致，对比公平有效。

---

## 6. 待办 / 阶段2

- [ ] SF2000（2TB）：重复全流程（数据量放大 10×，小文件与 compaction 差异预计更显著）。
- [ ] （可选）测量每查询扫描字节数（Spark SQL metrics）以量化"少扫多少"。
- [ ] 成本对比：S3 Tables maintenance 计费 vs 自管 compaction 的 EMR 计算成本。

---

## 附录

- 原始逐查询逐轮结果：`s3://tpcds-iceberg-bench-20260811/results/sf200/bench_{a,b,c}.csv`
- 汇总表（逐查询 A/B/C 的 r1/median/warm）：`tpcds_results/summary_sf200.csv`
- 查询集：`spark-sql-perf` `tpcds_2_4`（103 SQL）
- 测量脚本：PySpark `bench.py`（noop write 计时，3 轮）
