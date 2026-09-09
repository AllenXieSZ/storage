# AWS 大数据 & 分析 —— 20 题复习笔记（题干 + 作答 + 批改 + AWS↔GCP 对照）

> 覆盖 10 个模块：S3 数据湖 / Glue / Athena / Redshift / EMR / Kinesis / MSK / 编排 & Lake Formation / QuickSight & 联邦查询 / 格式 & 综合选型。
> 每题格式：题干 → 我的作答 → 五板块批改（逐点对照 / 参考答案+原理 / 概念深入 / AWS↔GCP 对照 / 评分+记忆点）。

---

## 第三模块：Athena 分析编排

### Q5（Athena 核心机制）

**题干**
1. Athena 是什么类型的服务？底层查询引擎是什么？说明查询 S3 数据的完整链路（元数据从哪来、数据怎么读）。
2. 计费模型有哪几种？
3. 作为架构师，降低 Athena 查询成本 + 提升性能的手段（至少 3 个）。

**我的作答**
Athena 查询 S3，元数据来自 catalog，计费模型按照扫描数据量。节省费用使用分区，提升性能也是分区。

**批改**
- 元数据来自 catalog ✅（Glue Data Catalog）；计费按扫描量 ✅ 但不完整；优化只答分区 ⚠️ 太单薄。
- **底层引擎**：Athena v2/v3 = **Trino（前身 Presto）**；另有 Athena for Apache Spark。**不是 DuckDB**。
- **查询链路**：提交 SQL → 查 Glue Data Catalog 拿 schema/S3 位置/格式/SerDe/分区 → Trino 引擎按 `s3://` 路径直接读 S3 数据文件（数据从不进 Glue）→ 过滤聚合 → 结果写到指定的 S3 query result location。
- **两种计费**：① 按扫描数据量（默认，$5/TB，需查最新定价）；② 预置算力 Provisioned Capacity（按 DPU 小时付费，适合高并发可预测负载）。
- **降本+提速手段**：① 列式格式 Parquet/ORC（最有效，只读需要列）② 压缩 ③ 分区（分区裁剪）④ 分区投影 Partition Projection ⑤ 合并小文件 ⑥ 只 SELECT 需要的列 ⑦ CTAS 转成分区 Parquet。
- **AWS↔GCP**：Athena（Trino，查 S3，存算彻底分离）↔ BigQuery（Dremel，自带托管存储）。BigQuery 同时对标 Athena + Redshift。
- **评分 5/10**。记忆点：Athena = serverless + Trino + 查 S3 + 按扫描量计费；优化铁三角 = 列式 + 压缩 + 分区（都为"少扫字节"）。

### Q6（Athena 进阶 / 联邦与编排）

**题干**
1. Athena 只能查 S3 吗？查 RDS/DynamoDB/CloudWatch 靠什么机制？
2. CTAS 和 INSERT INTO 典型用途？
3. 查询结果/并发/工作负载隔离怎么管理？
4. GCP 对标是什么？架构最大区别？

**我的作答**
Athena 怎么查 RDS、CloudWatch 放 S3 进行查询，GCP 对标 bigquery 里面组件。

**批改**
- "放 S3 再查" ❌ 概念混淆。正解 = **Athena Federated Query + 数据源连接器（Lambda connector）**，实时查 RDS/DynamoDB/CloudWatch，**免搬运**，可跨源 JOIN。
- **CTAS（CREATE TABLE AS SELECT）**：查询结果建新表并落 S3，典型用于格式转换（CSV→分区 Parquet）、ETL 物化。**INSERT INTO**：往已存在表追加增量数据。
- **Workgroup（工作组）**：工作负载隔离 + 成本控制（扫描量限额）+ 独立结果位置/加密 + 独立 CloudWatch 指标 + 引擎版本选择。
- **AWS↔GCP**：联邦查询 ↔ BigQuery 外部表/联邦；跨云查 ↔ BigQuery Omni。最大区别：Athena 存算彻底分离（自身不存数据），BigQuery 自带原生托管存储。
- **评分 3/10**。记忆点：Athena 查非 S3 = Federated Query + Lambda 连接器；CTAS = 转分区 Parquet 的 ETL 神器；Workgroup = 隔离 + 扫描限额。

---

## 第四模块：Redshift 深入

### Q7（架构与核心机制）

**题干**：Redshift 类型/架构（Leader+Compute）；行存还是列存及原因；Distribution Style 与 Sort Key；Provisioned vs Serverless。

**批改要点（教学，本题从零讲解）**
- **Redshift = 列式 MPP 云数仓，做 OLAP**。架构：**Leader Node**（指挥：解析/优化/分发/汇总，不存业务数据）+ **Compute Node**（并行存+算，内部再切 Slice）= MPP 大规模并行。
- **列式存储**三大好处：只读需要的列、压缩率高、向量化快。（OLTP 取整行用行存；OLAP 聚合用列存。）
- **Distribution Style**（数据分到哪个节点）：KEY（按 JOIN 列 hash，两大表 JOIN 免跨节点搬数据）/ ALL（小维度表每节点全副本）/ EVEN（轮询均匀）/ AUTO（默认）。选错 → JOIN 时数据重分布，慢十倍。
- **Sort Key**（节点内物理排序）：靠 Zone Map（每 1MB 块记 min/max）在范围查询时整块跳过无关数据。
- **Provisioned**（常驻集群，稳定重负载划算）vs **Serverless**（无集群按 RPU 秒计费，波动/间歇负载省心）。

### Q8（数据湖集成与扩展）

**题干**：Redshift Spectrum；RA3+RMS 架构变化；Concurrency Scaling；GCP 对标及本质区别。

**批改要点（教学）**
- **Spectrum**：Redshift 直接查 S3 数据湖（外部表 + Glue Catalog），可 JOIN 内部表 + S3 外部表 = Lake House。
- **RA3 + Managed Storage（RMS）**：从 DC2 的"存算耦合（本地 SSD）"变成"**存算分离**"（数据在 S3 支撑的托管层，节点本地 SSD 只做热缓存），按算力选节点、存储单独付费。
- **Concurrency Scaling**：并发排队时自动临时加集群容量分担，高峰过去释放；每天有免费额度。
- **AWS↔GCP**：Redshift（从有节点集群演进到存算分离，仍有节点/集群概念）↔ BigQuery（天生无节点 + 彻底存算分离 + 纯 serverless，slots 自动调度，理念更彻底）。

---

## 第五模块：EMR

### Q9（基础与架构）

**题干**：EMR 是什么/跑哪些框架；节点角色（Master/Core/Task）；三种部署形态；为什么数据放 S3 + EMRFS。

**我的作答**
EMR 只要 spark、flink、Hadoop，有 Master worker，EMR on EC2，HDFS 一般多个副本，而且还有 node，计算存储不分离。

**批改**
- 框架 ✅（可补 Hive/Presto/HBase）；HDFS 多副本 ✅（默认 3）；存算不分离 ✅（正是要 S3 解决的）。
- **节点角色（关键，你把 Core/Task 混成 worker）**：Master（指挥，1 或 HA 3）；**Core**（既算又存 HDFS 数据，不能乱删）；**Task**（只算不存数据，可随意增删，**Spot 弹性首选**）。
- **三形态**：EMR on EC2（控制力最强，可定制）；EMR on EKS（复用 K8s 资源池）；EMR Serverless（无集群，按用量，间歇负载）。
- **EMRFS + S3**：EMRFS 让 Hadoop/Spark 用 `s3://` 直接读写 S3 → **存算分离**（数据持久，集群用完即关）、多集群共享、成本低。HDFS 现多作临时/中间数据。
- **AWS↔GCP**：EMR ↔ **Dataproc**（不是 BigQuery！BigQuery 对标 Redshift/Athena）。
- **评分 5.5/10**。记忆点：三类节点 Master/Core/Task；数据放 S3 + EMRFS = 存算分离；GCP 对标 Dataproc。

### Q10（成本与选型）

**题干**：EMR 怎么省钱；EMR vs Glue；EMR vs Redshift；GCP 对标。

**我的作答**
EMR 使用 graviton EC2，EMR 可以定制化 ETL，EMR 半结构化、非结构化数据，redshift 处理格式化数据，GCP 对标 bigquery。

**批改**
- Graviton ✅（次要）；可定制 ETL ✅；EMR 非结构化 vs Redshift 结构化 ✅ 方向对；GCP 对标 ❌ 应是 Dataproc。
- **省钱最大头（你漏了）**：① **Task Node 用 Spot**（省 70-90%，不存数据无损）② **Transient 集群用完即关**（数据在 S3 不丢，不为闲置付费）③ Graviton ④ EMR Serverless ⑤ Managed Scaling。
- **EMR vs Glue**：EMR 托管集群、灵活可定制、多框架、重负载；Glue serverless、全托管省心、常规 ETL、深度集成 Glue Catalog。
- **EMR vs Redshift**：EMR = 通用分布式计算框架（写代码，处理任意数据）；Redshift = SQL 结构化数仓（分析建模数据）。
- **评分 5/10**。记忆点：省钱 = Spot + transient + Graviton + Serverless；EMR 灵活 / Glue 省心；EMR 通用计算 / Redshift SQL 数仓；GCP = Dataproc。

---

## 第六模块：Kinesis（实时流）

### Q11 / Q12（家族 + 对比，教学讲解）

**Kinesis = 实时数据传送带**，处理源源不断、要秒级处理的流数据（对比批处理"攒着晚上算"）。

**三兄弟（比喻）**
- **Data Streams**：裸传送带，自己写消费者（KCL/Lambda），数据保留（默认 24h，最长 365 天），**可重复读/多消费者/可回放**。灵活但要写代码。
- **Data Firehose**：全自动传送带，直送目的地（S3/Redshift/OpenSearch/Splunk/HTTP），全托管免代码，可挂 Lambda 转换 + 自动转 Parquet/ORC。近实时（缓冲几十秒~几分钟）。
- **Managed Service for Apache Flink**（原 Data Analytics）：传送带上的质检机器人，边流边算（滑动窗口/聚合/异常检测）。

**Shard（分片）** = 传送带轨道，吞吐（写 1MB/s、读 2MB/s per shard）+ 并发都靠加 shard；Partition Key 决定进哪条轨道并保证 key 内有序；On-Demand 模式自动扩缩。

**vs SQS**：Kinesis = 传送带（append-only 日志，可重复读、多消费者、有序）；SQS = 取件柜（取走即删、一对一、标准队列不保证顺序）。

**vs MSK（Kafka）**：Kinesis 全托管 AWS 自研（省心、新项目首选、深度集成 AWS）；MSK 托管开源 Kafka（已有 Kafka 迁移 / 需 Kafka 生态如 Connect / 团队熟 Kafka）。同"兼容开源为迁移，全新选原生"逻辑。

**AWS↔GCP**：Kinesis/SQS ≈ **Pub/Sub**；流计算 ≈ **Dataflow**；MSK ≈ Confluent Cloud（GCP 无原生托管 Kafka）。

**补充：Kafka/Kinesis 一条消息可被多消费者多次消费**
- 底层是 append-only 日志，读了不删，按 retention 保留。
- **Offset** = 消费者自己的书签，倒回即可重读（回放）。
- **不同 Consumer Group** 各读全量、互不影响（一条消息被多方消费）；**同组内**分摊 partition、只处理一次（并行提吞吐）。
- ⚠️ 只在 retention 期内可重复消费；过期真删。

---

## 第七模块：MSK（Managed Streaming for Apache Kafka）

### Q13（基础与架构）

**题干**：MSK 是什么/托管了什么；Kafka 核心概念；高可用不丢数据机制；Provisioned vs Serverless。

**我的作答**
MSK 自己运维高可用，运维多个 replica，存储几个副本，是不是 EBS，存储成本会不会高。zookeeper 需要运维一个集群，用 connector 整合上下游。

**批改**
- "自己运维" ⚠️ 说反了一半——MSK 是**帮你托管**（broker 部署/补丁/多 AZ/副本/监控）；自建 EC2 Kafka 才自己运维。
- 副本/EBS/存储成本追问 ✅ 很敏锐（见概念深入）；ZooKeeper 集群 ✅；connector ✅。
- **Kafka 概念**：Topic（消息分类=日志书）→ 切 **Partition**（有序 append-only 日志，有 offset）→ 分布在 **Broker**（服务器节点）上；Producer 写 / Consumer Group 读。
- **不丢数据**：Replica（副本，replication factor 常 3，Leader 读写 + Follower 同步，跨 AZ）+ **ISR**（同步副本集，leader 挂从 ISR 选新）+ **acks=all**（ISR 全确认才成功）+ min.insync.replicas。
- **存储成本（回答你的追问）**：Provisioned broker 存 EBS，实际存储 = 逻辑数据 × 副本数 × retention。降本用 **Tiered Storage**（冷数据下沉到低成本层，本地 EBS 只留热数据）。Kinesis 则全隐藏这些。
- **Provisioned**（自选 broker/EBS/副本，可调优）vs **Serverless**（自动扩缩，省心）。
- **评分 4.5/10**。记忆点：MSK = 托管开源 Kafka；Topic→Partition→Broker；不丢数据 = 多副本跨AZ + ISR + acks=all；存储成本 = 数据×副本×retention，用 Tiered Storage 降本。

### Q14（运维与选型）

**题干**：ZooKeeper 作用 + 为什么 KRaft 取代；MSK Connect + 能否触发 Lambda；MSK vs Kinesis 选型；GCP/开源对标。

**我的作答**
zookeeper 需要运维一个集群，用 connector 整合上下游。

**批改**
- **ZooKeeper**：Kafka 老版外挂的分布式协调集群，管 broker 成员/leader 选举/元数据。痛点：额外运维一套集群 + 元数据规模瓶颈。
- **KRaft（Kafka Raft）**：新版内置用 Raft 协议自管元数据，去掉 ZooKeeper → 少一套集群、支持百万级 partition、故障恢复更快。元数据由 **controller 角色**管理（可与 broker 合并或专用节点，都是 Kafka 自己的进程）。
- **MSK Connect**：托管 Kafka Connect，用现成 Source/Sink 连接器免代码整合上下游（Debezium CDC、S3、OpenSearch 等）；**MSK 可作 Lambda 事件源**（Event Source Mapping）无服务器消费。
- **选型**：有 Kafka 包袱/要 Connect 生态/团队熟 Kafka → MSK；轻装 + AWS 原生 + 深度集成 Lambda/Firehose/Flink → Kinesis。
- **AWS↔GCP**：GCP 无原生托管 Kafka（用 Confluent Cloud/自建 GKE）；原生流服务 Pub/Sub（非 Kafka）。
- **评分 4/10**。记忆点：ZooKeeper→KRaft（内置 Raft，去外挂集群，支持百万 partition）；MSK Connect 免代码整合 + 可作 Lambda 事件源；有 Kafka 生态选 MSK，轻装选 Kinesis。

**补充：ZooKeeper 会退出历史舞台吗**
- Kafka 语境：**是**。KIP-500 → KRaft；Kafka 4.0 完全移除 ZooKeeper。MSK 新集群走 KRaft。
- 作为独立项目：不会立刻消失（HBase/Hadoop 等存量还在用），但新系统主流从"外挂 ZooKeeper"转向"内置 Raft/etcd"（Kafka KRaft、K8s etcd、Consul/TiKV 等）。

---

## 第八模块：编排 & Lake Formation

### Q15（数据管道编排，教学讲解）

- **编排** = 指挥多步骤按序跑 + 处理依赖 + 失败重试 + 定时触发 + 告警。
- **Step Functions**：通用状态机（JSON/可视化，集成 200+ AWS 服务，serverless，内置 Retry/Catch，Standard/Express 两型）。AWS 原生工作流首选。
- **MWAA（托管 Airflow）**：Python 写 DAG，生态丰富，复杂管道/已用 Airflow；有常驻环境成本。
- **Glue Workflows**：Glue 内置轻量编排，只串 Glue 组件（Crawler→Job）。
- **定时+重试+告警设计**：EventBridge Scheduler（cron）→ 触发 Step Functions（Glue Crawler→Job→校验→加载 Redshift，每步 Retry + Catch）→ 失败 SNS 告警。
- **EventBridge**：事件总线，定时触发 + 事件驱动（S3 新文件→触发 Glue/Step Functions）+ 服务解耦。
- **AWS↔GCP**：Step Functions↔Workflows；MWAA↔Cloud Composer；EventBridge↔Eventarc/Cloud Scheduler。

### Q16（Lake Formation 数据湖治理，教学讲解）

- 痛点：光靠 IAM/S3 权限只能控到"S3 路径/对象"，**做不到表/列/行级**。
- **Lake Formation** = 数据湖集中细粒度权限治理，把"管 S3 路径"升级成"像数据库一样 GRANT 库/表/列/行"。
- 粒度：**数据库 → 表 → 列 → 行 → 单元格**，+ **LF-Tags**（标签化批量授权）。
- **AWS↔GCP**：Lake Formation ↔ **BigLake + Dataplex**；列级/行级安全 ↔ BigQuery policy tags + 行级安全策略。

**补充：Lake Formation 怎么实现细粒度权限（不是改写/拦截 SQL）**
- 机制 = **① 凭证发放（Credential Vending）+ ② 引擎侧过滤**。
- 用户 IAM **不直接持 S3 权限**；查询时 LF 校验权限后，发一张"只能读授权数据块"的短期临时凭证给引擎（Athena/Redshift/EMR），并把"允许的列/行/单元格规则"告诉引擎。
- 引擎用临时凭证读 S3，在**执行/扫描阶段物理剔除**无权的列和行，返回过滤后结果。**不重写用户 SQL**。
- 前提：引擎集成 LF + 数据注册到 LF + 收回用户直接 S3 权限，否则可被绕过。
- 官方原文："the analytical engine fetches the data from Amazon S3, and performs necessary filtering such as column, row, or cell filtering"。

---

## 第九模块：QuickSight & 联邦查询

### Q17（QuickSight BI 可视化）

**题干**：QuickSight 是什么/链路位置；SPICE；数据源；QuickSight Q/生成式 BI。

**我的作答**
quicksight BI 是可视化 dashboard，类似 tableau，可以接 S3 Athena，SPICE 是内存分片，缓存数据。

**批改**
- 类 Tableau ✅；接 S3/Athena ✅；SPICE 内存缓存 ✅ 方向很对。
- **位置**：链路最末端展示层。
- **SPICE**（Super-fast Parallel In-memory Calculation Engine）= 列式内存缓存。直连查询每次打后端（实时但慢+贵）；SPICE 预导入内存 → dashboard 秒开、不反复打后端省钱（多人访问尤其香），需定时刷新。
- **数据源**：Athena/Redshift/RDS/Aurora/S3/OpenSearch/Snowflake/Salesforce/Excel 等。
- **QuickSight Q / Amazon Q**：自然语言问数据 + 生成式 BI（对话生成/改仪表盘、自动摘要）。
- **AWS↔GCP**：QuickSight↔Looker/Looker Studio；SPICE↔BigQuery BI Engine。
- **评分 6.5/10**。记忆点：QuickSight = serverless BI（类 Tableau），展示层；SPICE = 列式内存缓存（秒开+省后端）；QuickSight Q = 自然语言问数据。

### Q18（联邦查询 & 整体串联）

**题干**：联邦查询本质 vs 先 ETL；Redshift 联邦查询能查什么；完整栈串联；GCP BI 对标。

**我的作答**
Athena federated query，这个不懂。

**批改（教学讲透）**
- **联邦查询本质 = 数据不动、查询去找数据**，一条 SQL 跨多源查/JOIN，实时、免搬运。vs ETL = "先搬到一处再查"（有延迟、要维护管道，但高频重查快）。
- **Athena 联邦查询**靠 Lambda 连接器查 RDS/DynamoDB/CloudWatch；**Redshift 联邦查询**直接查 RDS/Aurora 的 PostgreSQL/MySQL 实时数据（区别 Spectrum 查 S3）。
- **三条数据整合路**：联邦查询（不搬、偶发轻量）/ Zero-ETL（托管 CDC、近实时高频进 Redshift）/ 传统 ETL（手动管道、最灵活）。
- **完整栈**：数据产生 → Kinesis/MSK/DMS/Zero-ETL 采集 → S3 数据湖（Parquet+分区）→ Glue Catalog 编目 → Glue/EMR 处理 → Athena/Redshift 查询（含联邦/Spectrum）→ Step Functions/MWAA 编排（EventBridge 触发）→ Lake Formation 治理 → QuickSight 可视化。
- **AWS↔GCP BI**：QuickSight ↔ Looker/Looker Studio。
- **评分 0/10（未答）**。记忆点见上。

**补充：Zero-ETL**
- 定义：全托管集成，把 Aurora/RDS/DynamoDB 数据写入后数秒内自动同步到分析目标（Redshift/SageMaker/OpenSearch），无需自建 ETL 管道。
- 底层 = 读事务日志做 **CDC 增量**（非快照全搬），对源库负载小，近实时（<15s）。
- 集成类型：Aurora/RDS→Redshift、Aurora/RDS→SageMaker、DynamoDB→Redshift/OpenSearch、SaaS→Redshift（Glue Zero-ETL）。
- vs 联邦查询：Zero-ETL 复制数据、适合高频重分析；联邦查询不复制、适合偶发即席查。
- GCP 对标：Datastream → BigQuery。

---

## 第十模块：格式 & 综合选型

### Q19（列式格式与开放表格式）

**题干**：为什么用 Parquet/ORC；Parquet vs ORC；开放表格式（Iceberg/Hudi/Delta）多提供什么；AWS 对 Iceberg 的原生支持。

**我的作答**
parquet 压缩、列式查询快、节省空间；parquet 和 ORC 不知道；开放表格式就是 iceberg、hudi、delta，就是 ACID、time travel、开源；S3 Tables、Athena、EMR、Netflix 典型客户。

**批改**
- 列式压缩/快/省空间 ✅；开放表格式三家 + ACID + time travel + 开源 ✅（主干全对）；S3 Tables/Athena/EMR/Netflix ✅（加分，Iceberg 源自 Netflix）。
- **为什么列式**：只读需要列 + 高压缩 + 按扫描量计费省钱 + 内嵌统计（谓词下推）。CSV/JSON 又大又慢又贵。
- **Parquet vs ORC**：Parquet（Cloudera/Twitter，Spark 生态，云上主流首选）；ORC（Hortonworks，Hive 生态）。新项目默认 Parquet。
- **开放表格式补全能力**：ACID 事务 + 时间旅行 + **行级 UPDATE/DELETE/MERGE** + **Schema 演进** + 分区演进（Iceberg）。= 给"一堆 Parquet 文件"加元数据层，让数据湖有数据库级可靠性 = Lakehouse 基石。
- **AWS Iceberg 支持**：S3 Tables（托管 Iceberg，自动 compaction/快照清理）+ Athena/Glue/EMR/Redshift 全支持。Iceberg(Netflix)/Hudi(Uber,流式 upsert)/Delta(Databricks)。
- **AWS↔GCP**：Iceberg（S3 Tables）↔ BigLake Managed Tables（Iceberg）。
- **评分 7.5/10**。记忆点：列式=少扫字节=快且省；Parquet 偏 Spark/ORC 偏 Hive；开放表格式 = Parquet 之上加元数据层 → ACID+时间旅行+行级增删改+schema 演进；AWS 主推 Iceberg（S3 Tables）。

### Q20（综合选型场景题）

**题干**：三个场景选型。A：电商 T+1 离线报表（预算有限、低频）；B：IoT 每秒上报，实时监控大屏+秒级告警+历史分析；C：PB 级 S3，财务看金额列别人不看 + BI 给高管。

**我的作答**
场景 A：用 kinesis 放 S3 parquet，用 Athena 查询，接 quicksight。
场景 B：IoT 放 timestream + quicksight，冷热分层。
场景 C：放 S3，lake formation，Athena 查询，quicksight 展示。

**批改**
- **A**：主干对，但 T+1 离线**不该用 Kinesis**（实时流不对路）→ 应 DMS/Glue 批量导出 或 Firehose 缓冲落 S3；S3+Parquet+分区 ✅ + **Glue** 处理 + **Athena** 查（低频按需最省钱，别上 Redshift）+ QuickSight + EventBridge/Step Functions 编排。
- **B**：Timestream + 冷热分层 ✅ 但漏了采集和实时告警 → 完整：**IoT Core/Kinesis 采集 → Flink 实时算+SNS 秒级告警 → Timestream 时序存(冷热分层) → 大屏 QuickSight/Grafana → 同时 Firehose 分流落 S3 归档**。
- **C**：**完全正确** → S3 + **Lake Formation 列级权限**（财务角色可见 amount、其他排除）+ Glue Catalog + Athena/Spectrum + QuickSight（遵守 LF 权限）。
- **选型三问**：实时还是离线？查询频率高不高？要不要细粒度权限？
- **评分 6.5/10**。记忆点：A=S3+Glue+Athena+QuickSight（serverless 省钱）；B=IoT Core/Kinesis+Flink 告警+Timestream+落 S3 归档；C=Lake Formation 列级权限。

---

## 一句话全栈串联

数据产生 → **Kinesis/MSK/DMS/Zero-ETL** 采集 → **S3**（Parquet 列式 + 分区，或 **Iceberg** 开放表格式）存储 → **Glue Data Catalog** 编目 → **Glue/EMR** 处理 → **Athena/Redshift** 查询（+ 联邦查询跨源 + Spectrum 查 S3）→ **Step Functions/MWAA + EventBridge** 编排调度 → **Lake Formation** 细粒度治理 → **QuickSight** 可视化。

## AWS ↔ GCP 全栈对照速查

| 环节 | AWS | GCP |
|---|---|---|
| 采集入流 | Kinesis / MSK | Pub/Sub |
| 数据湖存储 | S3 | GCS |
| 元数据目录 | Glue Data Catalog | Dataplex / Data Catalog |
| 处理 ETL | Glue / EMR | Dataflow / Dataproc |
| 查询/数仓 | Athena / Redshift | BigQuery |
| 编排 | Step Functions / MWAA | Workflows / Cloud Composer |
| 治理权限 | Lake Formation | BigLake / Dataplex |
| BI 可视化 | QuickSight | Looker / Looker Studio |
| 托管 Kafka | MSK | Confluent Cloud（无原生） |
| 近实时同步 | Zero-ETL | Datastream → BigQuery |
