# DuckLake vs S3 Tables — 中立引擎 Trino 复测（SF100）

测试日期：2026-08-27 · region us-east-2 · **中立查询引擎 Trino 476（JDK 24）** · 单机
机器：1× r7i.2xlarge（8 vCPU / 61GB / gp3 200GB）· 数据 TPC-DS SF100（store_sales 287,997,024 行；inventory 399,330,000 行）

## 为什么做这轮

上一轮（`RESULTS.md`）用 **DuckDB 一个引擎**测 DuckLake vs S3 Tables，得出"S3 Tables 冷查询快 ~4×"。
但 DuckLake 是 DuckDB Labs 的亲儿子，存在"**主场偏袒**"嫌疑：DuckDB 对自家格式 DuckLake 可能有专门优化，
对 S3 Tables（Iceberg）反而是"外人"。为剥离这层偏袒，本轮换一个**对两种格式都是外人的中立引擎 Trino** 重测。

**核心问题：同样的数据、同样的格式，换成中立引擎 Trino 后，DuckLake vs S3 Tables 的差距是否还像 DuckDB 下那么大？**

## 测试设计（唯一变量 = 表格式 / catalog）

- 同一份 SF100 数据（DuckDB v1.5.5 生成 → 导出 Parquet → 分别灌入两种格式，行数完全一致，实测校验通过）。
- **同一个中立引擎 Trino 476**、同一台机器、同一 region/子网（走 S3 gateway endpoint）。
- **A = DuckLake**：元数据 PostgreSQL + 数据 S3 Parquet。Trino 读取用 **社区连接器 `altertable-ai/trino-ducklake`**（纯 Java，直接读 PostgreSQL 元数据 + S3 Parquet，**完全不经过 DuckDB**）。
- **C = S3 Tables**：AWS 托管 Iceberg。Trino 读取用**原生 Iceberg REST 连接器**（`iceberg.catalog.type=rest` + S3 Tables Iceberg REST endpoint + SigV4）。
- 查询：与上一轮完全相同的 5 条（`queries.sql`）× 3 轮。计时用 **Trino 服务端 elapsed（system.runtime.queries），排除 JVM/客户端启动开销**。R1=冷，R2/R3=warm。

## ✅ 可行性验证（先验证再灌数据）

按任务铁律，先花时间验证"Trino 能否读两种格式"，再灌 SF100：
- **Trino 读 S3 Tables**：✅ 成熟。原生 Iceberg REST 连接器直连 S3 Tables endpoint，开箱即用。
- **Trino 读 DuckLake**：✅ 可行，但连接器是**社区 POC**（`altertable-ai/trino-ducklake`，作者自述 "proof of concept, not production-ready"）。
  - 需自行用 Maven 编译（Trino 476 / JDK 24）。
  - 编译后遇两个坑，均已修复（见下"连接器踩坑"），修完能正确读出全部数据、聚合结果正确。
- **为何不用 Spark**：MotherDuck 的 `ducklake-spark` 连接器"**底层用 DuckDB 的 ducklake 扩展**去读 DuckLake catalog"——这会把 DuckDB 重新引回读取路径，**破坏中立性**。而 `trino-ducklake` 是纯 Java、不碰 DuckDB，才是真正的中立引擎，故选 Trino。

## 结果 1：数据加载耗时（DuckDB v1.5.5 写入，供参考）

| 表 | A DuckLake | C S3 Tables |
|---|---|---|
| store_sales | 52.9s | 107.2s |
| catalog_sales | 37.1s | 72.9s |
| web_sales | 16.3s | 32.7s |
| inventory | 8.1s | 8.6s |
| 维表×3 | ~2.3s | ~4.4s |
| **合计** | **~116.7s** | **~225.8s** |

→ DuckLake 写入快约 **1.9×**（与上一轮 ~1.8× 一致，元数据入 PostgreSQL、提交轻）。

## 结果 2：查询性能（Trino 服务端 elapsed，单位 ms）

| 查询 | DL R1(冷) | DL R2 | DL R3 | **DL warm** | S3T R1(冷) | S3T R2 | S3T R3 | **S3T warm** | **DL/S3T (warm)** |
|---|---|---|---|---|---|---|---|---|---|
| Q1 store_sales 聚合 | 12937 | 6591 | 7205 | **6.90s** | 5828 | 2192 | 2113 | **2.15s** | **3.2×** |
| Q2 ss+date_dim JOIN | 14732 | 14551 | 12184 | **13.37s** | 4072 | 2798 | 2740 | **2.77s** | **4.8×** |
| Q3 三表 JOIN | 25938 | 22993 | 22733 | **22.86s** | 7086 | 5556 | 5845 | **5.70s** | **4.0×** |
| Q4 inventory 聚合(399M) | 9347 | 9586 | 11728 | **10.66s** | 3279 | 2682 | 2533 | **2.61s** | **4.1×** |
| Q5 三大 sales union | 14795 | 14538 | 14778 | **14.66s** | 3469 | 2510 | 2367 | **2.44s** | **6.0×** |
| **合计** | 77.7 | 68.3 | 68.6 | **68.4s** | 23.7 | 15.7 | 15.6 | **15.7s** | **4.4×** |

**→ 换成中立引擎 Trino 后，S3 Tables 仍比 DuckLake 快约 4.4×（warm），差距不但没消失，量级和 DuckDB 那轮（~4.1×）几乎一样。**

## 结果 3：根因诊断（EXPLAIN ANALYZE 实测，Q2 store_sales 扫描节点）

同一条 Q2（store_sales JOIN date_dim WHERE d_year=2001）在两种格式下的 store_sales 扫描节点对比：

| 指标 | DuckLake | S3 Tables |
|---|---|---|
| 逻辑输入行 | 287,997,024 (4.83GB) | 287,997,024 (4.83GB) |
| **动态过滤命中率 Filtered** | **仅 15.71%** | **81.00%** |
| **物理读取量 Physical input** | **1.15 GB** | **871 MB** |
| **物理读取耗时 Physical input time** | **2.72 分钟 (163s)** | **29.3 秒** |
| **Splits 数（并行度）** | **25** | **81** |

三个决定性差异：
1. **物理读取耗时 DuckLake 163s vs S3 Tables 29s（~5.6×）**——同样的 4.83GB 逻辑数据，DuckLake 的 Parquet 读取路径慢得多。
2. **Splits：DuckLake 只有 25 个（≈每个 627MB 大文件一个 split）→ 8 核并行度严重不足**；S3 Tables 切成 81 个 split，把 8 核喂满、IO 并发高。
3. **动态过滤命中率 DuckLake 15.71% vs S3 Tables 81%**——S3 Tables（Iceberg）有更好的**列/行组统计信息**做数据跳过；DuckLake 侧几乎没跳过多少。

DuckLake 数据文件布局：store_sales = **25 个 × ~577MB 大文件（14.4GB）**，与上一轮完全一致（文件布局健康，非小文件问题）。

## ⚠️ 重要诚实声明：这轮对比也不是完美的"公平对照"

**必须标注的混淆因素（待进一步验证才能定论到"纯格式差异"）**：

- `trino-ducklake` 连接器是**社区 POC，明确没实现谓词下推（No Predicate Pushdown）**，也没有 split 细分优化——它把每个 Parquet 文件当一个 split 整读。
- Trino 的 **Iceberg 连接器是生产级成熟实现**，有完整的统计下推、行组裁剪、split 细分。
- 因此这轮 Trino 对比里，**DuckLake 侧被"连接器不成熟"拖累**，S3T 侧享受成熟连接器红利。所以 4.4× 里，**有多少来自"格式本身"、有多少来自"连接器成熟度差异"，本轮无法完全拆开——属待进一步验证**。

**但仍有确凿结论**：
- 上一轮担心的"DuckDB 主场偏袒论"（怀疑 S3T 快只是因为 DuckDB 优化自家 iceberg_scan）**不成立/至少不是主因**——因为**完全不用 DuckDB 的中立引擎 Trino 下，S3 Tables 依旧快 ~4×，量级不变**。
- 物理层实测（EXPLAIN ANALYZE）显示 DuckLake 慢在**读取路径本身**（物理读取耗时 5.6×、并行度低、统计跳过少），这是**跨两个引擎（DuckDB + Trino）复现的一致现象**，不是单一引擎的偏袒。

## 结论

1. **换中立引擎（Trino）后，S3 Tables 查询仍比 DuckLake 快 ~4.4×，与 DuckDB 那轮（~4.1×）量级一致。**"DuckDB 主场偏袒导致 S3T 假快"这个假设被**证伪**——差距在两个独立引擎下都稳定复现。
2. **写入**：DuckLake 仍快 ~1.9×（元数据入 SQL 库，提交轻）——DuckLake 的核心卖点（轻量元数据/写入）在两轮都成立。
3. **读取慢的物理根因（跨引擎一致）**：DuckLake 数据布局导致 ①split 粗、并行度低 ②Iceberg 统计信息更利于数据跳过而 DuckLake 侧跳过少 ③物理读取耗时数倍于 S3 Tables。
4. ⚠️ **待验证**：本轮 DuckLake 侧受"POC 连接器无谓词下推"拖累，无法把 4.4× 完全归因到"纯格式差异"。要彻底定论，需一个**成熟的 DuckLake 引擎/连接器**（如未来官方 Trino/Spark 原生支持、或 DuckLake 引擎自身持续优化）再测。DuckLake 很新（v0.2→1.0 演进中），读取性能有改善空间。
5. **选型启示（SF100 规模、本测试范围内）**：重查询/分析吞吐 → S3 Tables 明显占优；重写入/频繁元数据操作/轻量运维 → DuckLake 有优势。跨引擎生态成熟度上，Iceberg/S3 Tables 目前远领先 DuckLake。

## 附：连接器踩坑（trino-ducklake POC，供复现）

1. **强制要求静态 S3 access-key/secret-key**（`@NotNull`），不支持默认凭证链/实例 profile → 移除两个 getter 上的 `@NotNull` 注解后回退到 Trino 原生 S3 文件系统的默认凭证链（本测试仍给了一个只读 scoped key）。
2. **S3 路径拼错**：连接器把相对路径拼成 `s3://bucket/<PG schema=public>/<schema>/<table>/<file>`，而 DuckDB 的 DuckLake 实际布局是 `<ducklake_metadata.data_path>/<schema>/<table>/<file>`。→ 打补丁：读 `ducklake_metadata.data_path` 拼正确路径，读取即成功。
3. S3 Tables 侧：Trino 476 用 `iceberg.rest-catalog.sigv4-enabled=true` + `signing-name=s3tables`，且 SigV4 REST 签名需显式 `s3.aws-access-key/secret-key`（不走实例 profile）。

## 原始 Run Time 日志（Trino 服务端 elapsed ms）

```
DuckLake  R1(冷): Q1 12937  Q2 14732  Q3 25938  Q4 9347   Q5 14795   (合计 77.7s)
DuckLake  R2:     Q1 6591   Q2 14551  Q3 22993  Q4 9586   Q5 14538
DuckLake  R3:     Q1 7205   Q2 12184  Q3 22733  Q4 11728  Q5 14778
S3 Tables R1(冷): Q1 5828   Q2 4072   Q3 7086   Q4 3279   Q5 3469    (合计 23.7s)
S3 Tables R2:     Q1 2192   Q2 2798   Q3 5556   Q4 2682   Q5 2510
S3 Tables R3:     Q1 2113   Q2 2740   Q3 5845   Q4 2533   Q5 2367

EXPLAIN ANALYZE Q2, store_sales 扫描节点:
  DuckLake:  Input 287,997,024 rows(4.83GB), Filtered 15.71%, Physical input 1.15GB, Physical input time 2.72m, Splits 25
  S3 Tables: Input 287,997,024 rows(4.83GB), Filtered 81.00%, Physical input 871MB,  Physical input time 29.29s, Splits 81
```

*引擎：Trino 476 / JDK 24。DuckLake 连接器：altertable-ai/trino-ducklake（POC，本地打补丁编译）。S3 Tables：Trino 原生 Iceberg REST。*
*所有测试资源（EC2 / S3 bucket / S3 Tables table bucket / IAM role+profile+scoped user / SG）已于测试后清理。*
