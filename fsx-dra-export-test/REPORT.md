# FSx Lustre DRA AutoExport 导出性能测试报告

**测试时间**: 2026-08-06 23:00 ~ 2026-08-07 00:18 UTC
**Region**: us-east-2 | **账号**: REDACTED_ACCOUNT | **执行者**: admin
**目标**: 测 FSx Lustre 经 DRA AutoExportPolicy 把 100GB 数据自动导出回 S3 的耗时与吞吐

## 测试方法
- 数据集: 100 目录 × 1024 文件 × 1MB = **102400 文件 = 100GB**（/dev/urandom，xargs -P32 并行 dd）
- 客户端: 1 台 **c5n.4xlarge**（AL2023，lustre-client 2.15.6），三组复用
- 关键顺序: 建FS → 建DRA(AutoExport开启) → 挂载 → **建DRA后再写数据** → 触发自动导出
- 完成判定: `aws s3 ls --recursive --summarize` 轮询，达 102400 个 1MB 文件对象且稳定
- ⚠️ S3 总对象数为 102501（102400 数据文件 + 101 个目录占位对象 data/ + dir000~dir099），实际数据文件均为 **102400**（100GB 精确 = 107374182400 字节）

## 三组对照表

| 组 | 容量(GB) | 吞吐档(MB/s/TiB) | 总吞吐(MB/s) | 写入Lustre耗时 | 写入吞吐(MB/s) | 导出耗时(首达102400) | 导出吞吐(MB/s) | 是否完成 |
|----|---------|-----------------|-------------|--------------|--------------|-------------------|--------------|--------|
| 组1 | 4800 | 125 | 600  | 95s | 1078 | **~349s** | **~293** | ✅ 完成 |
| 组2 | 4800 | 250 | 1200 | 96s | 1067 | **~117s** | **~875** | ✅ 完成 |
| 组3 | 9600 | 125 | 1200 | 88s | 1164 | **~111s** | **~922** | ✅ 完成 |

> 导出耗时取"S3 对象数首次达到 102400 个数据文件"的时间点（T1 - T0_end）。轮询间隔约 30-75s，为量级近似值，非秒级精确。

## 分析

### (a) 组1 vs 组2：吞吐档翻倍（125→250）对导出的影响
- 两组容量相同(4800GB)，仅吞吐档从 125 翻倍到 250（总吞吐 600→1200 MB/s）。
- 导出耗时 **349s → 117s（约缩短 66%，加速约 3 倍）**，导出吞吐 293 → 875 MB/s。
- 结论: **提高 PerUnitStorageThroughput 对 DRA 自动导出速度提升非常显著**。吞吐档翻倍带来了约 3 倍的导出加速，收益甚至超过线性——说明 600MB/s 档位下导出通道是明显瓶颈，1200MB/s 档位下瓶颈大幅缓解。

### (b) 组2 vs 组3：相同总吞吐(1200MB/s)下，提档 vs 加容量的差异
- 两组总吞吐均为 1200 MB/s。组2 = 4800GB×250档；组3 = 9600GB×125档。
- 导出耗时 **117s vs 111s，几乎持平**（组3 略快约 5%）；导出吞吐 875 vs 922 MB/s。
- 结论: **在相同总吞吐下，"提高吞吐档"与"增加容量"对 DRA 导出性能的影响基本等价**，差异在测量误差范围内。这说明 **DRA 自动导出的性能主要由文件系统"总吞吐能力"（= 容量 × 吞吐档）决定，而非单看容量或单看吞吐档**。用户可按成本/容量需求灵活选择两种方式凑到目标总吞吐。

### 总体观察
- 三组导出吞吐（293/875/922 MB/s）均**低于**各自标称总吞吐（600/1200/1200 MB/s）。原因：本测试为 **10 万个 1MB 小文件**，DRA 导出是逐文件元数据操作 + PUT，小文件场景受**元数据/请求速率**制约，达不到大文件顺序吞吐的理论峰值。若为大文件（如几百 MB~GB 级），导出吞吐会更接近标称值。
- 写入 Lustre 的吞吐（~1078-1164 MB/s）三组接近，受客户端（单台 c5n.4xlarge + /dev/urandom 生成速率）制约，未打满各 FS 的写入能力。

## 资源 ID 记录

| 资源 | ID |
|------|-----|
| EC2 客户端 (c5n.4xlarge) | i-REDACTED (公网 REDACTED_IP，已 terminate) |
| 组1 FS | fs-REDACTED (已删) |
| 组1 DRA | dra-REDACTED (已删) |
| 组2 FS | fs-REDACTED (已删) |
| 组2 DRA | dra-REDACTED (已删) |
| 组3 FS | fs-REDACTED (已删) |
| 组3 DRA | dra-REDACTED (已删) |
| SG | sg-REDACTED (lustre-test-sg) |
| Subnet | subnet-REDACTED (us-east-2a) |

所有资源已打 tag: `Project=fsx-dra-export-test, Owner=weiwei`。

## 清理状态
- ✅ EC2 已 terminate
- ✅ 3 个 FSx Lustre FS 全部删除完毕（describe 已返回空）
- ✅ 3 个 DRA 全部删除
- ✅ S3 导出数据保留（按要求待用户决定）：
  - s3://<BUCKET>/lustre-export-1/ → 102400 × 1MB
  - s3://<BUCKET>/lustre-export-2/ → 102400 × 1MB
  - s3://<BUCKET>/lustre-export-3/ → 102400 × 1MB

## 踩坑记录（重要）

1. **DRA 创建 `file-system-path /` 报 "Missing required parameters"**：用根路径 `/` 配合 AutoExportPolicy 一直报缺参数（试了带/不带 batch-import、带/不带 AutoImportPolicy 均失败）。**改用 `/export` 路径立即成功**。因此数据必须写到挂载点的 `/fsx/export/` 子目录（DRA 映射 `/export` ↔ `s3://.../lustre-export-N/`）。
2. **`--batch-import-meta-data-on-create false` 语法错误**：AWS CLI 布尔 flag 不接受 `false` 值，会报 `Unknown options: false`。要用 `--no-batch-import-meta-data-on-create`（不导入）或 `--batch-import-meta-data-on-create`（导入）。
3. **AL2023 lustre client repo 404**：官方 `fsx-lustre-client-repo-latest.noarch.rpm` for al2023 返回 404，但 **AL2023 自带 `lustre-client` 包**（`sudo dnf install -y lustre-client` → 2.15.6），modprobe 正常，挂载成功。
4. **S3 对象数会略超 102400（=102501）**：AutoExport 会为每个目录创建占位对象（data/ + dir000~dir099 = 101 个），故轮询判定要按"1MB 数据文件数=102400"或"总数≥102501 稳定"，不能死等 exactly 102400。
5. **DRA 删除耗时较长**：每个 DRA 删除约需 8-10 分钟（DELETING 状态持续），FS 删除也需 5-6 分钟，串行清理是整个测试的主要耗时项之一。
6. **FSx Lustre PERSISTENT_2 创建很快**：三组 FS 从 CREATING 到 AVAILABLE 仅 2-8 分钟。
