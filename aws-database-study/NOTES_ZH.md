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
