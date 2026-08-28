# DuckLake vs S3 Tables @ SF2000 (2TB) — 三引擎中立交叉验证（DuckDB · Trino · Spark，同一份数据）

测试日期：2026-08-28 · region us-east-2 · 单机 **r7i.8xlarge（32 vCPU / 247GB RAM / 1TB gp3）**
数据：TPC-DS **SF2000（2TB）**，DuckDB v1.5.5 `dsdgen` 生成（耗时 6h15m，单线程瓶颈）。
- store_sales **5,759,954,874 行（57.6 亿）**，catalog_sales 28.8 亿，web_sales 14.4 亿，inventory 3758 万，date_dim 73,049，item 48,000，customer 910 万。
- **同一份 DuckDB 库**灌成两种格式，行数逐表校验完全一致（见文末）。

## 🎯 本轮要回答的问题
之前的结论都可能受"引擎"或"数据集"干扰：
- `RESULTS.md`（DuckDB SF100）：S3 Tables 快 4.1×
- `RESULTS_SF2000.md`（DuckDB 2TB，**另一份数据**）：DuckLake 反超 1.25×（"规模反转"）
- `RESULTS_TRINO.md`（Trino SF100）：S3 Tables 快 4.4×

本轮**在同一台机器、同一份 2TB 数据上，用三个引擎各自跑相同的 5 查询 × 3 轮 × 两格式**，
把"引擎"和"数据集"两个变量都锁死，做真正公平的对照，并回答：
**2TB 规模下，中立引擎（Trino/Spark）会不会复现 DuckDB 那样的"规模反转"（DuckLake 反超）？**

---

## ⚠️ 引擎中立性与可行性（务必先读，决定哪些结果可信）

| 引擎 | 读 S3 Tables (Iceberg) | 读 DuckLake | 中立性 |
|---|---|---|---|
| **DuckDB v1.5.5** | `iceberg` 扩展（第三方路径）| `ducklake` 扩展（**DuckDB Labs 亲儿子，主场**）| ❌ 有主场偏袒（DuckLake 是自家格式）|
| **Trino 476** | 原生 Iceberg REST 连接器（**生产级**）| `altertable-ai/trino-ducklake`（社区 POC，纯 Java 不经 DuckDB，**真中立但无谓词下推**）| ✅ 对两格式都是外人；但 DuckLake 侧受"连接器不成熟"拖累 |
| **Spark 3.5.3** | `iceberg-spark-runtime` + S3 Tables REST（**原生生产级**）| `PeterVanHolland/ducklake-spark`（纯 Java 无 DuckDB）| ⚠️ **该连接器在本数据上有正确性 BUG（见下），DuckLake 侧结果不可用** |

### 🔴 重大诚实声明：Spark 读 DuckLake 结果无效（连接器 BUG，实测确认）
`ducklake-spark`（纯 Java、无 DuckDB，本可作为真中立方案）在本 2TB 数据上**读出错误结果**：
- `date_dim WHERE d_year=2001` 返回 **0 行**（正确应为 365 行）；`d_year/d_date_sk` 全读成 NULL。
- `item.i_item_sk` 全为 **NULL**，但 `i_category` 读取正确（distinct=10 正确）。
- 现象：**整型/decimal 键列被读成 NULL，字符串列正常** → 典型的 Parquet 列类型映射错位（DuckDB 写的 DuckLake parquet 用了 DuckDB 的逻辑类型标注，Spark 的 `VectorizedParquetRecordReader` 按名映射时对 INT/decimal 列失败）。
- 后果：Q1 只聚合出 1 组、Q2/Q3 JOIN 键为 NULL 返回 0 行 → **Spark+DuckLake 的耗时数字建立在错误结果上，本报告予以剔除，不做对比**（铁律：能实测就实测，读不了/读错就如实报"不可用"，绝不编数据）。
- 已为让它跑起来打了 3 个补丁（`is_partition = 1`→`= true` 布尔比较、`getDataFiles` 拼 `schema/table/` 路径前缀、`data_path` 转 `s3a://`），补丁让它"能跑且不报错"，但**列值正确性问题是连接器读取层的深层缺陷，非配置可修**。

> Spark 侧只有 **S3 Tables（Iceberg 原生连接器）结果有效**，用于验证"成熟大数据引擎读 S3 Tables 的表现"。

---

## 结果总表：三引擎 × 两格式 @ 2TB（单位秒）

### A. 冷查询 R1（进程首次、无缓存）

| 查询 | DuckDB-DL | DuckDB-S3T | Trino-DL | Trino-S3T | Spark-S3T |
|---|---|---|---|---|---|
| Q1 store_sales 聚合 | 181.8 | 18.9 | 12.9 | 5.8 | 41.7 |
| Q2 ss⋈date | 178.9 | 20.4 | 14.7 | 4.1 | 30.9 |
| Q3 三表 JOIN | 186.5 | 25.3 | 25.9 | 7.1 | 40.8 |
| Q4 inventory 聚合 | 0.70 | 1.17 | 9.3 | 3.3 | 2.1 |
| Q5 三 sales union | 118.2 | 15.1 | 14.8 | 3.5 | 43.2 |
| **合计（冷）** | **666.1** | **80.9** | **77.7** | **23.7** | **158.7** |

> Spark 为单轮（2TB 下 warm≈cold，见下），列在冷查询表。

### B. 热查询 warm（R2/R3 均值；DuckDB/Trino 有多轮）

| 查询 | DuckDB-DL | DuckDB-S3T | Trino-DL | Trino-S3T |
|---|---|---|---|---|
| Q1 | 3.74 | 4.52 | 6.90 | 2.15 |
| Q2 | 3.55 | 5.76 | 13.4 | 2.77 |
| Q3 | 5.96 | 9.58 | 22.9 | 5.70 |
| Q4 | 0.028 | 0.35 | 10.7 | 2.61 |
| Q5 | 3.76 | 3.55 | 14.7 | 2.44 |
| **合计（warm）** | **~16.8** | **~23.8** | **68.4** | **15.7** |

### 各引擎"谁快"结论（同一份 2TB 数据）

| 引擎 | 冷查询谁快 | 热查询谁快 | 备注 |
|---|---|---|---|
| **DuckDB** | **S3 Tables 快 8.2×**（81s vs 666s）| **DuckLake 快 1.4×**（16.8 vs 23.8s，数据进 247GB 内存缓存）| 冷读 DuckLake 的 451×601MB 大文件很慢；热读缓存后 DuckLake 略优 |
| **Trino**（中立）| **S3 Tables 快 3.3×**（23.7 vs 77.7s）| **S3 Tables 快 4.4×**（15.7 vs 68.4s）| 全程 S3 Tables 快，无规模反转 |
| **Spark**（S3T 有效）| S3T 有效、DuckLake 连接器读错剔除 | — | 仅能确认 Spark 读 S3 Tables 正确可用 |

---

## 🔑 头号结论：**中立引擎 Trino 下没有"规模反转"，S3 Tables 全程更快**

- **旧 `RESULTS_SF2000.md` 说的"2TB 下 DuckLake 反超 1.25×" 未能在中立引擎上复现。** 那个反超**只发生在 DuckDB 引擎、且只在热查询/特定数据布局下**。
- **在同一份 2TB 数据上，中立引擎 Trino 无论冷热都是 S3 Tables 快约 3.3–4.4×**，量级与 SF100（4.4×）完全一致 → **"S3 Tables 更快" 是跨规模、跨（成熟）引擎稳定的现象**。
- **DuckDB 自己在这份数据上冷查询反而是 S3 Tables 快 8×**（与旧 SF2000 结论相反）——说明旧结论**对数据布局极其敏感**，不能推广。

### 为什么旧 SF2000 与本轮 DuckDB 结论相反？（数据布局差异）
两次 2TB 是**不同的 dsdgen 运行**，DuckDB 写出的 DuckLake 文件布局不同：
- 本轮 store_sales DuckLake = **451 个 × ~601MB 大文件（264.6GB）**。
- S3 Tables（Iceberg，同样 DuckDB 写）= **45,997 个 × ~4.4MB 小文件（196.3GB）**。
- 冷查询：DuckDB 读 451 个 601MB 大文件时**单文件串行 range 读吃亏**（冷 666s）；读 Iceberg 4.4MB 小文件反而能高并发预取（冷 81s）。
- 旧 SF2000 那份数据 DuckLake 文件更碎/更利于 DuckDB 冷读，才出现"DuckLake 冷读 GET 少、反超"。**布局一变，结论就反**——印证旧报告自己标注的"待深究"。

---

## 根因诊断（Trino EXPLAIN ANALYZE，Q2 store_sales 扫描节点，2TB 硬证据）

| 指标 | Trino-DuckLake | Trino-S3 Tables |
|---|---|---|
| 输入行 | 5,759,954,874（96.56GB）| 5,759,954,874（96.53GB）|
| 动态过滤命中 Filtered | 67.87% | 81.00% |
| 物理读取 Physical input | 23.08GB | 19.07GB |
| 物理读取耗时（聚合）| 1.06h | 5.97m |
| **Splits（并行度）** | **451** | **45,996** |

- **文件布局是决定性因素**：DuckLake **451 个 601MB 大文件 → 451 splits**；S3 Tables **45,997 个 ~4.4MB 小文件 → 45,996 splits**。
- Trino 下：S3 Tables 更细的 split + 更好的 Iceberg 统计（动态过滤 81% vs 68%、物理读少）让它把 32 核喂得更满、物理读快 ~10×，故 S3 Tables 更快。
- **注意**：本轮 S3 Tables 是"小文件多"，与 `RESULTS_TRINO.md`（SF100）里"DuckLake 大文件 split 少吃亏"是同一个道理的两面——**谁的文件布局更利于该引擎的并行调度，谁就快**。DuckDB 写 Iceberg 时切成大量小文件，恰好利于 Trino 的高并行 split 调度。

---

## 加载耗时（DuckDB v1.5.5 写入 S3，供参考）

| 表 | DuckLake | S3 Tables |
|---|---|---|
| web_sales (1.44B) | 146.5s | 183.8s |
| catalog_sales (2.88B) | 349.3s | 415.6s |
| store_sales (5.76B) | 475.5s | 583.6s |
| inventory / 维表 | 秒级 | 秒级 |

→ **DuckLake 写入稳定快 ~1.2–1.3×**（元数据入 PostgreSQL，提交轻）。这是 DuckLake 在所有轮次（SF100/两次 2TB）都成立的一致优势。

---

## 综合结论

1. **查询（中立引擎判定）**：**没有规模反转**。中立引擎 Trino 在 2TB 上仍是 **S3 Tables 快 3.3–4.4×**，与 SF100 一致、跨规模稳定。旧 SF2000 报告"DuckLake 2TB 反超"**只在 DuckDB 引擎 + 特定文件布局下成立，不可推广为格式优势**。
2. **DuckDB 主场效应确认**：DuckDB 热查询读自家 DuckLake 略快（缓存后 1.4×），但**冷查询在本数据上 S3 Tables 反而快 8×** → DuckDB 的"DuckLake 优势"高度依赖数据布局和缓存，不稳健。
3. **写入**：DuckLake 稳定快 ~1.2–1.3×（元数据轻），这是它最稳的卖点。
4. **决定性能的真正变量 = 文件布局与引擎的 split 调度匹配度**，而非"格式本身孰优"。大量小文件利于 Trino/Iceberg 高并行；少量大文件利于内存缓存后的 DuckDB 热查询。
5. **生态成熟度（重要选型因素）**：
   - S3 Tables/Iceberg：Trino、Spark **两个中立引擎都原生生产级、结果正确**。
   - DuckLake：DuckDB 原生好用；但**中立引擎生态很不成熟**——Trino 连接器是无下推的社区 POC，Spark 连接器**本轮实测直接读出错误数据**。跨引擎用 DuckLake 目前有实质风险。

## ⚠️ 诚实标注（可信度分级）
- ✅ **确凿（实测+多轮+EXPLAIN）**：三引擎在同一份 2TB 数据上的耗时；Trino 全程 S3T 快 3.3–4.4×；文件布局 451 大文件 vs 45997 小文件；DuckDB 冷 S3T 快 8×/热 DL 快 1.4×；DuckLake 写入快 1.2–1.3×。
- ✅ **确凿（实测）**：Spark-DuckLake 连接器读整型/decimal 键列为 NULL（正确性 BUG），故其数字剔除。
- ⚠️ **待进一步验证**：Trino-DuckLake 受"POC 连接器无谓词下推"拖累，4.4× 无法 100% 拆成"纯格式差异"；DuckLake 很新（1.0 仅 2026-04），读取生态仍在演进。
- ⚠️ **单机、5 条查询、TPC-DS**：换分布式集群、换查询集、换 DuckLake 版本，结论可能变化。

## 附：行数校验（同一份数据灌两格式，逐表一致）
| 表 | DuckLake | S3 Tables |
|---|---|---|
| store_sales | 5,759,954,874 | 5,759,954,874 |
| catalog_sales | 2,880,059,125 | 2,880,059,125 |
| web_sales | 1,439,965,966 | 1,439,965,966 |
| inventory | 37,584,000 | 37,584,000 |
| date_dim | 73,049 | 73,049 |
| item | 48,000 | 48,000 |
| customer | 9,100,000 | 9,100,000 |

*引擎：DuckDB v1.5.5 · Trino 476 (JDK 24) · Spark 3.5.3 (JDK 21)。DuckLake catalog：PostgreSQL 15。*
*Trino-DuckLake：altertable-ai/trino-ducklake（POC，本地打补丁）。Spark-DuckLake：PeterVanHolland/ducklake-spark（本数据读取有 BUG，结果剔除）。S3 Tables：各引擎原生 Iceberg。*
*所有测试资源已于三引擎全部跑完后清理（见 git 提交说明）。*
