# AWS Storage Engineering Playbook

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![AWS](https://img.shields.io/badge/cloud-AWS-orange?logo=amazonaws)
![Lustre](https://img.shields.io/badge/HPC-Lustre-6f42c1)
![Prometheus](https://img.shields.io/badge/observability-Prometheus%20%7C%20Grafana-e6522c)

一线云存储工程实战合集 —— 涵盖 **性能基准测试、自建高性能文件系统、S3 归档分层、以及可观测性**。
从 EBS/S3 微基准，到 6PB 级 Lustre 预训练存储的自建与 HSM 归档，再到自研 node_exporter collector + Grafana 监控。

多数工具为 **纯 Python (boto3)** 或 shell，跨平台，通过 SSM 在 EC2 上执行、自动清理资源。

---

## 目录

### 📊 性能基准（Benchmarks）
| 项目 | 测什么 | 关键指标 |
|------|--------|---------|
| **[s3-benchmark](./s3-benchmark/)** | S3 Standard vs Express One Zone；上传/下载工具集（预签名、Transfer Acceleration、CloudFront 签名 URL、分片） | 延迟 (4KB–8MB)、吞吐 (1GB multipart/range)、IOPS |
| **[ebs-benchmark](./ebs-benchmark/)** | EBS 卷类型 (gp3 / io2 等) | IOPS、吞吐、延迟 (fio) |

### 🗄️ 高性能文件系统（HPC / Lustre）
| 项目 | 内容 |
|------|------|
| **[self-built-lustre-raid1](./self-built-lustre-raid1/)** | 自建 Lustre + mdadm RAID1 全套：部署 / 性能 / OST 故障 / RAID1 改造 / 换盘 / 扩展测试 / 无 RAID EBS 丢失测试 |
| **[fsx-lustre-warmup](./fsx-lustre-warmup/)** | FSx Lustre warmup（S3→Lustre）脚本，含 v2 快速识别版（`lfs find -L released`，~40x 加速） |
| **[lustre-hsm-s3-guide](./lustre-hsm-s3-guide/)** | 开源 Lustre 通过 HSM (Estuary copytool) 归档到 S3 的完整部署指南（含源码补丁、systemd 自启） |
| **[fsx-lustre-efa-diag](./fsx-lustre-efa-diag/)** | FSx Lustre + EFA 一键诊断脚本 + 分层排障 SOP：四层自动检查（EFA设备/libfabric/LNet-Lustre/AWS基础设施），自动比对客户端 vs FSx AZ，定位 OST DISCONN / CREATE_AH err-22 / 内核漂移 |

### 📈 可观测性（Observability）
| 项目 | 内容 |
|------|------|
| **[node-exporter-ebsnvme](./node-exporter-ebsnvme/)** | 自研 Prometheus node_exporter collector，采集 EBS NVMe 详细性能统计（IOPS/吞吐/延迟直方图 + IOPS/吞吐限流时间）。已提交上游 prometheus/node_exporter |
| **[grafana-dashboards](./grafana-dashboards/)** | Disk Characteristics dashboard，集成 `node_ebs_*` 指标，可视化磁盘性能/饱和度/EBS 限流 |

### 🖥️ GPU / 分布式训练（Training）
| 项目 | 内容 |
|------|------|
| **[training-sample](./training-sample/)** | 8×H100 (p5.48xlarge) 上从零训练 ViT-Huge 632M 图像分类的极简样例（PyTorch DDP + HF Trainer，checkpoint 存 FSx Lustre）。36 行脚本 + 完整 README，含续训/混合精度/NCCL NVLS 说明 |

### ☁️ 基础设施 & 样例
| 项目 | 内容 |
|------|------|
| **[aws-backup-tf](./aws-backup-tf/)** | 跨账号 AWS Backup 的 Terraform（management / member account） |

---

## Benchmark 工具怎么跑

1. 在本地跑脚本
2. 脚本在 AWS 里开 EC2 + 存储资源
3. 通过 **SSM** 在 EC2 上执行基准（无需 SSH）
4. HTML + JSON 报告下载到本地
5. **资源自动清理**（即使崩溃/中断也会清）

```bash
pip install boto3
cd s3-benchmark && python run_benchmark.py      # S3 基准
cd ebs-benchmark && python ebs-bench.py --region us-east-2   # EBS 基准
```

## 亮点主题
- **反直觉发现**：小文件密集场景下，NFS 类存储比本地 EBS 慢约 50 倍（元数据 round-trip 瓶颈，非带宽）
- **6PB Lustre 预训练存储 de-risk**：warmup 速率由 MDT 并行度决定（非 metadata IOPS）；单客户端吞吐 = OSS 数 × single-flow 上限
- **自建 Lustre HSM → S3**：开源 copytool 适配 Lustre 2.15.8 + SigV4 + restore 数据修复
- **EBS NVMe 可观测性**：直接从 NVMe log page 读卷级 IOPS/吞吐限流信号，接入 Prometheus
- **训练存储实战**：8×H100 分布式训练用 FSx Lustre 存 checkpoint；踩坑教训——Lustre 静默掉载会让 checkpoint 回退写根盘并撑爆（用 `stat -f` 校验挂载）
- **EFA Lustre 排障方法论**：EFA 客户端必须与 FSx 同 AZ（跨 AZ → CREATE_AH err-22 → OST 全 DISCONN）；一次只改一个变量；OST 状态看 `ost_server_uuid` 非 `lnetctl peer state`

## 前提
- Python 3.8+ / `boto3`
- AWS 凭证（benchmark 工具需较高权限）

## License
MIT
