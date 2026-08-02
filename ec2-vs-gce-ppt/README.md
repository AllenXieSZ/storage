# AWS EC2 vs GCP Compute Engine 对比 (PPT)

**日期**：2026-08-02
**数据来源**：AWS / GCP 官方文档 · What's New · Blog · 各自 SLA/定价页，均基于最新官方文档核实。
**风格**：NetApp 风模板（16:9），AWS 橙 / GCP 蓝双列对照。

## 文件
- `EC2_vs_GCE.pptx` — 可编辑 PPT（10 页）
- `EC2_vs_GCE.pdf` — PDF 预览

## 页面结构
1. 封面
2. 机型分类（通用/计算/内存/加速/存储/HPC/可突发）
3. 底层处理器与单机规格（Intel/AMD/自研 ARM/AI 芯片 + 内存/存储/网络上限）
4. 计费与折扣（SUD / CUD / 自定义机型）
5. Live Migration（热迁移）
6. 硬件卸载 Nitro vs Titanium
7. 放置策略 & 镜像（placement + AMI / Machine Image / Snapshot）
8. 单实例可用性 SLA
9. 业界评价 / 各自短板（三色分层：官方事实 / 业界共识 / 主观感觉）
10. 总结

## 核心结论（均查官方文档核实）

- **单实例 SLA**：AWS EC2 = **99.5%**（约 3.6h/月停机）；GCP CE = **99.9%**（普通）/ **99.95%**（内存优化，约 21.6min/月）。多 AZ/Zone 两家都 99.99%。
  - 来源：aws.amazon.com/compute/sla（Last Updated 2022-05-25）· cloud.google.com/compute/sla

- **Live Migration**：**两家都支持**。
  - AWS：Dedicated Hosts 有 "Live migration host maintenance"（24h 内自动热迁不停机）；2025-05 起无本地盘的 Nitro 实例默认开启 customer-initiated reboot migration。有本地实例存储的老机型(C1/C3/D2/I2/M1/M2/M3/R3/X1)不支持热迁。
  - GCP：所有普通 VM 默认 MIGRATE，覆盖面更广、体感更透明。
  - 差异在**覆盖面/默认程度**，不是"有没有"。

- **硬件卸载**：AWS Nitro（2017 起全线标配，网络 400G+，裸金属成熟）vs GCP Titanium（含 Intel IPU，网络 200G，Hyperdisk Extreme 500K IOPS/实例，官方自述）。

- **机型灵活性**：GCP 独有自定义机型（Custom Machine Types）+ 自动持续折扣 SUD（最高 20-30%，无需承诺）；AWS 机型数量多、Graviton ARM 生态最成熟，但无自动折扣（靠 Savings Plans/RI）。

- **放置策略**：AWS 三模式（cluster/spread/partition）更细；GCP 两模式（compact/spread）+ workload policy。

- **镜像**：AWS 用 AMI 统一；GCP 分 Image / Machine Image / Snapshot 三层，整机克隆语义更清晰。

- **超大内存**：AWS High Memory 单机达 24TB（SAP HANA 场景领先）；GCP C4 最高 1.5TB DDR5。

## 短板校验（已剔除过时旧信息）

- ❌ "GCE 不支持 Windows" — **证伪**：GCP 官方有完整 Windows Server / SQL Server / BYOL / GKE Windows 支持。
- ❌ "GCP region 远少于 AWS" — **已反转**：官方最新 GCP = 43 region / 130 zone ≥ AWS = 39 region / 123 AZ。
  - 来源：aws.amazon.com/about-aws/global-infrastructure · cloud.google.com/about/locations（2026-07）

> 第三方观点仅作参考；PPT 中短板项按可信度分三层标注（官方事实 / 业界共识 / 主观感觉）。
