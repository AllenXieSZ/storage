# Aurora Backup 费用公式验算与实测对比

> 目的：用真实 Aurora 集群 + 每日 20GB DML 负载，把 **Aurora 备份费用公式** 与 **CloudWatch 实测容量** 及 **Cost Explorer 实际账单** 三方对比验算。
>
> 环境：AWS us-east-2 (Ohio) · Aurora MySQL 8.0 · 建于 2026-08-04
>
> ⚠️ 所有公式与计费规则均来自 AWS 官方文档（链接见文末），非推测。

---

## 1. 测试环境

| 组件 | 配置 |
|---|---|
| Aurora 集群 | `aurora-backup-test`（引擎 `8.0.mysql_aurora.3.12.0`，实例运行 8.0.44） |
| 实例规格 | `db.t3.medium`（Aurora 最小规格，2 vCPU / 4 GB） |
| 存储配置 | Aurora Standard（存储自动伸缩，**无 gp3/固定容量概念**） |
| 集群自带备份 | Automated backup 保留 **7 天**（continuous/PITR） |
| 每日负载 | cron 每天 UTC 05:00 跑 **~20 GB DML**（INSERT+DELETE 循环，模拟 transaction log，表本身不膨胀） |
| AWS Backup Plan | `aurora-backup-test-plan`，专用 vault `aurora-backup-test-vault` |
| — Rule 1 | Continuous backup（PITR），每天，保留 **35 天**（continuous 的 AWS 硬上限） |
| — Rule 2 | Weekly snapshot，每周一，保留 **365 天** |

> **关于 gp3/500GB**：Aurora 使用自研分布式存储层，存储按 10GB 增量自动伸缩，无法指定 gp3 或固定 500GB。若需 gp3/500GB 固定卷，那是标准 RDS 而非 Aurora。本测试为纯 Aurora。
>
> **关于 continuous backup 保留一年**：AWS Backup 的 continuous backup（PITR）**最长只能保留 35 天**（AWS 硬限制）。因此"保留一年"由 weekly snapshot（保留 365 天）实现，continuous rule 设为 35 天上限。

---

## 2. Aurora 备份计费模型（官方，已核实）

Aurora 维护两类备份，计费方式**不同**：

### 2.1 Automated (Continuous) Backup —— 增量、可 PITR

- **增量存储**：只存保留期内的所有变更（change records），用于 restore 到窗口内任意时间点。
- **免费额度** = 最新集群卷大小（CloudWatch `VolumeBytesUsed`）。
- **保留期 = 1 天时完全免费**。
- **计费上限**：billed usage 永远 **不超过**「集群卷大小 × 保留天数」的累计值。
  > 例：保留 7 天、卷稳定 100GB → automated backup 计费量上限 = 100×7 = 700GB。
- 变更越多，automated backup 越大；变更移出保留窗口后又会缩小。

### 2.2 Snapshot Storage —— 全量、非增量

- **DB cluster snapshot 永远是全量**，大小 = 创建时刻的卷大小。
- **无论手动还是通过 AWS Backup plan 创建，Aurora 都视为 manual snapshot。**
- **在 automated backup 保留期内的 snapshot 免费**；**超出保留期后**按 GB-月计费。

### 2.3 AWS Backup 与 Aurora 原生备份的映射（关键）

| AWS Backup 概念 | Aurora 侧等价物 | 计费 |
|---|---|---|
| Continuous backup（PITR rule） | Aurora **automated backup** | 走 `BackupRetentionPeriodStorageUsed − 免费额度` |
| Periodic snapshot（weekly rule） | Aurora **manual snapshot** | 保留期内免费，超出后 GB-月计费 |

> 官方原文：*"Amazon RDS and Aurora continuous backups don't incur higher costs compared with snapshot backups because AWS charges you for backup storage in both cases."* — continuous 备份**不比** snapshot 贵，两者都按 backup storage 计费。
>
> **重要**：AWS Backup 对 Aurora **没有独立的 warm-storage SKU**（pricing API 中 us-east-2 只有 air-gapped vault 变体 `WarmStorage-ByteHrs-Aurora-LAGV` = $0.0242/GB-月）。普通 vault 里的 Aurora 备份**直接走 Aurora backup storage 计费**，即 **$0.021/GB-月**（超出免费额度部分）。

---

## 3. 费用公式

### 3.1 单价（us-east-2，官方）

```
Aurora backup storage 超额单价 = $0.021 / GB-月
（air-gapped vault: $0.0242 / GB-月）
```

### 3.2 总费用公式

```
月度备份费用 = TotalBackupStorageBilled(GB) × $0.021

其中 TotalBackupStorageBilled =
    BackupRetentionPeriodStorageUsed          （automated/continuous 增量总量）
  + SnapshotStorageUsed                        （超出保留期的 snapshot 全量之和）
  − FreeTier                                   （= 最新 VolumeBytesUsed，集群卷大小）
```

三个量都是 CloudWatch 指标（`AWS/RDS` namespace，按 `DBClusterIdentifier` 维度，每日一个数据点）：

| CloudWatch 指标 | 含义 |
|---|---|
| `VolumeBytesUsed` | 集群实际卷大小（= 免费额度基准） |
| `BackupRetentionPeriodStorageUsed` | automated backup 增量总量（**未减免费额度**） |
| `SnapshotStorageUsed` | 超出保留期的 manual snapshot 全量之和（每快照一个数据点） |
| `TotalBackupStorageBilled` | 实际计费量 = 上面两者之和 − 免费额度 |

### 3.3 本测试的预期结构

```
自带 7天 automated backup (continuous):
    每天 20GB DML → change records 累积
    保留 7 天 → BackupRetentionPeriodStorageUsed ≈ Σ(7天内变更量)
    计费上限 = VolumeBytesUsed × 7
    billed_automated = max(0, BackupRetentionPeriodStorageUsed − VolumeBytesUsed)

AWS Backup continuous rule (35天 PITR):
    与集群 automated backup 同源计费，不额外重复收费

AWS Backup weekly snapshot (保留365天):
    每周一个全量 snapshot，大小 ≈ 当时 VolumeBytesUsed
    保留期(7天)内免费，超出后计费
    billed_snapshot = Σ(超期快照大小)
    52 周保留 → 稳态约 52 个快照在计费（各 ≈ 卷大小）

月度总费用 ≈ (billed_automated + billed_snapshot) × $0.021
```

---

## 4. 实测数据（滚动更新）

### 4.1 初始状态（2026-08-04，环境刚建成，DML 尚未运行）

| 指标 | 值 |
|---|---|
| `VolumeBytesUsed`（集群卷） | 274,251,776 B ≈ **0.255 GB** |
| `BackupRetentionPeriodStorageUsed` | 无数据点（新建，指标未发布） |
| `SnapshotStorageUsed` | 无（保留期内 snapshot 免费） |
| `TotalBackupStorageBilled` | 无数据点（尚未产生计费） |
| PITR 窗口 | 04:53 → 05:40 UTC（约 47 分钟，正在积累） |
| AWS Backup recovery points | 1 个（on-demand 测试快照，COMPLETED） |

> 初始库为空，备份量 < 免费额度，**当前计费 = $0**。需等每日 20GB DML 跑几轮后才能观测到有意义的计费量。

### 4.2 实测 vs 公式对比表（待回填）

> 由 cron 每天自动采集 CloudWatch 指标 + Cost Explorer 实际费用，回填下表。CE 数据有 24–48h 延迟。

| 日期 | VolumeBytesUsed (GB) | BackupRetentionStorageUsed (GB) | SnapshotStorageUsed (GB) | TotalBackupStorageBilled (GB) | 公式算费用 ($/月) | CE 实际费用 ($) | 偏差 |
|---|---|---|---|---|---|---|---|
| 2026-08-04 | 0.255 | — | — | 0 | $0.00 | — | — |
| 2026-08-04 (采集) | 0.2554 | — | — | — | $0.00 | $0 | — |
| 2026-08-05 | 1.2436 | 0.0000 | — | 0.0000 | $0.00 | $0 | 0（均 $0，一致） |
| _(待采集)_ | | | | | | | |

> **2026-08-04 采集简评**：卷大小 0.2554 GB（较建成时 0.255 GB 基本持平，DML 首轮 05:00 UTC 已跑但表本身不膨胀，符合设计）。`BackupRetentionPeriodStorageUsed`/`SnapshotStorageUsed`/`TotalBackupStorageBilled` 三项 CloudWatch 指标**仍无数据点**——新建集群的备份计费指标发布有延迟（通常需 1–2 天首次出现），CE 实际费用 $0（备份量 < 免费额度，且账单数据有 24–48h 延迟）。**当前无法做公式 vs 实测对比**，需等指标发布 + 每日 20GB DML 累积几轮后才有有意义的计费量。
>
> **2026-08-05 采集简评**：卷大小从 0.2554 GB 涨到 **1.2436 GB**（+~1 GB）——这是 08-05 05:00 UTC 那轮 20GB DML 后，Aurora 卷高水位增长的体现（虽然表逻辑上不膨胀，但存储层高水位不回缩）。关键进展：`BackupRetentionPeriodStorageUsed` 首次出现数据点（0.0000 GB），说明备份计费指标已开始发布。`TotalBackupStorageBilled = 0` 且 CE 实际费用 = $0，**公式费用 vs CE 实测一致（均为 $0），偏差 0**。原因：当前 automated backup 增量量仍远小于免费额度（= VolumeBytesUsed 1.24 GB），且尚无超期 snapshot。需继续累积几轮 DML + 等 weekly snapshot（首个周一 08-10）超出 7 天保留期后，才会出现非零计费量做真正的公式验算。

---

## 5. 采集方法（可复现）

### 5.1 CloudWatch 备份指标

```bash
# 集群卷大小（= 免费额度）
aws cloudwatch get-metric-statistics --region us-east-2 \
  --namespace AWS/RDS --metric-name VolumeBytesUsed \
  --dimensions Name=DBClusterIdentifier,Value=aurora-backup-test \
  --start-time <T-1d> --end-time <now> --period 86400 --statistics Maximum

# automated backup 增量总量（未减免费额度）
... --metric-name BackupRetentionPeriodStorageUsed ...

# 超期 snapshot 全量之和
... --metric-name SnapshotStorageUsed ...

# 实际计费量（三者综合）
... --metric-name TotalBackupStorageBilled ...
```

### 5.2 Cost Explorer 实际费用

```bash
aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=<YYYY-MM-01>,End=<YYYY-MM-DD> \
  --granularity DAILY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE_GROUP","Values":["Aurora: Backup Storage"]}}'
# 或按 USAGE_TYPE 过滤 *BackupUsage* / *AWS Backup*
```

---

## 6. 参考文档（官方）

- Aurora backup storage 计费与 CloudWatch 指标：
  https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-storage-backup.html
- Aurora pricing（backup storage 免费额度 = 100% 集群大小，超出 $0.021/GB-月）：
  https://aws.amazon.com/rds/aurora/pricing/
- AWS Backup pricing：
  https://aws.amazon.com/backup/pricing/
- AWS Backup 对 RDS/Aurora 的备份类型映射（continuous=automated, periodic=manual snapshot）：
  https://docs.aws.amazon.com/aws-backup/latest/devguide/rds-backup.html
- 优化 RDS/Aurora AWS Backup 费用（continuous 不比 snapshot 贵）：
  https://repost.aws/knowledge-center/backup-optimize-costs-rds-aurora

---

_文档由自动化测试环境生成，实测数据滚动更新。最后更新：2026-08-05（自动采集）_
