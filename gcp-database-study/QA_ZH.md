# GCP 数据库 —— 20 题面试题库（题干 + 作答 + 批改 + GCP↔AWS 对照）

> 方向：GCP 数据库。共 20 题，分 10 个模块，每 2 题一组过。
> 用法：小帅每次过 **2 道**，AI 逐题完整批改（①逐点对照 ②参考答案+原理 ③概念深入 ④GCP↔AWS 对照 ⑤评分+记忆点）。
> 铁律：批改必须完整展开五板块；答完即停，不预告不催。每批改完立即写入本文件 + NOTES_ZH.md 并推 GitHub（不丢批改正文）。
> ⚠️ 技术细节以 GCP 官方文档为准；服务特性会更新，回答/批改前查最新文档核实。

---

## 批改进度追踪

| 批次 | 模块 | 题号 | 状态 | 得分/备注 |
|------|------|------|------|-----------|
| 1 | Cloud SQL 基础 | Q1/Q2 | ✅ 已批改 | 09-13 综合题覆盖（Cloud SQL 三引擎/托管/区域级/IAM/Auth Proxy），6.5/10 |
| 2 | Cloud SQL 高可用与扩展 | Q3/Q4 | ✅ 已批改 | Q3 2.5/10（HA误答成读扩展+手动切换）；Q4 5/10（级联≠外部副本混淆）。09-15 |
| 3 | AlloyDB | Q5/Q6 | ⬜ 待作答 | — |
| 4 | Cloud Spanner | Q7/Q8 | ⬜ 待作答 | — |
| 5 | Bigtable | Q9/Q10 | ⬜ 待作答 | — |
| 6 | Firestore / Datastore | Q11/Q12 | ⬜ 待作答 | — |
| 7 | Memorystore（缓存） | Q13/Q14 | ⬜ 待作答 | — |
| 8 | BigQuery（分析/数仓） | Q15/Q16 | ⬜ 待作答 | — |
| 9 | 迁移 & 复制（DMS/Datastream） | Q17/Q18 | ⬜ 待作答 | — |
| 10 | 综合选型 & 安全 | Q19/Q20 | ⬜ 待作答 | — |

> 进度：待小帅从 Q1、Q2 开始作答。

---

## 第一模块：Cloud SQL 基础

**Q1（Cloud SQL 是什么 / 托管边界）**
1. Cloud SQL 是什么？它支持哪些数据库引擎（MySQL / PostgreSQL / SQL Server）？
2. 作为托管服务，Cloud SQL 帮你管了什么、你还要自己管什么（对比在 GCE 上自建数据库）？
3. Cloud SQL 的实例是区域级（regional）还是全球级？存储怎么扩容（自动扩容）？
4. Cloud SQL 有没有"无服务器（serverless）"形态？它和 AlloyDB / Spanner 的定位差异是什么？

**Q2（连接与安全基础）**
1. 应用怎么连接 Cloud SQL？（公网 IP / 私有 IP / Cloud SQL Auth Proxy / 连接器）各自适用什么场景？
2. Cloud SQL 的私有 IP 是怎么实现的（Private Services Access / VPC peering）？为什么生产推荐私有 IP？
3. Cloud SQL Auth Proxy 解决什么问题（加密 + IAM 鉴权，不用管理 SSL 证书/白名单）？
4. Cloud SQL 支持 IAM 数据库认证吗？数据加密（at-rest / in-transit）怎么做？CMEK 是什么？

---

## 第二模块：Cloud SQL 高可用与扩展

**Q3（高可用 HA）**
1. Cloud SQL 的高可用（HA）配置是什么？它靠什么实现（regional 实例 + 跨 zone 同步复制 + standby）？
2. 故障时怎么切换（自动 failover）？切换后连接地址变不变？RTO 大概什么量级？
3. Cloud SQL 的 HA 是"跨 zone"还是"跨 region"？跨 region 容灾怎么做？
4. HA 提供的是"高可用"还是"读扩展"？和只读副本有什么本质区别？

**Q4（只读副本与读扩展）**
1. Cloud SQL 只读副本（read replica）是什么？同步还是异步复制？主要解决什么问题？
2. 只读副本能跨 region 吗？能不能提升为独立主实例（promote）？
3. 什么是级联副本（cascading replicas）？什么是外部副本 / 从外部源复制？
4. 一个"高可用 + 读扩展"的典型 Cloud SQL 生产架构怎么组合 HA + 只读副本？

---

## 第三模块：AlloyDB

**Q5（AlloyDB 是什么 / 架构）**
1. AlloyDB 是什么？它兼容什么（PostgreSQL 兼容）？定位上填补了 Cloud SQL 和 Spanner 之间的什么空档？
2. AlloyDB 的存算分离架构是怎么回事（计算节点 + 分布式存储层 + 日志处理）？和 Aurora 的思路像吗？
3. AlloyDB 的读池（read pool）是什么？怎么做读扩展？
4. AlloyDB 主打什么场景（HTAP、AI/向量、比开源 PG 快多少的官方宣称）？

**Q6（AlloyDB 进阶）**
1. AlloyDB 的列式引擎（columnar engine）是什么？为什么能加速分析型查询（在同一个 PG 库里做 HTAP）？
2. AlloyDB 的备份、PITR、高可用怎么做？
3. AlloyDB Omni 是什么（可跑在任意环境/本地/其它云）？
4. AlloyDB 对向量检索（pgvector / ScaNN 索引）的支持，和它主打 AI 场景的关系？

---

## 第四模块：Cloud Spanner

**Q7（Spanner 是什么 / 核心机制）**
1. Cloud Spanner 是什么？它最独特的地方是什么（全球分布式 + 强一致 + 水平扩展 + 关系型 SQL）？
2. Spanner 怎么做到"全球强一致"的？TrueTime 是什么，它靠什么（GPS + 原子钟 + 不确定性区间）解决分布式事务的时序问题？
3. Spanner 的扩展单位是什么（node / processing units）？数据怎么分片（split）？
4. Spanner 是不是 serverless？计费模型是什么？

**Q8（Spanner 设计与取舍）**
1. Spanner 的主键 / 交错表（interleaved tables）设计要注意什么？为什么"热点主键（如单调递增/时间戳）"会造成性能问题，怎么避免？
2. Spanner 的一致性和延迟怎么取舍？跨 region 写为什么比单 region 慢（对比 Aurora Global Database 的异步 RPO~1s）？
3. Spanner 的读类型：强读（strong read）vs 陈旧读（stale read）有什么区别？
4. 什么场景该用 Spanner 而不是 Cloud SQL / AlloyDB？（全球规模、无限水平扩展、不能停机的关系型）

---

## 第五模块：Bigtable

**Q9（Bigtable 是什么 / 数据模型）**
1. Cloud Bigtable 是什么类型的数据库（宽列 NoSQL）？它适合什么负载（海量、高吞吐、低延迟、时序/IoT/指标）？
2. Bigtable 的数据模型：row key / column family / column qualifier / cell（带时间戳版本）是怎么组织的？
3. **row key 设计**为什么是 Bigtable 性能的命门？为什么单调递增的 row key（时间戳打头）会造成"热点（hotspotting）"，怎么打散（字段反转/加盐/哈希前缀）？
4. Bigtable 是强一致还是最终一致？单集群 vs 多集群复制时的一致性？

**Q10（Bigtable 运维与选型）**
1. Bigtable 的扩展单位是什么（node）？存储和计算是怎么分离的？自动扩缩（autoscaling）怎么工作？
2. Bigtable 的复制（replication）和多集群路由（multi-cluster routing）怎么做高可用/就近读？
3. Bigtable vs BigQuery：都能存海量数据，怎么选（低延迟点查/高吞吐 vs 大规模分析扫描）？
4. Bigtable 对标 AWS 什么服务？和 HBase 的关系？

---

## 第六模块：Firestore / Datastore

**Q11（Firestore 是什么）**
1. Firestore 是什么类型的数据库（文档型 NoSQL）？它和 Datastore（Firestore in Datastore mode）什么关系？
2. Firestore 的数据模型（collection / document / 子集合）是怎么组织的？和 DynamoDB 的表/项模型有什么不同？
3. Firestore 的两种模式（Native mode vs Datastore mode）区别？各适合什么（移动/Web 实时 vs 服务端）？
4. Firestore 的实时监听（real-time listeners）、离线支持是什么，为什么适合移动/Web 前端直连？

**Q12（Firestore 一致性与扩展）**
1. Firestore 的一致性模型是什么（强一致？）？它的多区域/多region 模式怎么做？
2. Firestore 的索引机制（自动索引 + 复合索引）？为什么有些查询必须先建复合索引？
3. Firestore 的扩展性和计费模型（按文档读/写/删 + 存储）？有没有"热点写"限制（单文档写入频率、500/50/5 规则）？
4. 什么时候用 Firestore、什么时候用 Bigtable、什么时候用 Cloud SQL？

---

## 第七模块：Memorystore（缓存）

**Q13（Memorystore 基础）**
1. Memorystore 是什么？支持哪些引擎（Redis / Memcached / Valkey）？各适合什么场景？
2. Memorystore for Redis 的高可用怎么做（Standard tier + 跨 zone 副本 + 自动 failover）？和 Basic tier 区别？
3. Memorystore 的用途（缓存 / 会话存储 / 排行榜 / 限流）？为什么缓存能减数据库压力？
4. Redis vs Memcached 在 Memorystore 上的本质区别（数据结构/持久化/多线程）？

**Q14（Memorystore 进阶与对比）**
1. Memorystore for Redis Cluster 是什么（分片、水平扩展）？和单节点/主从有什么区别？
2. 缓存的常见问题：缓存穿透 / 击穿 / 雪崩 分别是什么，怎么解决？
3. Cache-aside（旁路缓存）模式怎么工作？写策略（write-through / write-back）区别？
4. Memorystore 对标 AWS 什么服务？和 MemoryDB 类的"持久化 Redis"有没有对应？

---

## 第八模块：BigQuery（分析 / 数仓）

**Q15（BigQuery 是什么 / 架构）**
1. BigQuery 是什么（serverless 数据仓库 / OLAP）？它和 Cloud SQL/AlloyDB（OLTP）有什么本质区别？
2. BigQuery 的存算分离架构（Colossus 存储 + Dremel/Borg 计算 + Jupiter 网络）是怎么回事？为什么它能"无节点、自动扩展"？
3. BigQuery 的列式存储 + 大规模并行为什么适合分析？slots 是什么？
4. BigQuery 的两种计费模型（按扫描量 on-demand vs 容量预留 slots/editions）？怎么省钱（分区表 + 聚簇 + 只查需要的列）？

**Q16（BigQuery 进阶）**
1. BigQuery 的分区表（partitioning）和聚簇（clustering）分别是什么，怎么减少扫描量/费用？
2. BigLake / 外部表是什么？BigQuery 怎么直接查 GCS 上的数据湖（对比 Redshift Spectrum / Athena）？
3. BigQuery ML / BigQuery BI Engine / 物化视图 各解决什么？
4. BigQuery 对标 AWS 什么？它比 Redshift"更 serverless"体现在哪？

---

## 第九模块：迁移 & 复制

**Q17（Database Migration Service）**
1. GCP 的 Database Migration Service（DMS）是什么？它支持哪些迁移（同构/异构、到 Cloud SQL/AlloyDB/Spanner）？
2. 什么是同构迁移 vs 异构迁移？异构迁移靠什么工具做 schema 转换？
3. DMS 的持续迁移（continuous / CDC）怎么做到"最小停机"切换？
4. DMS 对标 AWS 什么服务（AWS DMS / SCT）？

**Q18（Datastream 与实时复制）**
1. Datastream 是什么（serverless CDC / change data capture）？它从哪些源捕获变更（MySQL/PostgreSQL/Oracle）？
2. Datastream → BigQuery 的实时同步典型架构是什么？为什么要把 OLTP 变更实时喂给 BigQuery？
3. CDC（变更数据捕获）的原理是什么（读事务日志 binlog/WAL/redo）？为什么比"定时全量导出"好？
4. Datastream 对标 AWS 什么（Zero-ETL / DMS CDC）？

---

## 第十模块：综合选型 & 安全

**Q19（数据库选型综合）**
1. 给定场景，如何在 GCP 数据库家族里选型？请说清每类的关键决策点：
   - 关系型 OLTP（区域级）：Cloud SQL vs AlloyDB
   - 全球分布式强一致关系型：Spanner
   - 宽列高吞吐 NoSQL：Bigtable
   - 文档型 / 移动后端：Firestore
   - 缓存：Memorystore
   - 分析/数仓：BigQuery
2. 选型三问（一致性要求？规模/全球性？关系型还是 NoSQL？）怎么套用？
3. 举一个"电商交易 + 商品目录 + 实时排行榜 + 数据分析"的综合架构，各环节分别选什么库、为什么？

**Q20（数据库安全与治理）**
1. GCP 数据库的安全怎么做（VPC-SC 边界、私有 IP、IAM、CMEK 客户管理密钥、加密 at-rest/in-transit）？
2. IAM 数据库认证 vs 内置数据库用户密码，各有什么优劣？为什么推荐 IAM？
3. 备份、PITR、跨 region 容灾在各库（Cloud SQL / AlloyDB / Spanner / Firestore / BigQuery）上分别怎么做？
4. 一个"纵深防御"的 GCP 数据库安全架构应覆盖哪些层，并对照 AWS 的等价能力（IAM/KMS/私有连接/审计日志）？
