# AWS S3 vs GCP Cloud Storage (GCS) 对比 (PPT)

**日期**：2026-07-25
**数据来源**：AWS S3 / GCP Cloud Storage 官方文档 + 官方定价，基于最新官方文档核实。

## 文件
- `S3_vs_GCS.pptx` — 可编辑 PPT
- `S3_vs_GCS.pdf` — PDF 预览

## 说明
两家对象存储服务对比（存储类别、一致性、性能、定价、生命周期、**访问控制/IAM** 等）。

**2026-08-24 更新**：新增第 12 页「⑫ 访问控制 & IAM 对比」，补齐权限维度。核心点：
- S3 有「基于资源的 Bucket Policy」可直接按前缀 `bucket/prefix/*` 授权；
- GCS 无 bucket policy，前缀级授权改用 **IAM Conditions** 的 `resource.name` 前缀条件（官方支持，机制不同，非 S3 那种 policy）。
- 生成脚本：`add_iam_slide.py`（在现有 pptx 上追加该页，保持原 NetApp/AWS 风格）。

⚠️ 本 README 仅为文件索引；PPT 具体各页数据以 PPT 内容为准（生成时基于官方文档）。如需核对某项具体数字，建议对照 AWS S3 / GCP Cloud Storage 官方最新文档，因对象存储的存储类别、定价、限额会随时间更新。
