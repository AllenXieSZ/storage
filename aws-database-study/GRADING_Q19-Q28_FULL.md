# AWS 数据库面试题 Q19–Q28 完整批改

> 09-08~09-09 聊天出题，逐题五板块完整展开：①逐点对照 ②完整参考答案+原理详解 ③概念深入 ④AWS↔GCP对照 ⑤评分+记忆点。
> 覆盖服务：DocumentDB / Keyspaces / Neptune / Timestream / ElastiCache / MemoryDB / Redshift / Athena / DMS / RDS Proxy。

---

# 第七模块：DocumentDB / Keyspaces

## Q19. Amazon DocumentDB

**题干**：DocumentDB 是什么？兼容什么数据库、是文档库吗？架构像不像 Aurora？和 DynamoDB 都是 NoSQL 怎么选？什么场景选 DocumentDB？

**小帅作答**："documentdb 兼容 MongoDB，是文档数据库，架构不知道。如果是简单 kv、没有复杂 filter、需要极致性能就 dynamodb。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 兼容什么 | 兼容 MongoDB ✅ | 正确 |
| 是不是文档库 | 是文档数据库 ✅ | 正确 |
| 架构 | "不知道" | 缺失（本题核心） |
| vs DynamoDB 怎么选 | 简单KV/无复杂filter/极致性能→DynamoDB ✅ | 方向对，但只答了一半（没说何时选 DocumentDB） |

### ② 完整参考答案 + 原理详解
DocumentDB 是 AWS 全托管、**兼容 MongoDB API** 的**文档数据库**（存 JSON/BSON）。可用原 MongoDB 应用代码/驱动/工具直连。官方兼容 MongoDB 3.6/4.0/5.0/8.0。

**架构（核心）——和 Aurora 几乎一模一样，是"Aurora 家族"的文档版**，核心是**计算存储分离**：
1. **Cluster Volume（共享存储卷）**：云原生分布式存储层，数据**跨 3 个 AZ 复制 6 份**（每 AZ 2 份），一个 cluster 只有一个 cluster volume，所有实例共享，容量自动增长最高 256 TiB（8.0）。
2. **Instances（计算实例）**：只负责算力，本身不存数据。**1 个 Primary**（唯一能写）+ **最多 15 个 Replica**（只读，分摊读负载/提可用性）；一个 cluster 0–16 个实例。

**为什么重要**：存储计算解耦→加读副本不复制数据（副本直接挂共享卷读）→副本创建快、故障切换快。写只走 Primary（单写点），读可横扩到 15 副本→读扩展强、写扩展受单 Primary 限制。

**vs DynamoDB 选型**：
| 维度 | DocumentDB | DynamoDB |
|---|---|---|
| 数据模型 | 文档(JSON/BSON)嵌套丰富 | 键值/宽表 |
| 查询能力 | 强(复杂查询/二级索引/聚合管道) | 弱(主键/GSI取数,复杂filter要scan) |
| 扩展性 | 读靠副本,写受单Primary限,256TiB | 近乎无限水平扩展,千万级QPS |
| 运维 | 选实例规格(provisioned) | serverless |
| 选它理由 | 已有MongoDB应用迁云/文档模型+复杂查询 | 云原生新建/极致规模/简单访问/免运维 |

**场景**：内容管理、用户画像、目录、灵活schema+复杂查询；尤其"本来用MongoDB想上AWS托管又不想改代码"。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 兼容MongoDB托管文档库 | DocumentDB | 无原生MongoDB兼容(靠Marketplace的MongoDB Atlas第三方) |
| 自家文档库 | — | Firestore(serverless,实时同步,更像文档版DynamoDB,非MongoDB兼容) |

⚠️ Firestore 虽是文档库但更接近 DynamoDB；GCP 无真正等价 DocumentDB(MongoDB兼容)的一方服务，想跑MongoDB兼容负载通常用Atlas。

### ⑤ 评分 + 记忆点
**6.5/10**。**DocumentDB = "MongoDB 版的 Aurora"**——兼容MongoDB API的文档库,架构=计算存储分离+6副本3AZ共享卷+1写15读。选它为迁移已有MongoDB/复杂文档查询;选DynamoDB为云原生+极致规模+简单访问+免运维。

---

## Q20. Amazon Keyspaces

**题干**：Keyspaces 是什么？兼容什么？是 serverless 吗要不要管节点？和 DynamoDB 都是宽列，数据模型异同？什么场景选它而非 DynamoDB？

**小帅作答**："keyspaces，不知道，兼容 Cassandra 就是写性能很快宽列数据库。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 兼容什么 | 兼容Cassandra ✅ | 正确 |
| 类型 | 宽列数据库 ✅ | 正确 |
| "写性能很快" | 部分对 | Cassandra写优化著称，但非Keyspaces核心卖点 |
| serverless? | 未答 | 缺失(核心) |
| 数据模型异同 | 未答 | 缺失 |
| 何时选 | 未答 | 缺失 |

### ② 完整参考答案 + 原理详解
Keyspaces 是 AWS 全托管、**兼容 Apache Cassandra** 的**宽列数据库**，用 **CQL** 操作，可用原 Cassandra 代码/工具直连。

**是不是 serverless？——是（核心）**：官方原话 "Amazon Keyspaces is serverless"。不用 provision/patch/管理服务器；表随流量自动 scale up/down；只为用掉的资源付费；号称近乎无限吞吐和存储。

**对比自建 Cassandra**：自建是去中心化 P2P 节点集群，要自己部署节点、配 replication factor、gossip 调优、节点扩缩容+数据 rebalance、repair 修复、版本升级……运维极重。Keyspaces 把这套全隐藏，**底层无"节点"概念暴露**——这才是相对自建的最大意义（不是"写快"，写快是 Cassandra 引擎特性）。

**Cassandra vs DynamoDB 数据模型（核心）**：
| | Cassandra/Keyspaces | DynamoDB |
|---|---|---|
| 分区键 | Partition Key | Partition Key |
| 排序/聚簇 | Clustering Column(s)(可多列分层排序) | Sort Key(单个复合键) |
| 查询语言 | CQL(类SQL) | DynamoDB API/PartiQL |
| 多列聚簇 | 支持多个clustering column分层 | 只有1个sort key |

相同：都PK决定分片+分区内二级排序键、都水平扩展、都最终一致可选。不同：Cassandra clustering column可多列天然分层排序，表达力更灵活；CQL更像SQL。

**场景**：已有Cassandra负载/代码迁云不想改代码不想运维→Keyspaces；团队已有CQL技术栈;需Cassandra多clustering column分层模型。全新项目无Cassandra包袱→通常直接DynamoDB。**Keyspaces核心意义=兼容迁移,非新建首选。**

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 宽列NoSQL | Keyspaces(Cassandra兼容,serverless)/DynamoDB | Bigtable(自家宽列,HBase API兼容) |
| serverless程度 | Keyspaces全serverless | Bigtable要选节点数(可autoscaling,但有节点概念) |

关键：Keyspaces对标Cassandra;Bigtable对标HBase/BigTable血统,两者不互兼容。Bigtable仍要管节点非纯serverless。Google BigTable论文(2006)是所有宽列库共同祖先。

### ⑤ 评分 + 记忆点
**4/10**。**Keyspaces = "serverless 的托管 Cassandra"**——兼容Cassandra/CQL宽列库,核心卖点免运维(无节点概念)非"写快"。数据模型 Partition Key+Clustering Column(s)(可多列)vs DynamoDB PK+单Sort Key。选它主要迁移已有Cassandra;全新项目直接DynamoDB。GCP对应Bigtable(兼容HBase非Cassandra,仍要管节点)。

---

# 第八模块：Neptune / Timestream

## Q21. Amazon Neptune

**题干**：Neptune 是什么类型？支持哪些图查询语言？架构像不像 Aurora/DocumentDB？什么场景一定用图库而非关系库硬 JOIN？

**小帅作答**："Neptune 是图数据库，支持查询语言我不知道，架构不知道，用来做社交关系、知识图谱、欺诈检测。对应开源 neo4j。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 类型 | 图数据库 ✅ | 正确 |
| 查询语言 | "不知道" | 缺失 |
| 架构 | "不知道" | 缺失(核心) |
| 场景 | 社交/知识图谱/欺诈 ✅✅ | 官方原文点名的正是这几个 |
| 开源对应 | neo4j ✅ | 方向对(兼容openCypher) |

### ② 完整参考答案 + 原理详解
Neptune 是 AWS 全托管**图数据库**，存/查高度关联数据，能存数十亿关系、毫秒级图遍历。

**支持语言——两大模型三种语言**：
1. **属性图(Property Graph)**：**Gremlin**(TinkerPop) + **openCypher**(Neo4j的Cypher开源版)。同一属性图可同时用两种语言访问。
2. **RDF(W3C语义网模型)**：**SPARQL**。
完整答案：Gremlin/openCypher(属性图) + SPARQL(RDF)。neo4j 对应 openCypher 这支。

**架构（核心）——和 Aurora/DocumentDB 同构**：计算存储分离，一个 DB cluster =
1. Cluster Volume：数据跨多AZ复制,高持久,持续备份S3+PITR。
2. Primary DB Instance：唯一能写,每cluster一个。
3. Neptune Replica：连同一存储卷,只读,最多15个,跨AZ提可用+分摊读。

💡 主线：**Aurora(关系)/DocumentDB(文档)/Neptune(图)三者架构完全同构**=计算存储分离+共享cluster volume多AZ多副本+1主写+最多15只读。这是AWS"Aurora存储引擎"复用到不同数据模型的结果，一题架构套三服务。

**为什么用图库而非关系库JOIN**：关系库多跳关系查询会JOIN爆炸(3跳=3层自JOIN指数放大)。图库把关系存成边(edge),遍历=指针跳转,跳几跳几步,延迟稳定毫秒级与总数据量无关。场景：社交(共同好友/传播)、推荐、欺诈检测(关联团伙/资金环路)、知识图谱、网络拓扑、药物发现。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 托管图库 | Neptune(Gremlin/openCypher/SPARQL) | ⚠️无一等公民托管图库 |
| 补空缺 | — | Spanner Graph(较新,Spanner之上图能力,openCypher/GQL)/第三方Neo4j Aura |

关键：**图是GCP明显空缺**,AWS有专门Neptune,GCP长期无对等原生托管图库。Spanner Graph补空缺但是"关系库+图能力"非纯图引擎。

### ⑤ 评分 + 记忆点
**6/10**。**Neptune = "图版的 Aurora"**——架构同构(共享卷+1写15读+多AZ);语言记"两模型三语言"(属性图 Gremlin/openCypher,RDF SPARQL);场景=多跳关系查询(社交/推荐/欺诈/知识图谱)。GCP图是空缺(Spanner Graph或第三方Neo4j)。

---

## Q22. Amazon Timestream

**题干**：Timestream 是什么类型？时序数据特点、为什么不用普通关系库？存储分层怎样？什么场景用？

**小帅作答**："timestream 是时序数据库，数据顺序写入、很少更新、按时间范围查询、存储自动分层，IoT、监控指标。对应开源 influxdb。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 类型 | 时序数据库 ✅ | 正确 |
| 时序特点 | 顺序写/少更新/按时间范围查 ✅✅✅ | 答得很好 |
| 存储分层 | "自动分层" ✅ | 方向对，没说具体两层 |
| 场景 | IoT/监控指标 ✅✅ | 正确 |
| 开源对应 | influxdb ✅ | 正确(fluxdb应是InfluxDB笔误) |

### ② 完整参考答案 + 原理详解
Timestream 是 AWS 全托管、**serverless** 的**时序数据库**，为大规模采集/存储/处理时序数据设计。主推 Timestream for Live Analytics（还有 Timestream for InfluxDB 托管 InfluxDB 引擎）。

**时序数据特点/为什么不用关系库**：海量按时间追加写(append-only,只追加几乎不改历史)；按时间范围查询+聚合(降采样)；数据随时间变冷。关系库B-tree为随机读写+频繁更新优化,面对每秒百万级追加写会索引膨胀/写放大,且无原生时间分区/自动降冷/TTL。时序库为高速追加+时间范围扫描+自动生命周期优化。

**存储分层（补全两层）**：
1. **Memory Store（内存层）**：存近期热数据,为高吞吐写入+快速点查优化,新写入先进这里。
2. **Magnetic Store（磁性层）**：存历史冷数据,为快速分析查询优化,成本更低。
**自动分层**：数据先写memory store,按retention policy自动迁到magnetic store;只配两个保留期,超magnetic保留期自动删(TTL);查询跨两层透明(一条SQL引擎自动决定去哪层取数);serverless且写入/存储/查询三系统解耦独立伸缩。

**场景**：IoT传感器遥测、监控metrics、DevOps遥测/APM、工业设备/车联网信号。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 专用时序库 | Timestream(Live Analytics + for InfluxDB) | ⚠️无专门一等时序服务 |
| GCP存时序方案 | — | Bigtable(高写吞吐,时序主力)/BigQuery(大规模分析)/第三方InfluxDB |

关键：**GCP无专门命名的时序库**,官方推荐Bigtable存时序(宽列+高写吞吐+行键设计,OpenTSDB等就跑Bigtable/HBase),大规模分析用BigQuery。AWS走专用服务路线,GCP走通用大数据承载路线。

### ⑤ 评分 + 记忆点
**8/10**（答得最好）。**Timestream = serverless 时序库**,时序数据=海量追加写+少更新+时间范围查+随时间变冷。分层记两层：**Memory Store(热/快写快点查)→自动迁→Magnetic Store(冷/低成本分析)**,retention policy自动降冷+TTL删。场景IoT/metrics/遥测。开源对应InfluxDB(AWS有Timestream for InfluxDB)。GCP无专用时序库,用Bigtable/BigQuery承载。

---

# 第九模块：ElastiCache / MemoryDB

## Q23. Amazon ElastiCache + Redis/Memcached 选型

**题干**：ElastiCache 是什么/干什么？Redis vs Memcached 区别？Cache-Aside 和 Write-Through 怎么工作？你 OpenCart 项目用 ElastiCache Redis 做了什么？

**小帅作答**："ElastiCache 是内存数据库,减轻后台数据库压力,存里面数据不用持久也不用强事务数据比较简单。Redis 结构丰富、单线程、可以持久。Cache-aside 是存一份临时数据,读 miss 就访问后台数据库;write-through 每次都写后台数据库。购物可以用 Redis,秒杀商品可以用 Redis,高频交易可以用 Redis。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 是什么/干什么 | 内存缓存减DB压力 ✅ | 正确 |
| Redis特点 | 结构丰富✅单线程✅可持久✅ | 三点全对 |
| Memcached | 没提 | 缺失(本题要对比) |
| Cache-Aside | 存临时数据读miss访问DB ✅ | 基本对,漏"回填缓存" |
| Write-Through | "每次都写后台DB" ⚠️ | 不准确,漏核心"同时写缓存" |
| OpenCart实战 | 未提 | 缺失 |

### ② 完整参考答案 + 原理详解
ElastiCache 是 AWS 全托管内存缓存服务,省去自运维Redis/Memcached。典型挡在数据库前当缓存层,把热点放内存(微秒~个位数ms),可降DB负载80%+。

**Redis/Valkey vs Memcached（核心，你漏了Memcached）**：
| 维度 | Redis/Valkey | Memcached |
|---|---|---|
| 数据结构 | 丰富(string/hash/list/set/zset/stream/geo/bitmap) | 只简单KV |
| 线程 | 单线程(每节点,命令串行无锁) | 多线程(吃满多核,纯KV吞吐高) |
| 持久化 | 支持(RDB/AOF) | 不支持(重启全丢) |
| 复制/HA | 支持(主从/多AZ/故障切换/读副本) | 不支持复制 |
| 备份 | 支持 | 不支持 |
| 适用 | 需数据结构/持久/HA/复杂功能 | 纯简单缓存/极致多核/可丢 |

⚠️ 单线程不是缺点:命令原子无锁实现简单,单节点QPS依然极高(10万+)。**Redis功能全面(默认首选),Memcached只在极简缓存+榨多核窄场景才考虑。**

**两种缓存模式**：
- **Cache-Aside(旁路,最常用)**：应用自管缓存。读:先查缓存命中返回,miss→查DB→**写回缓存(回填)**→返回。写:更新DB→**删除/失效缓存**。你漏了"读miss回填"+"写时失效缓存"两步。特点:只存被读过的热数据;缓存挂了不影响正确性。
- **Write-Through(写透)**：**写时同时写缓存+写DB**。你只说了写DB那半,漏了写缓存(名字来源)。特点:读永命中(缓存总最新),但每写多一次缓存写→写延迟增加,且会缓存可能永不被读的数据(浪费内存)。对比Write-Behind(异步回写DB,快但可能丢)。

**OpenCart实战**（本题问你的项目）：①session从DB切Redis(带TTL,消除browse对DB的session写);②商品/配置缓存(getProduct/getOptions)=典型Cache-Aside;③购物车迁Redis Hash(带DB降级,Aurora购物车写归零)。点评:session和购物车其实是"Redis当轻量主存"而非纯缓存,靠ElastiCache+DB降级兜底Redis挂了丢数据的风险——引出Q24的MemoryDB(持久Redis)。你答的秒杀✅很对(原子操作+单线程无锁扣库存);"高频交易"要小心:金融级不能丢的交易纯ElastiCache不够,得MemoryDB。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 托管Redis | ElastiCache for Redis/Valkey | Memorystore for Redis |
| 托管Memcached | ElastiCache for Memcached | Memorystore for Memcached |
| 持久Redis主库 | MemoryDB(见Q24) | 无对等(Memorystore偏缓存) |

关键：ElastiCache↔Memorystore几乎一一对应(都支持Redis+Memcached)。唯一明显差异:AWS有MemoryDB(持久Redis当主库),GCP没有。

### ⑤ 评分 + 记忆点
**6/10**。**ElastiCache = 托管缓存挡DB前**。引擎:Redis/Valkey(结构丰富+持久+HA,默认首选)vs Memcached(纯简单KV+多线程,极简才用)。模式:Cache-Aside(应用自管,读miss回源+回填,写时失效);Write-Through(写时同时写缓存+DB,读永命中但写变慢)。OpenCart实战覆盖session/商品缓存/购物车。

---

## Q24. MemoryDB vs ElastiCache Redis

**题干**：MemoryDB 是什么？和 ElastiCache Redis 最本质区别？怎么做到持久+高可用？性能差异？什么场景选哪个？

**小帅作答**："MemoryDB for Redis 是 AWS 自研内存数据库,强事务,读快、写慢,可以做主库,前面放 ElastiCache。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 是什么 | AWS自研内存库 ✅ | 正确(兼容Valkey/Redis OSS) |
| 最本质区别 | "强事务" ⚠️ | 用词不准,应是持久性durability |
| 性能 | 读快写慢 ✅ | 完全正确(文档:微秒读/个位数ms写) |
| 能做主库 | 可以 ✅ | 正确 |
| 架构建议 | 前面放ElastiCache | 有想法,见点评 |

### ② 完整参考答案 + 原理详解
MemoryDB 是 AWS **持久化(durable)内存数据库**,兼容 Valkey/Redis OSS。官方定位:"既有内存性能又有多AZ持久性,可当高性能主数据库"。

**最本质区别 = 持久性 durability（纠正"强事务"）**：
- ⚠️ "强事务"不准。Redis本有MULTI/EXEC事务,但非MemoryDB卖点。**本质区别是durability(数据不丢)**：
  - ElastiCache for Redis=缓存:数据主要在内存,虽有快照/AOF但定位缓存,节点故障可能丢最近数据,需背后有真正数据库(如Aurora)作source of truth。
  - MemoryDB=持久主库:每次写先落多AZ事务日志才算成功,跨多AZ强持久,节点全挂不丢已确认的写,本身就能当唯一主数据库。
- 一句话:ElastiCache Redis是"缓存"(数据可丢,要配主库);MemoryDB是"持久Redis"(数据不丢,本身就是主库)。

**怎么持久+高可用（你没答）**：核心=**Multi-AZ Transaction Log(多AZ事务日志)**。每写:写内存+同步持久化到跨多AZ分布式事务日志,日志确认后才返回成功。日志用于:快速故障切换/数据库恢复/节点重启,节点挂了从日志恢复不丢数据。这也解释"写慢":写要等多AZ日志确认(个位数ms);"读快":读直接命中内存(微秒),不碰日志。

**性能（你答对，补量级）**：读微秒级;写个位数毫秒。对比ElastiCache读写都微秒~亚毫秒(不等持久化),所以纯写吞吐ElastiCache更快——这是持久性的代价。

**场景**：选MemoryDB(主库):数据不能丢+要内存性能+想省掉缓存和DB两套系统(微服务主存/持久会话/购物车/排行榜/金融级高频状态)。选ElastiCache(缓存):数据可丢/可重建,背后已有主库,只加速读降DB压力。

**点评"MemoryDB主库前放ElastiCache"**：技术可行但通常没必要甚至反模式。MemoryDB本身微秒读已够快,前面再套ElastiCache意义不大(缓存目的是挡慢后端,MemoryDB不慢)。常见正确架构:①ElastiCache缓存+Aurora/RDS主库;②纯MemoryDB当主库(既内存性能又持久,不用再配缓存和DB)。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 缓存Redis(可丢) | ElastiCache for Redis/Valkey | Memorystore for Redis |
| 持久Redis主库(不丢) | MemoryDB ✅ | ⚠️无原生对等 |

关键：**MemoryDB是AWS独有差异化服务**("持久的、能当主库的Redis")。GCP Memorystore定位就是缓存(虽有RDB持久化选项但非"多AZ强持久主库")。想在GCP要MemoryDB那种持久Redis主库,得用Redis Enterprise(第三方)或自建。

### ⑤ 评分 + 记忆点
**7/10**。**MemoryDB = "持久版的 ElastiCache Redis"**,本质区别是durability(数据不丢,不是"强事务")。靠多AZ事务日志实现持久+快速故障切换→读微秒/写个位数ms(读快写慢)。选型:数据不能丢+要内存性能+想省掉缓存和DB两套→MemoryDB主库;数据可丢只加速读→ElastiCache缓存。GCP无MemoryDB对等。

---

# 第十模块：Redshift / Athena

## Q25. Amazon Redshift

**题干**：Redshift 是什么类型/干什么？OLTP vs OLAP 区别？为什么查海量数据快？什么场景用 Redshift 什么用 Aurora？

**小帅作答**："redshift 是数据仓库,用来分析查询。olap 是大量数据查询统计分析,oltp 是少量数据更新写入。redshift 是 mpp 列式存储。分析时候用 redshift,redshift 数据来自 aurora 一手数据。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 是什么/干什么 | 数据仓库/分析查询 ✅ | 正确 |
| OLAP定义 | 大量数据查询统计分析 ✅ | 正确 |
| OLTP定义 | 少量数据更新写入 ✅ | 正确 |
| 为什么快 | MPP✅列式✅ | 对,漏压缩+分布键/排序键 |
| 选型 | 分析用Redshift/数据来自Aurora ✅ | 方向对,抓到"从OLTP库同步" |

### ② 完整参考答案 + 原理详解
Redshift 是 AWS 全托管云数据仓库,为OLAP(分析型)设计——海量数据大规模扫描/聚合/多表JOIN/报表。不是跑高频交易的OLTP。

**OLTP vs OLAP**：
| 维度 | OLTP(Aurora/RDS/DynamoDB) | OLAP(Redshift) |
|---|---|---|
| 全称 | Online Transaction Processing | Online Analytical Processing |
| 操作 | 高频小事务增删改查 | 低频大范围扫描聚合 |
| 数据量/次 | 每次动几行 | 每次扫百万~十亿行 |
| 关注 | 低延迟/高并发/ACID | 高吞吐/复杂查询/扫描聚合速度 |
| 存储 | 行式 | 列式 |

**为什么快（补全4机制）**：
1. **列式存储**：按列存,分析只读需要的几列跳过其余→大减I/O(行式要读整行)。
2. **MPP(大规模并行处理)**：多节点多slice,数据分散,查询拆开在所有节点并行执行后汇总。
3. **数据压缩**：列式同列类型相同值相似,压缩率极高,扫描物理数据更少。
4. **分布键+排序键**：分布键决定数据怎么分散到节点(选好如按JOIN键→避免跨节点shuffle);排序键决定磁盘物理排序(带时间过滤时靠zone map跳过不相关block)。

💡 补充:RA3节点(计算存储分离,数据放S3托管存储RMS)、Redshift Serverless(免管集群按用量付费)、Spectrum(直接查S3外部表不用先加载)。

**vs Aurora选型**：Aurora(OLTP)=应用主交易库(下单/库存/用户,高并发小事务);Redshift(OLAP)=分析/BI/报表(把Aurora等业务库数据经ETL/CDC同步过来,跑重型分析不影响生产库)。核心:别在OLTP库跑大分析(会拖垮),抽到数仓单独分析。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 云数据仓库 | Redshift | BigQuery |
| 架构差异 | 传统"集群"(选节点),RA3/Serverless才存算分离 | 从诞生纯serverless,无集群,自动伸缩,按扫描量或slot付费 |

关键：BigQuery天生serverless(比Redshift更早更彻底"无集群按需付费"),且同时对标Redshift+Athena(Q26展开)。

### ⑤ 评分 + 记忆点
**8/10**。**Redshift = 云数据仓库(OLAP)**。快的四法宝:列式+MPP+压缩+分布键/排序键。OLTP(Aurora小事务高并发)跑业务,OLAP(Redshift大扫描聚合)跑分析,数据从Aurora经ETL进Redshift,分析别压垮交易库。GCP对应BigQuery(天生serverless)。

---

## Q26. Amazon Athena

**题干**：Athena 是什么/最大特点？要不要预建集群/加载数据？计费模型？Redshift vs Athena 怎么选？

**小帅作答**："Athena 是无服务的大数据查询,直接查 S3 上格式化文件(parquet、avro 等),按照扫描数据付费。偶尔临时查询用 Athena。Athena 底层是 Presto 还是 Trino,还是会用 duckdb。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 是什么/特点 | serverless/大数据查询/直接查S3 ✅✅ | 正确 |
| 格式 | parquet/avro ✅ | 正确(还有ORC/JSON/CSV) |
| 计费 | 按扫描数据付费 ✅ | 正确 |
| 场景 | 偶尔临时查询 ✅ | 正确 |
| 底层引擎 | "Presto还是Trino,还是会用duckdb" ⚠️ | Presto+Trino对,DuckDB不对 |
| 要不要集群/ETL | 未明确答 | 缺失(与Redshift关键对比) |

### ② 完整参考答案 + 原理详解
Athena 是 AWS **serverless 交互式查询服务**——用标准SQL直接查S3数据,不用建集群、不用先加载进数据库。官方"based on Trino and Presto"(开源分布式SQL引擎),支持ANSI SQL/大JOIN/窗口函数/数组。

⚠️ **纠正引擎**：Athena 基于 Trino 和 Presto(Trino是Presto分裂出的社区分支)。**DuckDB不是Athena底层**——DuckDB是独立的进程内(in-process)分析型数据库(类似"分析界的SQLite"),和Athena无关。别混。

**要不要集群/加载数据（核心对比，你没答）**：Athena都不要——数据本就在S3,只要在Glue Data Catalog定义"外部表"描述S3数据schema就能直接SQL查,零基础设施零ETL装载。Redshift(传统)都要——先建集群+ETL加载进内部存储。本质差异:**Athena=查数据"原地"(data stays in S3);Redshift=把数据"搬进来"再查(load then query)。**

**计费（补省钱点）**：按扫描数据量付费,约$5/TB scanned,无集群常驻费。⭐省钱关键(官方省30-90%):①列式格式(Parquet/ORC)只扫需要的列;②分区(Partitioning)带过滤只扫相关分区;③压缩物理数据更小。反例:未分区大CSV可能全表扫几TB又慢又贵。

**Redshift vs Athena选型**：偶尔/临时/探索性查询+数据已在S3+不想管基础设施→Athena;高频/复杂/需持续高性能(BI看板每天几千次/复杂多表JOIN)→Redshift。直觉:Athena"随用随查按扫描付费";Redshift"常驻高性能引擎"。

### ④ AWS ↔ GCP（重点：BigQuery双重身份）
| 能力 | AWS | GCP |
|---|---|---|
| serverless查对象存储 | Athena | BigQuery(查GCS外部表/BigLake) |
| 高性能云数仓 | Redshift | BigQuery(原生存储表) |

关键：**AWS把"数仓"和"serverless即席查询"拆成两产品**(Redshift+Athena);**GCP用一个BigQuery同时干这两件事**(既高性能云数仓对标Redshift,又天生serverless能直接查GCS外部数据对标Athena)。面试问"BigQuery对应AWS什么"正解:同时对应Redshift+Athena(AWS多产品分工,GCP单产品通吃)。

### ⑤ 评分 + 记忆点
**7.5/10**。**Athena = serverless 直接查 S3 的 SQL 服务,基于 Trino/Presto(不是DuckDB)**,免集群免ETL,按扫描量付费($5/TB)→Parquet+分区省30-90%。选型:偶尔/临时/免运维→Athena;高频/复杂/持续高性能→Redshift。GCP的BigQuery一个产品同时对标Redshift+Athena。

---

# 第十一模块：DMS / RDS Proxy

## Q27. AWS DMS

**题干**：DMS 干什么？同构 vs 异构迁移？CDC 是什么为什么重要？典型场景？

**小帅作答**："dms 是迁移数据库,使用 cdc 模式,可以双向同步,最后实现 cutover。如果异构数据库,还需要先 SCT 做 schema 转化,类似 goldengate。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 是什么 | 迁移数据库 ✅ | 正确 |
| CDC | 使用CDC模式 ✅ | 正确且知用途 |
| cutover | 实现cutover ✅ | 很专业,理解全流程 |
| 异构 | 需先SCT做schema转化 ✅✅ | 完全正确 |
| 类比GoldenGate | ✅ | 好类比 |
| "可以双向同步" | ⚠️ | 部分对,需精确化 |

### ② 完整参考答案 + 原理详解
DMS 是 AWS 全托管数据库迁移服务,把数据从源库迁移/持续复制到目标库。既能一次性搬迁也能持续复制。

**同构 vs 异构**：
| 类型 | 含义 | 需SCT? | 例子 |
|---|---|---|---|
| 同构 | 同一种引擎 | 不需要 | MySQL→Aurora MySQL |
| 异构 | 不同引擎 | 需要SCT | Oracle→Aurora PostgreSQL |

SCT(Schema Conversion Tool):异构时源库表结构/存储过程/函数/触发器在目标引擎语法不同,SCT自动转换schema+代码(如Oracle PL/SQL→PostgreSQL PL/pgSQL),转不了的标记出来手动改。DMS搬数据,SCT转结构/代码,配合完成异构迁移。

**CDC（为什么重要）**：迁移两阶段:①Full Load(全量加载)把现有数据整体搬;②CDC(持续增量同步)全量过程中和之后源库还在被业务写入,CDC读源库事务日志(MySQL binlog/PostgreSQL WAL/Oracle redo log)持续同步增量到目标。**为什么重要=实现近零停机迁移**:有CDC持续追平增量源库不用停机,等目标追平后做cutover(短暂停写源库→等最后增量同步完→应用指向目标库),停机窗口从几小时压到几分钟。

**关于"双向同步"（精确化）**：DMS支持双向复制但主要用于特殊场景(双活/迁移回滚保护),有冲突处理/循环复制防护复杂性,非默认。常规迁移是单向(源→目标+CDC追增量)。面试更稳妥说法:"DMS主要单向迁移+CDC增量;也支持双向复制但需处理冲突,用于双活等特殊场景"。

**场景**：数据库上云(本地Oracle/SQL Server→RDS/Aurora)、跨引擎迁移(Oracle→Aurora PostgreSQL省license)、持续复制到分析/湖(OLTP库经DMS+CDC同步到Redshift/S3,呼应Q25"Redshift数据来自Aurora一手数据")、数据库整合拆分、跨区域灾备复制。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 迁移服务 | DMS(+SCT异构转换) | Database Migration Service(也叫这名) |
| CDC | DMS CDC(读事务日志) | GCP DMS支持MySQL/PG/Oracle→Cloud SQL/AlloyDB,也用CDC |
| 异构转换 | 独立SCT工具 | 内置部分转换能力 |

关键：两家都叫"Database Migration Service"思路一致(全量+CDC近零停机)。差异:AWS把schema转换拆成独立SCT;GCP更多集成进DMS流程。第三方通用工具=Oracle GoldenGate(跨云经典CDC复制)。

### ⑤ 评分 + 记忆点
**8.5/10**（最强一题）。**DMS = 数据库迁移,全量(Full Load)+CDC(读事务日志追增量)→近零停机→cutover切换**。同构不用SCT,异构要SCT转schema/代码。场景:上云/跨引擎/持续复制到Redshift/S3。"双向同步"能做但非常规(记单向+CDC为主)。类比GoldenGate。

---

## Q28. RDS Proxy

**题干**：RDS Proxy 是什么/挡在哪两者之间？主要解决什么问题？对故障切换有什么帮助？什么场景强烈建议上？

**小帅作答**："rds proxy 是应用和数据库之间,实现链接 pool 和读写分离,解决短链接建立链接花费时间,适用短链接、数据库经常打满的。"

### ① 逐点对照
| 考点 | 回答 | 评价 |
|---|---|---|
| 位置 | 应用和数据库之间 ✅ | 正确 |
| 连接池 | 实现连接pool ✅ | 正确(核心功能) |
| "读写分离" | ❌ | 错误——RDS Proxy不做读写分离 |
| 解决什么 | 短连接建连接耗时 ✅ | 对但不完整(漏连接数打满/连接风暴核心) |
| 场景 | 短连接/DB经常打满 ✅ | 正确 |

### ② 完整参考答案 + 原理详解
RDS Proxy 是全托管数据库连接池代理,挡在应用↔RDS/Aurora之间。应用连Proxy,Proxy维护到数据库的连接池并复用。大多数应用无需改代码。

⚠️ **重点纠错：RDS Proxy 不做"读写分离"**。官方文档通篇讲连接池化(pooling)/连接复用/防连接风暴/故障切换保持连接/IAM认证——没有"把读请求路由到只读副本、写请求路由到主库"这个功能。
- **读写分离**是应用层/Aurora端点的事:Aurora提供Cluster Endpoint(写,指向主)和Reader Endpoint(读,自动负载均衡到只读副本),应用配置"读走reader endpoint、写走cluster endpoint"实现。**你OpenCart的db.php就是这么做的(DB_READER_HOSTNAME走reader),跟RDS Proxy无关。**
- 别混:RDS Proxy=连接管理;读写分离=端点路由(应用层做)。这是面试易错点,你踩了。

**主要解决什么（补全核心）**：
1. **连接风暴/连接数打满(最核心)**：数据库最大连接数是稀缺资源(每连接吃内存+CPU)。尤其Lambda等serverless瞬间几千并发每个开新连接→瞬间打爆(oversubscription)。Proxy用连接池复用:几千应用连接共享少量真实DB连接,保护数据库。你答"数据库经常打满"✅。
2. **省反复建连接开销**：每次新连接要TCP握手+认证+TLS。Proxy复用池里连接避免。你答"短连接建连接耗时"✅。
3. **超限排队/限流而非崩溃**：超池容量时排队或限流(shed load),应用平滑降级不压垮数据库。

**对故障切换的帮助（你没答）**：failover时(主库挂副本升主),传统情况应用所有连接断开要重连可能报错几十秒。RDS Proxy在failover时保持应用侧连接不断,自己后台快速重连新主库,大幅缩短中断(官方可减少高达66% failover时间),应用几乎无感。

**场景**：Lambda/serverless密集访问RDS/Aurora(头号动机,Lambda无法自维护连接池最易打爆);连接数经常打满/有连接风暴;大量短连接的应用(PHP每请求建连接);需更平滑更快failover。

### ④ AWS ↔ GCP
| 能力 | AWS | GCP |
|---|---|---|
| 托管连接池代理 | RDS Proxy | 无完全等价独立托管服务 |
| GCP连接管理 | — | Cloud SQL Auth Proxy(主要安全连接/IAM认证,不是连接池);连接池靠PgBouncer自建或AlloyDB内置 |

关键：**RDS Proxy是AWS相对完整的托管连接池方案**,GCP无"名字就叫连接池代理"的对等托管服务。Cloud SQL Auth Proxy易被误认对等物但只管加密连接+IAM认证+免管IP白名单,不做连接池化。面试记:"RDS Proxy≈连接池+failover加速;GCP的Auth Proxy只管安全连接不管池,连接池要自建"。

### ⑤ 评分 + 记忆点
**6/10**。**RDS Proxy = 应用↔数据库之间的托管连接池代理**。核心解决连接风暴/连接数打满(尤其Lambda)+省建连开销+failover时保持连接快速切换。⚠️不做读写分离(读写分离是Aurora reader/cluster endpoint+应用路由,OpenCart实战用过)。GCP无完全对等(Auth Proxy只管安全不管池)。

---

# 附录：本轮答疑（非题目）

## Cache-Aside vs Write-Through 适用场景
- **Cache-Aside 适用**：①读多写少(read-heavy,热点反复读,回填后大量命中);②能容忍数据短暂陈旧(写时失效缓存,下次读回填,有极短不一致窗口);③只想缓存真正被访问的热数据(冷数据不占内存);④要求缓存故障不影响正确性(挂了回源DB仍正确,容错好=默认首选)。不适合:写非常频繁且要求缓存立即最新(每写失效→下次miss回源,命中率被打穿);极端读一致性。
- **Write-Through 适用**：①读一致性高不能读旧数据(每写同步更新缓存,读永不陈旧,如余额/账户/库存);②读远多于写且写后马上被读(write-then-read);③配合Read-Through形成"读写都由缓存层托管";④希望命中率稳定极高。不适合:写延迟敏感;写多读少(缓存大量永不被读数据浪费内存);数据量远大于缓存容量。
- 对比表:Cache-Aside(应用自管/只放热数据/可能读旧值/写延迟低/内存省/容错好/商品页资料配置)vs Write-Through(缓存层管/放所有写过数据/读永最新/写延迟高/可能浪费内存/故障影响大/余额库存设置)。
- 心法:**Cache-Aside 治"读放大"(怕慢),Write-Through 治"读旧值"(怕不一致)。**

## 布隆过滤器防缓存穿透
- 术语:穿透(penetration,查根本不存在的数据,每次都打DB)/击穿(breakdown,热点key突然过期瞬间大量并发涌向DB)/雪崩(avalanche,大量key同时过期或缓存宕机)。布隆过滤器防的是**穿透**。
- 布隆过滤器=概率型数据结构判断元素"是否可能在集合里":判定不存在100%准(没有假阴性);判定存在可能误判(假阳性)。口诀"说没有就真没有,说有可能骗你"。
- 原理:长度m位数组(初始全0)+k个哈希函数。加元素:算k个位置置1。查:任一位置0→一定不存在;全1→可能存在。
- 参数:m越长假阳性越低(占更多内存);k最优≈(m/n)ln2。100万元素想1%假阳性≈1.2MB(每元素~9.6bit,极省内存)。
- 限制:标准BF不能删(清0可能误伤共享位→假阴性,要用Counting Bloom Filter变种);有假阳性不能单独做"确定存在"判断。
- 实战:架构 请求→布隆过滤器→缓存(Redis)→数据库。判"不存在"直接返回不查缓存不查DB(拦截穿透);判"可能存在"继续。Redis 4.0+ RedisBloom模块 BF.ADD/BF.EXISTS/BF.RESERVE,启动时把DB所有存在key预灌进去。
- vs "缓存空值":布隆过滤器极省内存拦最前(有假阳性/不能删/要预热);缓存空值实现简单精确(但海量不存在key会塞满缓存)。常组合:布隆过滤器挡多数,漏网假阳性用缓存空值兜底。
