# AWS 数据库面试题批改笔记（Q1-Q30）

> 题库见 QA_ZH.md（10 模块 30 题：RDS/Aurora/DynamoDB/ElastiCache/DocumentDB/Neptune图/Timestream时序/Redshift/DMS/选型）。
> 流程：①出题干(不给答案)→②伟伟作答→③五板块批改(逐点对照/参考答案+原理/概念深入/AWS↔GCP对照/评分+记忆点)。答完即停,不预告。
> 铁律:每题五板块完整展开发在聊天;NOTES归档是附加动作不能代替聊天展开。

## 批改进度
（待开始，从 Q1-Q2）

## 批改进度
| 题 | 分数 | 关键点/纠错 |
|---|---|---|
| Q1 | 3.5/5 | RDS托管关系型/DB2答对(加分)/自管SQL+schema对;漏MariaDB+SQLServer+Aurora(共7引擎);"自动升级"不准(小版本可自动,大版本手动);"优化参数"误解(RDS不自动调优,只给参数组+Performance Insights);"自动高可用"不准(要主动开Multi-AZ)。取舍=弃OS控制权换免运维。GCP=Cloud SQL(仅MySQL/PG/SQLServer,无Oracle/Db2);云原生=AlloyDB;全球强一致=Spanner |
| Q2 | 2/5 | failover靠DNS CNAME重指向(答得好)+客户端重连对;**同步答成异步**(核心错,Multi-AZ同步/零丢失RPO≈0);**HA答成读扩展**(核心错,备库不可读纯热备);与RR关系反了。Multi-AZ=保命(HA同步),RR=扩读(异步/可读/可跨区),两不同目的常一起用;failover 60-120s。新Multi-AZ DB Cluster模式备库可读(较新特性)。GCP Cloud SQL HA靠Regional Persistent Disk磁盘层跨zone同步,备库同样不可读 |
| Q3 | 4.5/5 | 异步✓/读扩展✓/跨区DR✓/不自动升级✓/手动promote✓ 核心全对;漏"为什么异步"+**复制延迟(replication lag)→最终一致**(强一致读要读主库)。RR=异步只读拷贝(独立存储/实例)→读扩展;可跨区(DR+就近读+迁移);promote不可逆。对比Multi-AZ自动+同步/RR手动+异步。GCP Cloud SQL RR同为异步/读扩展/可跨区/手动promote;AlloyDB有read pool |
| Q4 | 3/5 | Multi-AZ+RR可同用✓/读扩展✓/跨区容灾✓ 方向对;**漏读写端点分离**(写端点vs读端点,SELECT走副本+写/强一致读走主库,RDS Proxy路由,呼应OpenCart读写分离);漏完整架构;**漏RPO/RTO量级**(Multi-AZ RPO≈0/RTO60-120s/自动防AZ; 跨区RR RPO秒-分/RTO分钟/手动防region; 全球低RPO自动=Aurora Global DB~1s)。GCP跨区强一致王牌=Cloud Spanner(RPO≈0全球) |

## 穿插答疑（09-08）复制机制考据（重要,基于官方User Guide原文）
- **Read Replica用什么复制** → 官方User Guide原话"uses the **built-in replication features of the DB engine**"+"copies them **asynchronously**"。各引擎:MySQL/MariaDB=binlog复制,PostgreSQL=WAL流复制,Oracle/SQLServer/Db2各自原生。是**引擎层逻辑复制**(副本重放变更→真正运行的实例→**可读**)。来源 USER_ReadRepl.html。
- **Multi-AZ用什么复制** → ⚠️纠错:RDS User Guide**没有**"block replication"措辞。User Guide(Concepts.MultiAZSingleStandby.html)原话:①"**synchronously replicated**"(同步,明确)②备库"**can't serve read traffic**"(不可读,明确)③MariaDB/MySQL/Oracle/PG用含糊的"**Amazon failover technology**",**未公开**底层是块复制还是引擎复制(托管黑盒)④**SQL Server**明确用"**Database Mirroring(DBM)或Always On AG**"(引擎层HA,非块复制)。
- "block-level storage replication"仅出现在**Db2官方博客**,不是通用Multi-AZ的User Guide措辞。之前我(助手)说成User Guide写的=不严谨,已纠正。
- **严谨答法**:Multi-AZ官方只拍板"同步+不可读";机制SQL Server=DBM/AG,其他引擎=含糊的"Amazon failover technology"未明说块or引擎复制。业界普遍理解非SQLServer经典Multi-AZ偏存储/块级同步(故备库不可读)但非官方原话。
- **对比**:Read Replica=引擎原生复制(异步/可读,官方明确);Multi-AZ=同步/不可读(官方明确),复制机制黑盒(SQLServer例外=DBM/AG)。
| Q5 | 3.5/5 | MySQL/PG兼容✓/6副本✓/**写4/6 quorum答对**✓/log is database概念✓/容量自动增长✓;**"像RAC/share-everything"不准**(Aurora=共享存储的**单写多读**,非RAC多写+缓存融合);**"没data file/查询慢"错**(有数据页,只是页由**存储节点用redo log回放物化**,读照样快)。存储6副本/3AZ,写4/6读3/6 quorum,容忍挂1AZ还能写。GCP=AlloyDB(存储计算分离+log下推存储层,理念几乎一致);全球强一致=Spanner(TrueTime,另一物种) |
| Q6 | 4/5 | 共享存储✓/failover不copy存储✓(答到根本)/副本可升写库✓;**副本数16错→是15**;漏"复制延迟为何小"(共享存储读同一份+只广播log更新缓存→毫秒级)。Aurora读副本=共享分布式卷(区别RDS RR异步binlog各自拷贝)→延迟毫秒级+failover快~30s(reader直接提升writer,按promotion tier 0-15选)+集群内自动failover(强于RDS RR手动promote);一套副本同时扩读+保命。GCP AlloyDB read pool理念一致 |

## 穿插答疑(09-08) "log is the database"出处考据(重要,标来源层级)
- **官方User Guide明确的**(Aurora.Overview.StorageReliability.html):共享分布式cluster volume/6副本跨3AZ/**加副本不拷数据**("Aurora doesn't make a new copy of the table data")/存储独立于计算/自动伸缩/IO-Optimized vs Standard计费。
- **官方博客明确**:写4/6读3/6 quorum("under the hood: quorum"博客)。
- ⚠️**"log is the database"+数据页物化外包给存储节点** → **公开User Guide未展开**;权威出处=**AWS SIGMOD 2017论文《Amazon Aurora: Design Considerations...》**(有一节标题就叫"THE LOG IS THE DATABASE")+官方博客/re:Invent。
- **面试严谨答法**:共享存储/存储计算分离/加副本不拷数据=User Guide明确;log is database+存储节点回放物化数据页=SIGMOD 2017论文,非User Guide。伟伟认可论文作为出处。
| Q7 | 3/5 | 不预置/自动伸缩✓/固定内存CPU比例✓/v1冷启动✓/v2更快✓/间歇负载✓;"每次伸缩一个ACU"不准(v2=0.5ACU平滑增量,非跳一个);v1冷启动时机没答(auto-pause到0后**第一个请求**唤醒,几十秒);v2为何快没答(**原地加资源** vs v1找scaling point换更大实例迁移)。ACU=容量单位,**1ACU≈2GiB内存**+配套CPU;v1粗粒度跳档+暂停到0被诟病;v2重写架构平滑秒级+支持完整reader/GlobalDB+现支持scale-to-0(较新);稳定满载用预置更划算。GCP关系库无完全对等,真serverless明星=BigQuery(OLAP) |
| Q8 | 4/5 | 另一region复制✓/**RPO=1s准**✓/合规容灾✓/Spanner RPO=0多写强一致✓/主动问写延迟差异(好直觉);漏与跨区RR区别(**存储层专用复制**非引擎binlog,延迟低不拖主库);漏RTO(托管failover分钟级)。GlobalDB=1主region(可写)+最多5从region(只读),存储层异步复制RPO~1s;vs Spanner:Spanner全球多写+强一致+RPO≈0靠**TrueTime**,代价**跨区同步写延迟更高**;Aurora单区写**写延迟低**但全球最终一致=**强一致vs低写延迟本质取舍**;AWS无Spanner对等物 |
| Q9 | 4/5 | 自动备份连续/≤35天✓/手动快照不含日志·可随时·可超35天✓(答准)/PITR靠日志回放✓/跨区跨账号✓;PITR用词偏窄("redo log"是MySQL视角,通用=**事务日志binlog/WAL**);**漏恢复=新建实例**(不覆盖原库);漏加密快照跨账号共享要**自定义KMS CMK+授权目标账号**。自动备份=每日全量+持续事务日志→支持PITR(恢复到任意秒);手动快照=某刻镜像不含日志·可永久·不支持PITR。GCP Cloud SQL同理(PITR靠binlog/WAL) |
| Q10 | 2/5 | 参数组=数据库参数✓/启动选参数组✓/选项组非必须✓;**static/dynamic说反**(核心错:**static要重启,dynamic立即生效**;口诀动的立刻动/静的要停);**默认参数组能改说错**(官方明确默认组**不能改**,要建自定义组);选项组"开额外功能/插件"没说清(Oracle/SQLServer的TDE/审计);漏参数组vs选项组本质(调值 vs 开功能)。换整个参数组要重启1次,改已关联组的dynamic参数立即生效。Aurora有集群级+实例级两级参数组。GCP用统一database flags,无参数组/选项组之分/无默认组只读概念 |
| Q11 | 3/5 | gp2/gp3/io1/io2✓/建议新代系✓/可配IOPS✓/io2延迟稳✓;漏magnetic;漏Provisioned IOPS定位场景(io1/io2显式指定稳定IOPS,关键OLTP/金融/延迟敏感);**漏gp3 vs gp2关键改进(IOPS/吞吐独立于容量配置,gp2是3IOPS/GB绑定+credit抖动,gp3更便宜~20%)**;漏存储自动伸缩(自动扩容防写满,只增不减)。选型:一般gp3/极密集io2/magnetic别用。GCP=PD-SSD/**Hyperdisk**(解耦盘) |
| Q12 | 3/5 | private子网✓/SG来自app✓/KMS加密✓/Secrets存密码✓;**漏传输加密SSL/TLS**(只答at-rest);**漏未加密实例不能原地开加密**(核心陷阱:必须快照→加密复制快照→从加密快照恢复新实例;也不能给未加密库建加密副本;创建时就开加密);漏IAM数据库认证(临时token无密码)。GCP Cloud SQL**默认全加密**(无未加密转加密陷阱),也支持IAM认证/CMEK/Private IP |
| Q13 | 3.5/5 | NoSQL/KV✓/serverless全托管✓/分区键打散✓/**放弃schema+强事务换低延迟高吞吐(本质好)**✓;"查询某几个分区"不准(高效查询必须给分区键**精确定位单分区**,跨分区=Scan低效);复合主键=**恰好分区键+排序键2个**(非"多个");排序键作用(同分区排序+range查询)没展开;个位数ms为何没答(hash打散+自动加分区+无JOIN直接定位)。DynamoDB也支持文档(嵌套属性)+有限ACID事务(TransactWriteItems)。GCP=Firestore(文档强一致)+Bigtable(海量宽列) |
| Q14 | 2.5/5 | 预置vs按需区分✓/按需按用量✓/热分区概念✓/打散重设计key✓;**RCU/WCU说成CPU内存(核心错)**→是**读写吞吐单位**(1RCU=每秒4KB强一致读/8KB最终一致读;1WCU=每秒1KB写);计量没答;预置/按需场景没展开;避免热分区手段(加盐write sharding/adaptive capacity/单分区上限~3000RCU/1000WCU)没展开。热分区=流量集中少数键→局部限流(总容量没满也报错)。GCP Bigtable同样怕热row key(时间戳/顺序key反模式),按节点配吞吐无RCU/WCU |
| Q15 | 1.5/5 | 知道有GSI/LSI;**global/local理解成"唯一性"错**(是**能否跨分区**);**"global只能建表时指定"记反**(是**LSI只能建表时创建**,**GSI可随时创建/删除**);漏一致性(GSI只最终一致/LSI可强一致)+独立容量(GSI有独立RCU/WCU,LSI共享主表)。GSI=可用不同分区键/跨全表/可后加删/独立容量/最终一致;LSI=必须同分区键换排序键/建表时创建/共享容量/可强一致/单分区键≤10GB。类比Oracle:GSI≈global index/LSI≈local index(理念像,实现不同:GSI是异步复制的最终一致索引)。GSI用得多 |
| Q16 | 2/5 | DAX=缓存✓/Streams做CDC✓;**最终一致读vs强一致读(核心)没答**(默认最终一致,1RCU=2次最终一致/1次强一致,便宜一半,GSI/DAX/跨区不支持强一致);**Global Tables是多活多写没答出**(区别Aurora单写!最终一致+last-writer-wins冲突解决);Streams/DAX只点名没展开。Streams=变更流(24h)→触发Lambda/CDC/Global Tables底层;DAX=微秒级读缓存(API兼容/写穿透/只加速读/最终一致)。全球强一致多写要GCP Spanner |

## 穿插答疑(09-08) DynamoDB vs Redis(ElastiCache)对比
- 伟伟判断:①DynamoDB是持久存储✓对(SSD+多AZ持久);②latency比Redis高一个数量级✓基本对(DynamoDB个位数ms,Redis亚毫秒μs;DynamoDB+DAX可补到μs)。
- **本质**:DynamoDB=持久化NoSQL数据库(数据的家,SSD,near-infinite,ms级,system of record);Redis=内存缓存/内存数据结构(加速层,RAM,受内存限,μs级,丰富数据结构string/hash/list/set/zset/stream)。
- **为何Redis快一个数量级**=RAM(ns~μs) vs SSD+网络+多副本一致(μs~ms),存储介质+架构层次的物理差异。
- **通常配合用非二选一**:应用→Redis(μs挡热读)--miss-->DynamoDB/Aurora(ms持久权威),即OpenCart架构。
- 想要Redis速度+持久→**MemoryDB for Redis**(多AZ事务日志持久化+强一致,可当主库,非只缓存);DynamoDB想μs读→+DAX。
- GCP:DynamoDB→Firestore/Bigtable;ElastiCache→Memorystore;MemoryDB→GCP无完全对等(Memorystore偏缓存)。
| Q17 | 3/5 | Redis数据结构多✓/可持久✓;Memcached简单✓/不持久✓/无HA✓;**线程模型完全说反**(Redis命令执行**单线程**,Memcached**多线程**;伟伟答成Redis多线程/Memcached单线程)。记忆法:Redis单线程重功能(无锁原子,多核靠分片)/Memcached多线程轻功能(吃满多核纯KV)。Redis 6+有多线程I/O但命令仍单线程。绝大多数选Redis。GCP=Memorystore(同Redis+Memcached) |
| Q18 | 3/5 | cluster mode分片多节点✓/**MemoryDB可当主数据(本质对)**✓/需持久✓;cluster enabled(多分片横向扩,key按hash slot)vs disabled(单分片,加只读副本扩读/换大节点)没展开;副本+自动故障切换没答(每分片1主+最多5副本+MultiAZ,ElastiCache异步复制切换**可能丢**);**MemoryDB本质没答**(写**同步到多AZ事务日志**→强一致+宕机不丢,这才是能当主库的原因);"内存要求高"不是关键(关键是持久化代价:写延迟略高+更贵)。ElastiCache=缓存(权威在别处可丢);MemoryDB=持久主库(数据即权威不能丢,省缓存+后端两层)。GCP Memorystore无MemoryDB对等物 |

## 穿插答疑(09-08) MemoryDB内部实现
- **是Redis改还是全新开源?** → 官方明确:兼容Redis/Valkey API,**非独立开源项目**(AWS托管商业产品);**我的推断(非官方)**:大概率基于Redis/Valkey引擎+AWS自研持久化层,非从零重写;是否fork Redis源码AWS未公开。
- **是不是把Redis改成写落盘?** → 方向对但不精确。Redis本就有AOF/RDB落盘,单机落盘≠不丢(节点/AZ挂了还是丢)。MemoryDB关键=每次写**同步复制到跨多AZ的分布式事务日志**+多数派确认才返回→分布式持久+强一致+不丢(写延迟比纯内存Redis高、更贵)。不是简单本地落盘。
- **像Oracle TimesTen吗?** → 神似(都是内存库+事务日志持久化+可当主库),但**TimesTen是SQL关系型,MemoryDB是Redis KV**,数据模型/接口不同;MemoryDB是云原生多AZ持久化,TimesTen传统单机checkpoint+log。类比成立在"内存库+持久化+权威源"层面,不能划等号。

## 批改续（09-08~09-09，聊天出题 Q19–Q28，对应 DocumentDB/Neptune/Timestream/Redshift/DMS 等模块）

> 注：以下 Q19–Q28 是 09-08 起聊天里按服务模块新出的题（编号独立于上方 QA_ZH 的 Q1–Q30 原始题库），逐题五板块已在聊天完整展开，此处归档要点。

| 题 | 主题 | 分数 | 关键点/纠错 |
|---|---|---|---|
| Q19 | DocumentDB | 6.5/10 | 兼容MongoDB API✓/文档库✓/选型方向对(简单KV极致性能→DynamoDB);**架构没答**(核心)=Aurora式:计算存储分离+cluster volume六副本跨3AZ+1 primary最多15 replica+256TiB(8.0)。选型补全:文档模型/复杂查询/迁移已有MongoDB→DocumentDB;云原生/极致规模/serverless→DynamoDB。GCP=Firestore(非MongoDB兼容,更像文档版DynamoDB;GCP无MongoDB兼容原生,靠Atlas第三方) |
| Q20 | Keyspaces | 4/10 | 兼容Cassandra✓/宽列✓;**serverless没答**(核心卖点=免运维无节点概念,不是"写快");数据模型没答=Partition Key+Clustering Column(s)(可多列分层排序)vs DynamoDB Partition Key+单Sort Key;选它主要为迁移已有Cassandra,全新项目通常直接DynamoDB。GCP=Bigtable(但兼容HBase非Cassandra,且仍要管节点非纯serverless;BigTable论文是宽列共同祖先) |
| Q21 | Neptune | 6/10 | 图数据库✓/场景社交/知识图谱/欺诈✓✓(官方点名);**语言没答**="两模型三语言"=属性图Gremlin/openCypher+RDF SPARQL;**架构没答**=Aurora式同构(共享cluster volume多AZ+1写15读+PITR+持续备份S3)。场景本质=多跳关系查询,关系库JOIN爆炸处用图库。**GCP图是空缺**(Spanner Graph新增或第三方Neo4j Aura) |
| Q22 | Timestream | 8/10 | 时序库✓/时序特点海量追加写+少更新+时间范围查+随时间变冷✓✓✓/自动分层✓/IoT+metrics✓/开源对应InfluxDB✓;缺分层具体两层=**Memory Store(热/快写快点查)→按retention policy自动迁移→Magnetic Store(冷/低成本分析)+TTL自动删**。serverless、写入/存储/查询三系统解耦独立伸缩。AWS有Timestream for InfluxDB托管InfluxDB引擎。**GCP无专用时序库**,用Bigtable/BigQuery承载 |
| Q23 | ElastiCache | 6/10 | 内存缓存挡DB前✓/减DB压力✓/Redis结构丰富+单线程+可持久✓;**Memcached没提**(本题要对比)=纯简单KV+多线程+不持久+无复制,极简缓存才用;Cache-Aside✓但漏"读miss回填"+"写时失效缓存";**Write-Through说反重点**(核心是"同时写缓存",不只写DB→读永命中但写变慢)。实战OpenCart:session存Redis/商品配置缓存(Cache-Aside)/购物车迁Redis。GCP=Memorystore(Redis+Memcached) |
| Q24 | MemoryDB | 7/10 | AWS自研内存库✓/读快写慢✓(文档实锤:微秒读/个位数ms写)/可做主库✓;**本质区别用词不准**="强事务"应为**durability持久性**;怎么持久没答=**多AZ事务日志**(每写同步落多AZ日志才返回)→持久+快速故障切换。选型:数据不能丢+要内存性能+省掉缓存和DB两套→MemoryDB主库;数据可丢只加速读→ElastiCache缓存。**MemoryDB是AWS独有,GCP无对等**(Memorystore只是缓存)。点评"MemoryDB主库前放ElastiCache"=技术可行但通常反模式(MemoryDB本身已够快) |
| Q25 | Redshift | 8/10 | 数仓✓/OLAP大扫描聚合✓/OLTP小事务写✓/MPP✓/列式✓/数据来自Aurora一手✓;补全"为什么快"四法宝=列式存储+MPP并行+压缩+分布键/排序键(zone map跳块)。RA3(存算分离)/Serverless/Spectrum(查S3外部表)。选型:Aurora(OLTP交易)vs Redshift(OLAP分析),数据ETL/CDC同步进数仓,别在交易库跑大分析。GCP=BigQuery(天生serverless) |
| Q26 | Athena | 7.5/10 | serverless✓/直接查S3✓/parquet/avro✓/按扫描付费✓/偶尔临时查✓;**引擎混入DuckDB(错)**→官方"based on Trino and Presto",DuckDB是无关的进程内分析库;漏"免集群免ETL"(vs Redshift建集群+加载)。$5/TB扫描,Parquet+分区省30-90%。选型:偶尔/临时/免运维→Athena;高频/复杂/持续高性能→Redshift。**GCP BigQuery一个产品同时对标Redshift+Athena**(高频考点) |
| Q27 | DMS | 8.5/10 | 迁移✓/CDC✓/cutover✓✓/异构需SCT✓✓/类比GoldenGate✓(最强一题);"双向同步"需精确化(常规单向+CDC,双向复制非常规需冲突处理)。全量Full Load+CDC(读binlog/WAL/redo log追增量)→近零停机→cutover切换。同构不用SCT,异构SCT转schema/代码。场景:上云/跨引擎/持续复制到Redshift/S3。GCP也叫Database Migration Service |
| Q28 | RDS Proxy | 6/10 | 应用↔DB之间✓/连接池✓/短连接建连耗时✓/DB打满✓;**"读写分离"错**(RDS Proxy不做读写分离!读写分离=Aurora reader/cluster endpoint+应用路由,OpenCart实战用过);漏failover加速(保持应用连接快速切新主,减少高达66% failover时间)。核心解决连接风暴/连接数打满(尤其Lambda)+省建连开销。GCP无完全对等(Cloud SQL Auth Proxy只管安全不管池,连接池靠PgBouncer自建/AlloyDB内置) |

## 穿插答疑（09-09）
- **Cache-Aside vs Write-Through 适用场景**：Cache-Aside治"读放大"(读多写少+容忍短暂陈旧,如商品页/资料/配置;缓存故障可回源,容错好,默认首选);Write-Through治"读旧值"(读一致性高+写后即读,如余额/库存/设置;每写多一步写缓存→写变慢+可能缓存冷数据浪费内存)。可组合:Cache-Aside读+写失效 / Read-Through+Write-Through / Write-Behind(异步刷DB最快但可能丢)。
- **布隆过滤器防缓存穿透**(penetration非击穿breakdown):概率结构,说不存在100%准/说存在可能假阳性/无假阴性;位数组+k哈希;标准BF不能删(要Counting BF变种);极省内存(100万元素1%假阳性~1.2MB);RedisBloom BF.ADD/BF.EXISTS;架构前置于缓存拦截不存在的key,常配"缓存空值"兜底。穿透(查不存在)/击穿(热点key过期)/雪崩(大量key同时过期或宕机)三者区别。

## 本轮收尾（09-09 03:02）
- 伟伟决定本轮面试题库到此收尾（Q29/Q30 DynamoDB深入题因前面已散考过而跳过），总结推 GitHub。
- 累计已批改：QA原题库 Q1–Q18 + 聊天新出 Q19–Q28（DocumentDB/Keyspaces/Neptune/Timestream/ElastiCache/MemoryDB/Redshift/Athena/DMS/RDS Proxy）。
