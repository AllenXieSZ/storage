# AWS EBS vs GCP Hyperdisk 对比 (PPT)

**日期**：2026-07-24
**数据来源**：AWS/GCP 官方文档（EBS volume types / Hyperdisk docs）+ 官方定价，均基于最新官方文档核实。

## 文件
- `EBS_vs_Hyperdisk.pptx` — 可编辑 PPT
- `EBS_vs_Hyperdisk.pdf` — PDF 预览

## 核心结论（已核实官方文档）

- **性能修改冷却期（重要，纠正过旧信息）**：
  - **AWS EBS**：6 小时冷却期已于 2026-01-15 取消。现规则=一次修改完成后可立即发起下一次，24 小时滚动窗口内每卷最多 4 次修改。
  - **GCP Hyperdisk**：反而有冷却期——Hyperdisk ML 每 6 小时改一次；其它所有类型（Balanced/Extreme/Throughput/HA）每 4 小时改一次。
  - → 在"修改性能"上 **AWS EBS 现在比 GCP Hyperdisk 更灵活**。

- **单卷性能上限**：GCP 更高——Extreme 350K IOPS/5000 MiB/s > EBS io2 256K/4000 MiB/s；通用盘 Balanced 160K IOPS > gp3 80K。

- **持久性(durability)**：GCP 各等级 ≥ AWS；通用盘高 2-3 个数量级（gp3/gp2 99.8-99.9% vs Balanced >99.999%）。

- **撕裂写保护(Torn Write Protection)**：两家都有（非 GCP 独有）——AWS 16KiB 原子写(2022起)，GCP 128KB 原子写。

- **价格**：通用盘两家几乎同价；GCP Extreme 中低 IOPS 段更便宜。具体以官方 Calculator/SKU 为准。

> 详细数据见 MEMORY.md 的 "AWS EBS vs GCP Hyperdisk" 章节。
