# AWS vs GCP 文件存储服务对比 (PPT)

**整理日期**：2026-08-02
**数据来源**：AWS/GCP 官方文档（performance/service-tiers/service-levels/what-is）+ GCP 官方博客（Parallelstore GA 公告）+ DAOS/NetApp 官方，2026-08。

7 页 PPT，覆盖 **4 组"同类可比"的 AWS↔GCP 文件存储配对**。

## 文件
- `aws_gcp_file_storage_compare.pptx` — 可编辑 PPT
- `aws_gcp_file_storage_compare.pdf` — PDF 预览
- `make_file_storage_ppt.py` — 生成脚本（python-pptx, NetApp 风格）

## 对比内容

| # | AWS | GCP | 类别 |
|---|---|---|---|
| ① | Amazon EFS | Filestore | 基础托管 NFS |
| ② | FSx for Lustre | Managed Lustre (DDN) | 并行 FS - Lustre 系 |
| ②b | (FSx Lustre 最接近) | Parallelstore (Intel DAOS) | 并行 FS - 对象/DAOS 系 |
| ③ | FSx for NetApp ONTAP | NetApp Volumes | 企业级 ONTAP |

## 关键结论

1. **EFS vs Filestore**：EFS 免预置全弹性、NFSv4、单FS吞吐上限更高(60GiBps)；Filestore 分层清晰(Zonal/Regional/Enterprise)。
2. **Lustre 系**：对象存储集成是关键差异——AWS HSM 惰性加载(数据>>容量省钱) vs GCP 批量传输(全量装进,训练零抖动)；AWS burst 衰减 / GCP 恒定吞吐；AWS 元数据可独立预置。
3. **Parallelstore (DAOS)**：⚠️ **GCP 有两个并行文件系统**——Managed Lustre(Lustre内核) 和 Parallelstore(Intel DAOS内核)，是两个不同产品。Parallelstore 全分布式元数据+用户态RDMA，主打小文件/元数据/AI训练(0.3ms/300万读IOPS @100TiB)；AWS 无直接对标。
4. **NetApp ONTAP**：同源→功能高度重合(快照/克隆/SnapMirror/FlexGroup)；最大区别 AWS 开放多 HA pair scale-out(Single-AZ 最多12,用户可配) vs GCP HA 托管黑盒。

## ⚠️ 数据确定性标注
- Parallelstore 规格(100TiB/115GiB·s/300万读IOPS/0.3ms)来自 GCP 官方博客 GA 公告的"当前最大部署"，因 docs 页当前重定向到 Managed Lustre，未取到完整各档位表。
- 部分性能为官方文档值或实测，具体以实际 region/配置为准。
- AWS FSx ONTAP 精确 IOPS/吞吐档位数字、两家精确价格未在本 PPT 展开。

*配套仓库其他 Lustre 深度文档：`aws-fsx-vs-gcp-managed-lustre/`、`fsx-lustre-throughput-change/`、`fsx-lustre-fis-network-latency/`、`fsx-lustre-pcc-crash/`。*
