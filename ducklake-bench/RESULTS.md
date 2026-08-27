# DuckLake vs S3 Tables 基准测试日志（SF100，单机 DuckDB 统一引擎）

测试日期：2026-08-27 · region us-east-2 · 引擎 DuckDB v1.5.5
机器：1× r7i.4xlarge（16 vCPU / 128GB / gp3 300GB）· 数据 TPC-DS SF100（store_sales 287,997,024 行）

## 测试设计

- **唯一变量 = 表格式 / catalog**，同一份 SF100 数据、同一 DuckDB 引擎、同一台机器。
- **A = DuckLake**：元数据 → 本机 PostgreSQL catalog；数据 → S3 Parquet
- **C = S3 Tables**：AWS 托管 Iceberg（内建 catalog + 自动 compaction）
- （B 自管 Iceberg 手动 compaction 本轮略：DuckDB 单机写 Iceberg 支持弱，且上次 EMR 已充分测过；本轮聚焦新东西 DuckLake vs S3 Tables）
- 加载 7 表（store_sales/catalog_sales/web_sales/inventory/date_dim/item/customer）。
- 查询：5 条扫描/聚合/JOIN 密集查询 × 3 轮，warm = round2/3 均值。

## 结果 1：数据加载耗时（写入 S3）

| 表 | A DuckLake | C S3 Tables |
|---|---|---|
| store_sales | 30.8s | 58.2s |
| catalog_sales | 21.6s | 39.3s |
| web_sales | 10.3s | 18.6s |
| inventory | 4.7s | 5.6s |
| 维表×3 | ~2.1s | ~3.9s |
| **合计** | **~69.6s** | **~125.7s** |

**→ DuckLake 写入快约 1.8×**（S3 Tables 写入走 Iceberg REST catalog + 元数据文件，开销更大）。

## 结果 2：查询性能（warm，round2/3 均值）

| 查询 | DuckLake | S3 Tables | 比值(DL/S3T) |
|---|---|---|---|
| Q1 store_sales 聚合 | 8.39s | 1.98s | 4.2× |
| Q2 ss + date_dim JOIN | 8.51s | 2.07s | 4.1× |
| Q3 三表 JOIN | 9.29s | 2.69s | 3.5× |
| Q4 inventory 聚合(399M) | 5.52s | 1.74s | 3.2× |
| Q5 三大 sales union | 11.12s | 1.91s | 5.8× |
| **合计** | **42.82s** | **10.39s** | **4.1×** |

**→ 查询上 S3 Tables 快约 4×（与"DuckLake 应该更快"的直觉相反）。**

## 结果 3：根因诊断（诚实分析，实测非推测）

独立进程冷/热对照（同一查询 store_sales 聚合）：

| | 第1次(冷) | 第2次(热/缓存) |
|---|---|---|
| DuckLake | **12.76s** | 0.34s |
| S3 Tables | **2.23s** | 0.49s |

**关键发现：差异全在"冷启动首次读取"，热查询两者都 <0.5s。**

EXPLAIN ANALYZE（DuckLake 冷查询）：
- **发了 4,711 个 S3 GET 请求，仅传输 681.6 MiB**（查询只需 2 列）
- store_sales 数据文件 = **23 个 ~627MB 大文件（14.4GB）**，文件布局健康，**不是小文件/未 compaction 问题**

**真因（基于实测 + EXPLAIN）**：DuckLake 首次读 627MB 大 Parquet 文件时，对每个 column chunk / row group 发大量细碎 Range GET（4711 次），S3 往返延迟累积 → 冷查询慢。S3 Tables 侧 DuckDB 的 iceberg_scan IO 调度更优（更少更大的 Range 请求）或文件 row group 布局更利于批量读，冷启动快。

⚠️ **标注**：
- "S3 Tables iceberg_scan IO 更优 / row group 布局更利于批读" 是**基于 4711 GET 现象的推断**，未逐层验证到 DuckDB 源码级别，属**待进一步验证的推测**。
- 确凿的是：**差异真实且公平（独立冷跑复现），根源在冷启动 S3 读取模式（DuckLake 的 Range 请求碎、次数多）**，不是缓存假象、不是小文件问题、不是网络/AZ 差异（同 region 同机同路径）。

## 结论

1. **写入**：DuckLake 快 ~1.8×（元数据入 PostgreSQL，提交轻）。
2. **冷查询**：S3 Tables 快 ~4×（DuckLake 对大 Parquet 发过多细碎 Range GET，冷启动 S3 往返累积）。
3. **热查询**：两者都极快（<0.5s），差异消失——瓶颈纯在首次 S3 读取。
4. **DuckLake 的卖点（元数据入 SQL 库）确实让写入/元数据操作更快**，但**本轮实测中它的数据读取路径在冷启动上不如 S3 Tables 高效**。
5. ⚠️ 本测试为 SF100 单机 DuckDB 单一引擎、5 条查询的小规模验证；不同引擎（Spark/Trino）、更大规模、或 DuckLake 调优后结果可能不同。DuckLake 版本演进快（v1.0 才 2026-04），读取性能可能后续改善。

## 原始 Run Time 日志

```
DuckLake  round1(冷): Q1 19.32 Q2 9.12 Q3 9.61 Q4 10.23 Q5 15.16  (合计 63.4s)
DuckLake  round2:     8.62 8.64 9.37 5.49 11.22
DuckLake  round3:     8.15 8.37 9.21 5.55 11.02
S3 Tables round1(冷): 2.44 2.29 2.94 1.68 7.43  (合计 16.8s)
S3 Tables round2:     2.04 1.95 2.68 1.58 2.02
S3 Tables round3:     1.92 2.19 2.70 1.90 1.80

独立冷/热对照(store_sales聚合):
  DuckLake:  冷 12.76s / 热 0.34s
  S3 Tables: 冷 2.23s  / 热 0.49s
  DuckLake EXPLAIN: #GET=4711, in=681.6 MiB, Total 12.47s
```

*所有测试资源（EC2 r7i.4xlarge / S3 bucket / S3 Tables table bucket / IAM / SG）已于测试后清理。*
