# AWS 数据库面试题库（30 题）—— RDS / Aurora / NoSQL / 图 / 时序 / 缓存 / 分析

> 生成日期：2026-09-07
> 范围：RDS 引擎与架构、Aurora、只读副本/多可用区、参数组/备份/快照、DynamoDB、ElastiCache、DocumentDB、Neptune（图）、Timestream（时序）、Keyspaces、MemoryDB、Redshift、QLDB、DMS/SCT、选型与一致性、与 GCP 对照
> 用法：伟伟每次过 **2 道**，我逐题完整批改/讲解（①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点）。
> 铁律：批改必须完整展开五板块；答完即停，不预告不催。每批改完立即写入 storage/aws-database-study/NOTES_ZH.md 并推 GitHub（不丢批改正文）。
> 回答任何点必须先查 AWS/GCP 官方文档核实，不确定标注；"旧缺点"须查最新文档验证是否仍成立。

---

## 一、RDS 基础与架构

**Q1.** Amazon RDS 是什么？它支持哪些数据库引擎（MySQL/PostgreSQL/MariaDB/Oracle/SQL Server/Aurora）？RDS 帮你托管了什么、你还要自己管什么（对比自建 EC2 上装数据库）？

**Q2.** RDS 的 Multi-AZ（多可用区）部署是什么？它是同步复制还是异步？故障时怎么切换？Multi-AZ 提供的是"高可用"还是"读扩展"？和只读副本有什么本质区别？

## 二、只读副本与扩展

**Q3.** RDS 只读副本（Read Replica）是什么？同步还是异步复制？能跨区域吗？主要解决什么问题？故障时能不能自动提升为主库？

**Q4.** Multi-AZ 和 Read Replica 能不能同时用？一个典型的"高可用 + 读扩展"生产架构怎么组合它们？跨区域只读副本对灾备（DR）有什么价值？

## 三、Aurora

**Q5.** Amazon Aurora 和普通 RDS MySQL/PostgreSQL 有什么本质区别？Aurora 的存储架构（6 副本跨 3 AZ、共享存储卷、日志即数据库 log-is-the-database）是怎么回事？

**Q6.** Aurora 的读副本和 RDS 只读副本有何不同（共享存储 vs 各自拷贝）？Aurora 故障切换为什么比 RDS 快？Aurora 副本最多几个？

**Q7.** 什么是 Aurora Serverless（v1/v2）？它怎么自动伸缩？适合什么场景（间歇负载/不确定负载）？ACU 是什么？

**Q8.** 什么是 Aurora Global Database？它和跨区域只读副本有什么区别？RPO/RTO 大概是什么量级？适合什么场景？

## 四、备份、快照、参数组、安全

**Q9.** RDS 的自动备份（automated backup）和手动快照（snapshot）有什么区别？备份保留期、PITR（时间点恢复）是怎么工作的？快照跨区域/跨账号能共享吗？

**Q10.** RDS 参数组（parameter group）和选项组（option group）是什么？static 和 dynamic 参数有什么区别（改了要不要重启）？

**Q11.** RDS 的存储类型有哪些（gp2/gp3/io1/io2/magnetic）？什么是 Provisioned IOPS？存储自动伸缩（storage autoscaling）是什么？

**Q12.** RDS 怎么做安全（VPC 子网组、SG、加密 at-rest/in-transit、IAM 数据库认证、Secrets Manager 集成）？加密能不能对已有实例开启？

## 五、DynamoDB（NoSQL 键值/文档）

**Q13.** DynamoDB 是什么类型的数据库？分区键（partition key）和排序键（sort key）是什么？它怎么做到"任意规模的个位数毫秒延迟"？

**Q14.** DynamoDB 的容量模式：预置（provisioned）vs 按需（on-demand）有什么区别？什么是 RCU/WCU？什么是热分区（hot partition）问题，怎么避免？

**Q15.** DynamoDB 的 GSI（全局二级索引）和 LSI（本地二级索引）有什么区别？各自的限制是什么？什么时候用哪个？

**Q16.** DynamoDB 的读一致性：最终一致 vs 强一致读有什么区别？什么是 DynamoDB Streams？什么是 DAX（DynamoDB Accelerator）？什么是全局表（Global Tables）？

## 六、缓存（ElastiCache / MemoryDB）

**Q17.** ElastiCache 是什么？Redis 和 Memcached 两种引擎有什么区别？各自适合什么场景？

**Q18.** ElastiCache Redis 的集群模式（cluster mode enabled/disabled）、副本、自动故障切换怎么工作？什么是 MemoryDB for Redis，和 ElastiCache Redis 有什么本质区别（持久化/一致性）？

## 七、DocumentDB / Keyspaces

**Q19.** Amazon DocumentDB 是什么（兼容 MongoDB）？它和 DynamoDB 都是 NoSQL，怎么选？DocumentDB 的架构像 Aurora 吗？

**Q20.** Amazon Keyspaces 是什么（兼容 Cassandra）？它是 serverless 吗？和 DynamoDB 的宽列模型有什么异同？

## 八、图数据库（Neptune）

**Q21.** Amazon Neptune 是什么？图数据库解决什么关系型/NoSQL 解决不好的问题（多跳关系查询）？它支持哪些查询语言/模型（Gremlin/openCypher/SPARQL，property graph vs RDF）？

**Q22.** 图数据库的典型场景（社交网络、推荐、欺诈检测、知识图谱）为什么用图比用关系型 JOIN 快？"多跳查询"在关系型里为什么代价高？

**Q23.** Neptune 的架构（是否像 Aurora 的共享存储 + 只读副本）？Neptune Serverless 是什么？Neptune Analytics 又是什么？

## 九、时序数据库（Timestream）

**Q24.** Amazon Timestream 是什么？时序数据（time-series）有什么特点？为什么需要专门的时序数据库而不是用 RDS？典型场景（IoT、监控指标、DevOps 遥测）？

**Q25.** Timestream 的存储分层（内存存储 memory store + 磁盘/磁性存储 magnetic store）是怎么回事？数据怎么从热层流到冷层？它的查询和计费模型有什么特点？

**Q26.** Timestream for LiveAnalytics 和 Timestream for InfluxDB 有什么区别？什么时候选托管 InfluxDB？

## 十、分析 / 账本 / 迁移 / 选型

**Q27.** Amazon Redshift 是什么（数据仓库/OLAP）？它和 RDS/Aurora（OLTP）有什么本质区别（列式存储、MPP 大规模并行）？什么时候该用 Redshift 而不是 Aurora？

**Q28.** OLTP 和 OLAP 有什么区别？行式存储 vs 列式存储各适合什么？一个公司又要交易又要分析，典型的数据架构怎么搭（OLTP 库 + ETL/CDC + 数据仓库/湖）？

**Q29.** AWS DMS（Database Migration Service）和 SCT（Schema Conversion Tool）是什么？同构迁移 vs 异构迁移有什么区别？CDC（变更数据捕获）在迁移里起什么作用？

**Q30.**（综合选型题）给出场景，选合适的 AWS 数据库并说理由：①电商订单交易；②海量用户会话/购物车（高并发低延迟KV）；③社交好友推荐/欺诈检测；④IoT 设备每秒百万级传感器读数；⑤全公司 BI 报表分析 PB 级数据；⑥需要兼容现有 MongoDB 应用；⑦需要不可篡改的审计账本。并给出每个的 GCP 等价服务。

---

## 附：AWS ↔ GCP 数据库对照速查（供批改时引用）

| 类别 | AWS | GCP |
|---|---|---|
| 关系型托管 | RDS (MySQL/PG/...) | Cloud SQL |
| 云原生关系型 | Aurora | AlloyDB (PG) / Cloud Spanner (全球分布式) |
| 全球强一致关系型 | Aurora Global DB(最终) | **Cloud Spanner**(全球强一致,独一档) |
| NoSQL KV/文档 | DynamoDB | Firestore / Datastore / Bigtable |
| 宽列 | Keyspaces(Cassandra) / DynamoDB | Bigtable |
| 缓存 | ElastiCache / MemoryDB | Memorystore |
| 文档(Mongo兼容) | DocumentDB | Firestore(非兼容) / 第三方 |
| 图 | Neptune | (无一线托管图, Spanner Graph 新增) |
| 时序 | Timestream | Bigtable+工具 / 第三方(无专门一线时序) |
| 数据仓库 OLAP | Redshift | BigQuery |
| 账本 | QLDB(注:已停新建) | (无直接对应) |
| 迁移 | DMS + SCT | Database Migration Service |

---

## 批改进度追踪
- [ ] Q1-Q2  [ ] Q3-Q4  [ ] Q5-Q6  [ ] Q7-Q8  [ ] Q9-Q10
- [ ] Q11-Q12  [ ] Q13-Q14  [ ] Q15-Q16  [ ] Q17-Q18  [ ] Q19-Q20
- [ ] Q21-Q22  [ ] Q23-Q24  [ ] Q25-Q26  [ ] Q27-Q28  [ ] Q29-Q30
