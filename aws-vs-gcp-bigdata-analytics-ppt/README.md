# AWS vs GCP 大数据/分析产品对比 PPT

14 页对比演示文稿，NetApp 风模板，AWS 橙 / GCP 蓝双列对照。覆盖 **10 大类别 + 架构总览 + 改名提示 + 选型总结**。**每条优缺点/定位均基于 AWS/GCP 官方文档核实**（docs.aws.amazon.com / cloud.google.com），不确定处诚实标「待确认」，绝不臆造。

## 内容结构（14 页）

1. 封面
2. 总览：两种架构哲学（AWS 多而全 purpose-built vs GCP 少而精 serverless 为主）
3. ⚠️ 4 个近期改名（已核实官方文档，避免用旧名踩坑）
4. **数据仓库** — Amazon Redshift(含 Serverless) vs Google BigQuery
5. **交互式查询** — Amazon Athena vs BigQuery 外部表 / BigLake
6. **托管 Spark/Hadoop** — Amazon EMR vs Managed Service for Apache Spark(原 Dataproc)
7. **流式处理引擎** — Kinesis + Managed Flink vs Dataflow(Apache Beam)
8. **消息/事件摄取** — Kinesis / Amazon MSK vs Pub/Sub
9. **ETL/数据集成** — AWS Glue vs Cloud Data Fusion
10. **工作流编排** — Amazon MWAA vs Managed Airflow(Composer Gen3)
11. **BI/可视化** — Amazon Quick Sight vs Looker / Looker Studio
12. **搜索/日志分析** — Amazon OpenSearch vs GCP(无原生对标)
13. **湖仓/表格式** — Amazon S3 Tables vs BigQuery Apache Iceberg managed tables
14. 总结：一句话决策指南

## 4 个近期改名（已核实，避免用旧名）

| 旧名 | 新名 |
|---|---|
| Dataproc | Google Cloud Managed Service for Apache Spark |
| QuickSight | Amazon Quick Sight（隶属 Amazon Quick AI 套件）|
| Cloud Composer | Managed Airflow (Gen3) |
| BigLake Iceberg tables | Apache Iceberg managed tables |

## 核心结论

- **GCP** = 少而精、serverless 为主，BigQuery 一个平台包揽多数分析，追求零运维 + 内建 AI。
- **AWS** = 多而全、purpose-built，每类负载一个专门服务，组合灵活、生态广度更强。
- **AWS 独有强项**：搜索/日志（OpenSearch，GCP 无原生对标）、托管 Kafka（MSK）、开放中立的托管 Iceberg 湖（S3 Tables）。
- **GCP 独有强项**：数仓（BigQuery）、批流一体（Dataflow/Beam）、BI 语义层（Looker/LookML）。

## 文件

- `aws_gcp_bigdata_ppt.py` — python-pptx 生成脚本（NetApp 风模板）
- `aws_gcp_bigdata_compare.pptx` — 演示文稿
- `aws_gcp_bigdata_compare.pdf` — PDF 版

## 生成方式

```bash
pip install python-pptx
python3 aws_gcp_bigdata_ppt.py
# 转 PDF: soffice --headless --convert-to pdf aws_gcp_bigdata_compare.pptx
```

> 数据基于 2026-08 官方文档，产品特性/计费随更新变化，以官方最新为准。标「待确认」项做深度选型时建议再查最新计费/配额页。
