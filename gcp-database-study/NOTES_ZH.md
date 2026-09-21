# GCP 数据库 —— 批改归档（NOTES）

> 每批改完一组（2 题）立即追加到此文件并推 GitHub，保留完整五板块批改正文。
> 题库见 `QA_ZH.md`（10 模块 20 题）。

---

## 批次 2 · 第二模块 Cloud SQL 高可用与扩展 · Q3/Q4（2026-09-15）

### Q3 高可用 HA — 评分 2.5/10

**小帅作答**：高可用是通过 regional persistent disk 实现数据复制，提供的是读扩展，需要手动切换。

**逐点对照**
- ✅ 底层是 regional persistent disk —— 对（半对，加分项）
- ❌ 说 HA "提供读扩展" —— 错。HA 提供可用性；standby 实例**不可读**。读扩展是只读副本的活。
- ❌ 说 "需要手动切换" —— 错。failover 全自动（心跳每秒检测，多次丢失自动切）。手动 failover/failback 只是可选运维操作。

**参考答案要点**
1. HA = 区域级实例：同 region 内 主zone(primary)+从zone(standby)。同步复制到两 zone 的 regional persistent disk —— 每笔写要两 zone 都落盘才 commit（RPO≈0）。
2. 自动 failover；primary/standby **共享同一静态 IP**，切换后连接地址不变；RTO 几十秒级。failover 后不自动切回，想切回做 failback。
3. HA 是**跨 zone（同 region）不是跨 region**。跨 region 容灾靠 cross-region read replica + promote。
4. HA=高可用（管活着），standby 不可读不可写；只读副本=读扩展（可读，不自动接管写）。本质区别：同步 vs 异步、可用性 vs 性能扩展。

**概念深入**：同步(HA,RPO0,写延迟略高) vs 异步(副本,有 lag,RPO>0)；共享静态 IP 是 failover 对应用透明的核心；新版 HA 的 standby 不可读（区别于 legacy HA）。

**GCP↔AWS**：Cloud SQL HA ≈ RDS Multi-AZ。都同步+自动failover+备节点不可读（Multi-AZ instance）。差异：GCP 共享 IP 漂移 vs AWS DNS endpoint 切换；AWS Multi-AZ DB Cluster 的 reader 可读、RTO 更短(<35s)。

**记忆点**：HA = 同region跨zone + 同步复制(regional PD) + 自动failover(共享IP,地址不变) + standby不可读 + RPO≈0/RTO几十秒。HA管"活着"，不管"读得快"。

---

### Q4 只读副本与读扩展 — 评分 5/10

**小帅作答**：只读副本是异步复制，可以手动 promote，cascading replica 是外部副本。一个 primary + 读扩展。

**逐点对照**
- ✅ 只读副本异步复制 —— 对
- ✅ 可手动 promote —— 对
- ❌ "cascading replica 是外部副本" —— 错。级联副本 ≠ 外部副本，两个独立概念。
- △ "一主+读扩展" —— 方向对但架构题没展开。

**参考答案要点**
1. 只读副本 = primary 的只读拷贝，异步复制（有 lag），分摊读/分析流量 = 读扩展。
2. 能跨 region（cross-region read replica：就近读/DR/迁移）；能 promote 成独立主实例（不可逆）。
3. **级联副本 cascading** = 副本的副本（primary→副本A→副本B），减 primary 复制分发压力，都在 Cloud SQL 内。**外部副本 external / 从外部源复制** = 跨 Cloud SQL 边界：external read replica，或源库在外部(本地自建)、Cloud SQL 作副本从它复制（上云迁移，配 source representation instance）。两者完全不同，别混。
4. 生产架构 = HA(primary+standby 同步,保可用) + 多个只读副本(异步,分散不同zone,保读扩展) + 跨region只读副本(就近读+DR,可promote)；应用做读写分离(写→primary共享IP，读→副本，副本挂回退primary)。

**概念深入**：异步→复制延迟→读一致性（读己之写要读 primary）；可给只读副本自身开 HA；promote 不可逆。

**GCP↔AWS**：读副本≈RDS读副本(异步/可promote/可跨region)；级联≈RDS read replica of read replica；从外部源复制≈RDS原生复制/DMS CDC。GCP 无 Aurora Reader Endpoint，读写分离要应用自己做。

**记忆点**：只读副本=异步+只读+分摊读+可跨region+可promote(不可逆)。级联=副本的副本(云内副本链)；外部=跨云边界(外部库/迁移,配source representation instance)。生产=HA(同步保可用)+多zone只读副本(异步保读扩展)+跨region副本(就近读+DR)。

---

## 批次 5 · 第五模块 Bigtable · Q9/Q10（2026-09-20）

### Q9 Bigtable 是什么/数据模型 — 评分 5.5/10

**小帅作答**：Bigtable 是宽列 NoSQL，适合海量数据查询，row key 是数据存储排序机制，是最终一致性。

**逐点对照**
- ✅ 宽列 NoSQL —— 对
- ⚠️ "适合海量数据查询" —— 用词危险。强项是低延迟点查+高吞吐读写+按 row key 前缀范围扫描；无二级索引、不能按非key列过滤。别和 BigQuery 分析查询混。
- ✅ row key 是存储排序机制 —— 对（表按 row key 字典序排序），但没展开为什么是性能命门。
- ⚠️ "最终一致性" —— 不完整。单集群强一致(read-your-writes)；只有多集群复制后集群间才最终一致。漏了单集群强一致。
- ❌ 数据模型(row key/CF/qualifier/带版本cell) —— 漏答。

**参考答案要点**
1. 稀疏宽列 NoSQL，十亿行×千列，TB~PB；低延迟单键读写高吞吐；HBase Java 客户端兼容。场景：时序/IoT/金融/营销/图/MapReduce。value≤10MB。
2. 数据模型四层：Row(按row key字典序排序,唯一索引) → Column Family(建表定义,GC/权限/存储单位) → Column Qualifier(动态无限列) → Cell(row×col交叉,多个带timestamp版本)。表稀疏,空列不占空间。列由 `列族:列限定符` 标识。
3. row key 是唯一索引+决定数据落哪个 tablet/节点+决定范围扫描效率。单调递增(时间戳打头/自增ID)→新写全落尾部同一tablet同一节点→热点。打散：字段反转(设备ID#时间戳)、加盐/哈希前缀(hash%N#key)、时间戳反转(取最新)。
4. 单集群强一致；多集群复制最终一致(官方 eventual)；每集群都是primary都能读写；app profile 单集群路由可换强一致。

**概念深入**：tablet/split(按row key排序切块,一节点服务一批tablet,自动分裂均衡)；存算分离(数据在Colossus,节点无状态,resize无停机)；单集群强一致因single-writer-per-tablet。

**GCP↔AWS**：Bigtable ≈ DynamoDB(低延迟高吞吐NoSQL)/ Keyspaces(宽列Cassandra,数据模型更近)。⚠️ 不是Redshift！Redshift 对标 BigQuery。Bigtable无二级索引(DynamoDB有GSI/LSI)。时序另有 Timestream。

**记忆点**：稀疏宽列NoSQL，按row key字典序排序，`列族:列限定符→带版本cell`；单集群强一致/多集群最终一致；单调递增row key会热点，加盐/哈希前缀/字段反转打散；≈DynamoDB不是Redshift。

---

### Q10 Bigtable 运维与选型 — 评分 3/10

**小帅作答**：扩展单位是 node，对标 redshift，复制是类似 MySQL Replication。

**逐点对照**
- ✅ 扩展单位是 node —— 对，但没答存算分离/resize无停机/autoscaling。
- ❌ 对标 Redshift —— 错。Bigtable 对标 DynamoDB/Keyspaces；Redshift 对标 BigQuery。
- ⚠️ 复制类似 MySQL Replication —— 有本质偏差。Bigtable 多主(每集群都是primary能读写)，MySQL经典是单主多从(从只读)。
- ❌ 多集群路由/Bigtable vs BigQuery选型/HBase关系 —— 漏答。

**参考答案要点**
1. 扩展单位=node。存算分离：数据在Colossus,节点无状态只做服务/路由。加减节点无需搬数据、无停机(resize后几分钟均衡)。Autoscaling按CPU/存储利用率自动增减节点(设目标+上下限)。
2. 加cluster即自动开复制(无需手动配replica)；一instance跨最多8 region、每zone一cluster。多主:每集群primary都能读写,集群间异步最终一致。App profile: multi-cluster routing(路由最近/可用,自动failover=高可用就近读)；single-cluster routing(固定集群=工作负载隔离+强一致)。
3. Bigtable vs BigQuery：Bigtable=低延迟点查/高吞吐读写(毫秒,按row key)；BigQuery=大规模分析扫描/聚合(SQL任意字段,秒~分)。低延迟高并发点查→Bigtable；分析型SQL扫全表→BigQuery。常组合:Bigtable存实时+管道喂BigQuery分析。
4. 对标 DynamoDB/Keyspaces(不是Redshift)。HBase关系：2006 Google Bigtable论文启发了开源Apache HBase；Bigtable提供HBase兼容Java API,自建HBase可低成本迁入并接Hadoop生态;自建HBase有规模瓶颈,Bigtable托管消除。

**概念深入**：resize无停机根子=存算分离(MySQL加从库要搬数据,Bigtable只重分配tablet服务权)；App Profile=定义连接/路由/一致性的配置对象,同instance多profile做隔离；多主的一致性代价(CAP)：多活换最终一致,强一致用single-cluster routing。

**GCP↔AWS**：Bigtable≈DynamoDB/Keyspaces；扩展 node(存算分离) vs DynamoDB按需/预置+AutoScaling(无节点概念更serverless)；多集群多活≈DynamoDB Global Tables(最终一致)；HBase兼容 vs EMR自建HBase。⚠️ Bigtable≠BigQuery，BigQuery才对标Redshift。

**记忆点**：加/减node无停机(存算分离,数据在Colossus)+autoscaling按CPU；加cluster自动多活、每集群primary(多主)、集群间最终一致，app profile做multi-cluster(高可用就近)/single-cluster(隔离+强一致)路由；低延迟点查用Bigtable,分析扫描用BigQuery；对标DynamoDB(不是Redshift),是HBase鼻祖且兼容HBase API。

---

## 批次 7 · 第七模块 Memorystore（缓存）· Q13/Q14（2026-09-20）

### Q13 Memorystore 基础 — 评分 5/10

**小帅作答**：memorystore是托管的Redis memcached，使用哨兵模式做高可用，存储热门kv数据，事务性要求不严格，Redis是单线程，支持数据类别多。

**逐点对照**
- ✅ 托管 Redis/Memcached —— 对（漏 Valkey，现在是第三引擎）
- ❌ HA=哨兵模式 —— 错。Memorystore 不用 Redis Sentinel；用 GCP 托管控制面健康检测+自动 failover，底层主从异步复制。Sentinel 是自建 Redis 的 HA 方案，托管服务不暴露。
- ✅ 存热门 KV、事务性弱 —— 对（缓存定位）
- ✅ Redis 单线程 —— 对（命令单线程；6.0+ 仅网络I/O多线程）
- ✅ 数据类型多 —— 对
- 漏答 Q13.2(Basic vs Standard tier)、Q13.3(用途/减DB压力原理)

**参考答案要点**
1. 三引擎：Redis(数据结构丰富/持久化/复制)、Memcached(多线程纯KV/无持久化)、Valkey(Redis改闭源后Linux基金会fork，协议兼容)。内存存储=微秒级，做热数据缓存层。
2. HA：Basic tier单节点无副本无HA(挂了丢全部数据)；Standard tier跨zone主从+自动failover，异步复制(RPO>0可容忍)，endpoint不变，可选1-5读副本兼读扩展。
3. 用途：缓存/会话/排行榜(ZSet)/限流(INCR+EXPIRE)/发布订阅/分布式锁。减DB压力=读先查缓存,hit直接返内存,miss才回源,命中率90%则DB只扛10%读。
4. Redis(命令单线程原子无锁/数据结构多/持久化/HA) vs Memcached(多线程吃满多核/纯KV/无持久化)。

**概念深入**：异步复制RPO>0 —— 缓存可容忍(能从DB重建)，对比Cloud SQL HA同步复制RPO≈0(权威数据不能丢)。取舍逻辑:权威数据同步保RPO;缓存异步保低延迟。

**GCP↔AWS**：Memorystore Redis/Memcached/Valkey ≈ ElastiCache Redis/Memcached/Valkey。Standard tier跨zone HA ≈ ElastiCache Multi-AZ+Auto-Failover。Basic tier ≈ 单节点无副本组。

**记忆点**：Memorystore=托管Redis/Memcached/Valkey。HA=Standard tier跨zone主从异步复制+托管控制面自动failover(不是Sentinel!);Basic单节点无HA丢数据。Redis命令单线程(原子无锁)数据结构丰富;Memcached多线程纯KV。

---

### Q14 Memorystore 进阶与对比 — 评分 4.5/10

**小帅作答**：Redis cluster支持分片是数据分片。穿透使用布隆过滤，雪崩使用不定期时效，击穿使用什么，cache sides和write back，防止击穿，对标ElastiCache，memoryDB没有AWS对应的前端。

**逐点对照**
- ✅ Cluster=数据分片 —— 对(太简略,没讲vs单节点/主从)
- ✅ 穿透→布隆过滤器 —— 对
- ✅ 雪崩→TTL随机化("不定期时效") —— 对
- ❌ 击穿→"使用什么" —— 没答。解法=互斥锁/逻辑过期/热点永不过期
- ⚠️ cache-aside/write-back —— 名词对但没展开
- ❌ "防止击穿" —— 张冠李戴,写策略≠防击穿手段
- ✅ 对标 ElastiCache —— 对
- ⚠️ "MemoryDB没有AWS对应的前端" —— 表述乱,应为"MemoryDB是AWS独有,GCP无等价物"

**参考答案要点**
1. 单节点(受单节点内存/单核限)；主从=复制(每节点全量,扩读+HA,写和总容量仍受单主限)；Cluster=分片(16384哈希槽CRC16(key)%16384分散到多shard,扩写+扩容量)。一句话:主从=复制扩读;Cluster=分片扩写。
2. 穿透=查不存在的key(DB也没有,一直miss)→布隆/缓存空值/参数校验;击穿=单热点key过期瞬间并发打爆(DB有数据)→互斥锁/逻辑过期/永不过期;雪崩=大量key同时失效或缓存挂→TTL加随机+高可用+限流降级。
3. Cache-aside(应用管:读miss查DB写回缓存,写=更新DB删缓存,缓存挂不影响DB);write-through(同步写缓存+DB,强一致但慢);write-back(只写缓存异步刷DB,极快但缓存挂丢数据)。三者是写策略,不是防击穿。
4. 对标ElastiCache(含Cluster mode enabled)。MemoryDB=AWS独有的持久化+强一致+多AZ事务日志Redis主库(durable,RPO0),GCP无等价物。

**概念深入**：ElastiCache(缓存,异步复制可丢,挂了从DB重建) vs MemoryDB(主数据库,写先落多AZ事务日志再返回,RPO0强一致,Redis当权威存储)。GCP无MemoryDB等价物。

**GCP↔AWS**：Memorystore Redis Cluster≈ElastiCache Cluster mode enabled;持久化强一致Redis主库=AWS MemoryDB(GCP无对应)。

**记忆点**：Cluster=16384哈希槽分片(扩写+扩容量),主从=复制(扩读)。穿透(查不存在→布隆/空值)/击穿(单热点key过期→互斥锁/逻辑过期)/雪崩(大量key同时失效→TTL加随机)。写策略:cache-aside/write-through/write-back(会丢)。MemoryDB=AWS独有持久化Redis主库,GCP无对应。

---

## 批次 9 · 第九模块 迁移 & 复制 · Q17/Q18（2026-09-21）

### Q17 Database Migration Service — 评分 6/10

**小帅作答**：DMS支持on premise rdbms到cloud rds实时传播,使用cdc,最小切换停机是source只读,然后追平,然后切换读写。

**逐点对照**
- ✅ 本地RDBMS→云托管库迁移 —— 方向对(但"cloud rds"是AWS术语,GCP目标是Cloud SQL/AlloyDB)
- ✅ 用CDC —— 对
- ✅ 最小停机:source只读→追平→切读写 —— 答得好,抓住cutover核心
- ❌ 同构/异构区分 —— 没答
- ❌ 异构schema转换工具 —— 没答
- ❌ 对标AWS DMS/SCT —— 没答

**参考答案要点**
1. DMS=托管迁移,管初始快照+持续CDC复制,目标Cloud SQL(MySQL/PG/SQL Server)/AlloyDB。术语纠正:GCP是Cloud SQL不是RDS。
2. 同构(同引擎,简单)vs异构(跨引擎如Oracle→PG,需schema/类型/方言转换)。异构转换工具:DMS内置+Ora2Pg,对标AWS SCT。
3. cutover:①全量快照②CDC持续读binlog/WAL/redo追平③source停写只读→残余同步完→应用切目标读写。停机窗口仅几秒。
4. GCP DMS≈AWS DMS;异构转换≈AWS SCT。

**概念深入**：CDC最小停机本质=把全量和增量分开,全量慢搬(源库照常读写),靠读日志追上全量期间变更,只有冻结残余增量那一瞬需停写。

**GCP↔AWS**：DMS≈AWS DMS;schema转换≈SCT;目标Cloud SQL/AlloyDB≈RDS/Aurora。

**记忆点**：DMS=托管迁移到Cloud SQL/AlloyDB。同构(同引擎)vs异构(跨引擎需schema转换,对标SCT)。最小停机=全量快照+CDC追平→source只读冻结残余→切目标读写。DMS≈AWS DMS。

---

### Q18 Datastream 与实时复制 — 评分 4/10

**小帅作答**：Datastream对标Zero-ETL,是大数据从GCS到数仓的数据迁移。

**逐点对照**
- ✅ 对标Zero-ETL —— 对(一半,还对标AWS DMS CDC)
- ❌ "从GCS到数仓" —— 数据流向答反!Datastream从OLTP库(MySQL/PG/Oracle/SQL Server/MongoDB)捕获变更→写BigQuery/GCS。GCS是目标不是源。
- ❌ serverless CDC本质 —— 没点明
- ❌ 源数据库 —— 没答
- ❌ →BigQuery典型架构+为什么 —— 没答
- ❌ CDC读日志原理 —— 没答

**参考答案要点**
1. Datastream=serverless CDC复制服务。源=OLTP库(MySQL/PG含AlloyDB/Oracle/SQL Server/MongoDB/Spanner+Salesforce/ServiceNow应用源);目标=BigQuery(主打)/GCS/(配Dataflow→Cloud SQL/Spanner)。流向:OLTP库→BigQuery/GCS,不是GCS→数仓。
2. 架构:源OLTP库→Datastream实时捕获→写BigQuery(近实时)。为什么:OLTP不擅长分析扫描,直接查生产库拖垮线上;同步到BigQuery(OLAP)做分析不影响生产,实现近实时分析而非T+1。
3. CDC=读事务日志(MySQL binlog/PG WAL/Oracle redo)拿INSERT/UPDATE/DELETE。比全量导出好:低延迟(变更即捕获)、低开销(只传增量)、不丢中间变更(全量只看最终态)、不压源库。
4. 对标AWS DMS CDC + Zero-ETL(如Aurora→Redshift zero-ETL)。

**概念深入**：DMS vs Datastream:DMS面向一次性迁移(搬完切换收工);Datastream面向持续实时复制(长期把OLTP变更喂BigQuery做分析)。都用CDC但目的不同:搬家vs长期同步。

**GCP↔AWS**：Datastream(serverless CDC)≈AWS DMS CDC模式;Datastream→BigQuery≈Aurora/RDS→Redshift Zero-ETL。

**记忆点**：Datastream=serverless CDC,从OLTP库(MySQL/PG/Oracle/SQL Server/MongoDB)捕获变更→实时喂BigQuery/GCS(近实时分析不压生产库)。CDC=读binlog/WAL/redo拿增量,比全量导出低延迟/低开销/不丢变更。对标AWS DMS CDC+Zero-ETL。DMS=搬家一次性,Datastream=长期实时同步。
