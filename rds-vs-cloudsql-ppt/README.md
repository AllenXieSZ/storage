# AWS RDS vs GCP Cloud SQL — 对比 PPT

18 页对比演示文稿，NetApp 风模板，AWS 橙 / GCP 蓝双列对照。所有数据基于两家**官方文档**核实（RDS User Guide / Cloud SQL 文档 / 各自 SLA/quotas/定价页），推测/第三方来源均分层标注。

## 内容结构

**托管传统引擎篇（P1–9，主对比）**
1. 封面
2. 对标关系（厘清 RDS↔Cloud SQL / Aurora↔AlloyDB / Aurora Global·DSQL↔Spanner 三个层次）
3. 支持的数据库引擎（RDS 6 种 vs Cloud SQL 3 种）
4. GCP 上如何跑 Oracle / Db2（Oracle@Google Cloud；Db2 无对标）
5. 版本模型（Cloud SQL Enterprise / Enterprise Plus 分档 vs RDS 实例类+选项）
6. RDS 三种部署模式（含 Multi-AZ DB cluster 本地 NVMe binlog）
7. 高可用 & SLA
8. 存储上限 & 只读副本
9. 备份 / PITR & 特色能力

**云原生篇（P10–13）：Aurora vs AlloyDB**
10. 分隔页
11. 云原生架构：存算分离（Aurora 6副本/3AZ vs AlloyDB 三层存算解耦）
12. HTAP / 列式引擎 / AI（AlloyDB 差异化）
13. AlloyDB 命名 & 性能宣称（厂商 benchmark 分层标注）

**全球分布式篇（P14–17）：Aurora Global / DSQL vs Spanner**
14. 分隔页
15. 全球分布式三方对标（真正对标 Spanner 的是 Aurora DSQL active-active，非单主的 Global）
16. 一致性机制 & SLA（Spanner TrueTime vs DSQL OCC；多区 SLA 都 99.999%）
17. Spanner 命名 & 强一致的代价（CAP=CP 系统；写延迟换全球强一致）
18. 总结：关键差异一览

## 关键数据（官方核实）

- **引擎覆盖**：RDS 6 种（含独有 Oracle / Db2 / MariaDB）vs Cloud SQL 3 种
- **HA SLA**：基础档打平 99.95%；Cloud SQL Enterprise Plus 99.99% 高一档；RDS 单实例 99.5% 兜底
- **存储上限**：RDS 64 TiB（Oracle/SQLServer 附加卷 256 TiB）；Cloud SQL 专用核 64 TB / 共享核 3 TB
- **只读副本**：RDS 每主实例最多 15 个（硬上限）；Cloud SQL 副本算实例、受项目配额（≤1000/项目），无 per-primary 固定上限
- **最高 IOPS**：RDS io2 Block Express 256,000 IOPS；Cloud SQL 随规格自动，无独立 provisioned IOPS
- **本地 NVMe**：RDS Multi-AZ DB cluster 用本地 NVMe 存 binlog/事务日志降写延迟（强制 d 系实例类）；Cloud SQL Enterprise Plus data cache 本地 SSD 只读缓存
- **全球分布式**：对标 Spanner 的是 Aurora DSQL（active-active，RPO=0）；Spanner 是 CP 系统靠 TrueTime，写延迟换全球强一致

## 数据来源

- AWS：docs.aws.amazon.com/AmazonRDS（Welcome / CHAP_Limits / CHAP_Storage / Concepts.DBInstanceClass.Types / USER_ReadRepl / multi-az-db-clusters-concepts / USER_Binlog.MultiAZ / rds-optimized-reads），aws.amazon.com/rds/sla · /rds/features/multi-az，docs.aws.amazon.com/aurora-dsql
- GCP：cloud.google.com/sql/docs（editions-intro / quotas / replication / about-read-pools），cloud.google.com/sql/sla，cloud.google.com/alloydb/docs/overview，cloud.google.com/spanner（sla / true-time-external-consistency）
- 一致性/CAP：Google Cloud 官方博客《Inside Cloud Spanner and the CAP Theorem》(Eric Brewer)；DSQL OCC/QP：Marc Brooker(AWS DSQL 首席工程师) 博客
- 云原生三层存储/列存装载/WAL Apply：墨天轮 modb.pro/db/445739（第三方，已标注）
- 命名解释：Wikipedia/社区共识（非官方逐字，已标注）

## 文件

- `rds_vs_cloudsql_ppt.py` — python-pptx 生成脚本
- `RDS_vs_CloudSQL.pptx` — 成品（18 页）
- `RDS_vs_CloudSQL.pdf` — PDF 预览

## 生成方式

```bash
python3 rds_vs_cloudsql_ppt.py            # 生成 pptx
soffice --headless --convert-to pdf RDS_vs_CloudSQL.pptx   # 转 PDF
```
