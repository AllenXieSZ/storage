# TPC-DS on Iceberg 综合报告：S3 Tables vs 自管 Iceberg（compaction / 无 compaction）

**日期:** 2026-08-11
**环境:** AWS EMR on EC2 (emr-7.13.0, Spark 3.5.6, Iceberg), us-east-2, 1× m5.xlarge + 6× r6i.4xlarge
**两个规模:** SF200 (~200GB) 与 SF2000 (~2TB)

三组唯一变量 = catalog + 存储 + compaction，其余（EMR 集群 / Spark 运行时 / executor 资源 22×4×18g / 查询集 tpcds_2_4 103 SQL / 3 轮 / 同一份源 Parquet）完全对齐。
- **A** = Amazon S3 Tables（托管 Iceberg，自动 compaction）
- **B** = 自管 Iceberg + 手动 `rewrite_data_files` compaction
- **C** = 自管 Iceberg，无 compaction（B/C 用相同 8MB 小文件写入，只对 B 压）
主指标 = warm 均值（第 2、3 轮平均，剔除第 1 轮冷启动）。行数三组校验一致。

---

## 核心结论表

### warm 总耗时比（103 SQL 汇总，基准 B=1.00）

| 规模 | A (S3 Tables) | B (自管 compaction) | C (无 compaction) |
|------|---:|---:|---:|
| **SF200 (200GB)** | 0.92 | 1.00 | **1.58** |
| **SF2000 (2TB)** | 1.09 | 1.00 | **2.52** |

### warm 总耗时绝对值（秒）

| 规模 | A | B | C |
|------|---:|---:|---:|
| SF200 | 451.8 | 489.4 | 770.6 |
| SF2000 | 2256.7 | 2065.2 | 5195.7 |

### store_sales 文件数（live snapshot）

| 规模 | A | B | C | C 是 A/B 的倍数 |
|------|---:|---:|---:|---:|
| SF200 | 38 | 38 | 2674 | ~70× |
| SF2000 | 389 | 389 | 27142 | ~70× |

---

## 三大结论

### 1. Compaction 是决定性的，且规模越大越关键
- 无 compaction（C）相比 compaction 后（B）：
  - SF200：慢 **58%**
  - SF2000：慢 **152%（2.5×）**
- 小文件惩罚随数据量急剧放大。SF2000 下扫描密集查询（q14a/b、q75、q23）普遍慢 2.6–3.8×，单个查询绝对增量可达 **+129 秒**。
- C 的多轮耗时基本不随轮次下降——小文件的 planning/list 开销是**结构性**的，缓存救不了。

### 2. 托管自动 compaction 与手动 compaction 查询性能等价
- 两规模下 A 与 B 大表最终文件数**完全一致**（都收敛到 512MB target）。
- warm 总耗时 A vs B 差异 SF200 = −8%、SF2000 = +9%，**无系统性优劣**，可视为等价。

### 3. ⚠️ S3 Tables 自动 compaction 的代价 = 异步延迟，且延迟随规模增长（最重要运维发现）

| 规模 | S3 Tables 自动压完大事实表(store_sales)所需时间 |
|------|------|
| SF200 (68GB parquet, 2674 小文件) | **~70 分钟** |
| SF2000 (604GB parquet, 27142 小文件) | **~2.5–3 小时** |

- 写完立即查：大表仍是小文件、查询慢，要等后台 maintenance 压完才恢复性能。小表先压、大表后压。
- 自管手动 compaction 可**即时、按需**触发（本次手动压 store_sales 27142→389 约 10 余分钟完成），可控性强。
- **取舍**：S3 Tables 省去 compaction/snapshot/orphan-file 全部运维，代价是新数据落地后有"未压窗口"、且该窗口随规模变长；自管则运维换取即时可控。

### 其它观察
- inventory 表：SF200 时 S3 Tables 自动策略**不压**（保守），SF2000 时因表更大越过阈值被压——自动策略是按表体量/收益判定的。
- 三组行数完全一致（SF200 store_sales=5.5亿；SF2000=55亿），对比公平。

---

## 选型建议

| 场景 | 推荐 |
|------|------|
| 不想运维 compaction/snapshot、能接受新数据"未压窗口"（分钟~小时级，随规模增长） | **S3 Tables (A)** |
| 需要对新写入数据**即时**获得最优查询性能、或对 compaction 时机/策略要求精细可控 | **自管 + 手动 compaction (B)** |
| 任何生产场景 | **务必做 compaction**——无 compaction (C) 在 2TB 已慢 2.5×，规模越大越糟 |

---

## 交付物
- SF200 详报：`reports/tpcds-iceberg-bench-2026-08-11.md`
- SF2000 详报：`reports/tpcds-iceberg-bench-sf2000-2026-08-11.md`
- 原始数据：`s3://tpcds-iceberg-bench-20260811/results/{sf200,sf2000}/bench_{a,b,c}.csv`
- 汇总表：`summary_sf200.csv` / `summary_sf2000.csv`（逐查询 A/B/C 的 r1/median/warm）
- 方法：PySpark `bench.py`（每查询 noop write 完整执行计时，3 轮），EMR on EC2，SSM 驱动。
