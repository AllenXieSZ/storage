# DuckLake vs S3 Tables 基准 — SF2000 (2TB) 结果 + 规模反转发现

测试日期：2026-08-27 · region us-east-2 · 引擎 DuckDB v1.5.5
机器：1× r7i.8xlarge（32 vCPU / 256GB / gp3 1TB）· 数据 TPC-DS SF2000（store_sales 5,759,954,874 行 ≈ 57.6 亿）

## 🎯 头号发现：规模反转（Scale Reversal）

**同一套测试、同一引擎，SF100 和 SF2000 结论完全相反：**

| 规模 | 谁的查询快 | 倍数 |
|---|---|---|
| **SF100（~10GB 级）** | **S3 Tables 快** | 4.1× |
| **SF2000（2TB）** | **DuckLake 快** | 1.25× |

→ **"DuckLake 冷查询慢" 只在小数据成立；数据规模大到远超内存后，DuckLake 反而更快。**

## 查询性能对比（warm，round2/3 均值）

### SF2000（2TB）
| 查询 | DuckLake | S3 Tables | S3T/DL |
|---|---|---|---|
| Q1 store_sales 聚合 | 167.4s | 243.4s | 1.45× |
| Q2 ss+date JOIN | 171.4s | 188.9s | 1.10× |
| Q3 三表 JOIN | 182.2s | 195.5s | 1.07× |
| Q4 inventory 聚合 | 0.8s | 1.4s | 1.86× |
| Q5 三 sales union | 113.2s | 163.2s | 1.44× |
| **合计** | **635s** | **792.5s** | **1.25×（DuckLake 快）** |

### 对比 SF100（之前）
- 合计 DuckLake 42.8s vs S3 Tables 10.4s → **S3 Tables 快 4.1×**

## 根因诊断（EXPLAIN ANALYZE 硬证据，非推测）

**SF2000 冷查询 store_sales 聚合（同引擎、同数据、同机）：**

| | 冷查询耗时 | S3 GET 请求数 | 扫描行数 |
|---|---|---|---|
| **DuckLake** | 172.2s | **94,157** | 5.76B |
| **S3 Tables** | 238.0s | **139,310** | 5.76B |

- **DuckLake 发的 GET 请求少 32%（94K vs 139K）** → 大规模全表扫描下 DuckLake 的数据文件布局 / 元数据组织让它用更少的 S3 IO 请求读完同样的数据 → 冷查询更快。
- 两组**热查询（缓存后）都 3-5s**（DuckLake 3.2s / S3 Tables 4.7s），差异全在冷启动 IO。
- store_sales 数据 = 407 个大 parquet 文件（DuckLake 侧），布局健康。

### 与 SF100 根因对照（关键）
| | SF100 | SF2000 |
|---|---|---|
| DuckLake 冷读 GET 次数 | **4,711（碎、多）** → 慢 | **94,157 但比 S3T 少 32%** → 快 |
| 谁快 | S3 Tables | DuckLake |
| 数据 vs 内存 | 小，可缓存 | 2TB 远超内存，每轮真扫 |

- **SF100**：数据小能缓存，S3 Tables 首次 IO 调度优势主导；DuckLake 对小数据的 627MB 文件发过多碎 Range GET 吃亏。
- **SF2000**：数据远超内存，比拼大规模全表扫描的 IO 效率，DuckLake 发更少 GET → 反超。

⚠️ 标注：
- **确凿（实测+EXPLAIN）**：两规模结论相反；SF2000 下 DuckLake GET 少 32%、冷查询快、warm 合计快 1.25×；热查询两者都 3-5s。
- **推测（待深究）**："DuckLake 为何在大规模发更少 GET"（文件/row-group 布局、元数据在 PostgreSQL 使规划更省 IO）属基于现象的推断，未逐层验证到源码。

## 加载耗时（SF2000，写入 S3）

| 表 | DuckLake | S3 Tables |
|---|---|---|
| web_sales | 120.3s | 180.9s |
| catalog_sales | 281.9s | 398.3s |
| store_sales | —(未单记) | 577.0s |
| 维表 | 秒级 | 秒级 |

→ **DuckLake 写入依旧更快**（元数据入 PostgreSQL，提交轻），SF100/SF2000 一致。

## 综合结论

1. **写入**：DuckLake 两个规模都更快（~1.5-1.8×），元数据入 SQL 库的优势稳定。
2. **查询**：**存在规模反转** —— 小数据(SF100)S3 Tables 快 4×，大数据(2TB)DuckLake 快 1.25×。
3. **根因**：差异全在冷启动 S3 读取；大规模下 DuckLake 发更少 GET(94K vs 139K)反而高效，小规模下 DuckLake 碎 GET 吃亏。
4. **选型启示**：
   - 数据量小、交互式、可缓存 → S3 Tables 冷启动更顺；
   - 数据量大(TB级)、全表扫描密集 → DuckLake 查询更快 + 写入更快 + 元数据操作快。
5. ⚠️ 本测试为单机 DuckDB 单引擎、5 条查询；不同引擎(Spark/Trino)、不同查询、DuckLake 版本演进(v1.0 仅 2026-04)结果可能变化。

## 原始日志摘录
```
SF2000 查询 warm:
 DuckLake  R2: 169.3 172.3 179.9 0.73 111.0 | R3: 165.6 170.5 184.6 0.79 115.5
 S3 Tables R2: 247.6 190.3 195.6 1.47 166.6 | R3: 239.1 187.5 195.5 1.37 159.8
冷/热(同进程):
 DuckLake  cold 172.2s / hot 3.2s ; EXPLAIN #GET=94157
 S3 Tables cold 238.0s / hot 4.7s ; EXPLAIN #GET=139310
```

*所有测试资源已于测试后清理。*
