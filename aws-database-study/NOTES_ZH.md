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
