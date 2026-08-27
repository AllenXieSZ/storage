# Aurora MySQL Backup 费用验算

验证 Amazon Aurora（RDS）的 **backup 计费规则**：免费额度、超出计费单价，以及 **CloudWatch backup 指标是否与实际账单一致**。

## TL;DR 结论

1. **Aurora automated backup 免费额度 = 集群当前存储量的 100%**；超出部分按 **$0.021/GB-月**（us-east-2）计费。
2. **CloudWatch 的 `TotalBackupStorageBilled` 指标 = 计费依据**，与账单口径一致（Cost Explorer 的 `Aurora:BackupUsage`），差异仅来自"瞬时值 vs 月累计平均"。
3. **continuous backup（PITR）的保留期硬上限 = 35 天**；想保留一年只能靠**周期性快照**（snapshot，最长可 365 天甚至更久）。
4. **backup 费用相比实例费用几乎可忽略**：35 天 continuous backup 的测试集群每天仅 ~1-2 美分；真正大头是数据库实例本身。

## 计费规则（AWS 官方，us-east-2）

- **Automated backup（continuous / PITR）**：
  - 免费额度 = **集群当前分配存储量的 100%**（即"备份量 ≤ 库大小"时免费）
  - 超出免费额度部分：**$0.021/GB-月**
- **手动/AWS Backup 快照**：warm storage 同样 **$0.021/GB-月**
- **continuous backup 保留期上限 = 35 天**（PITR 硬限制）；要更长期只能用快照

## CloudWatch backup 指标（关键）

Aurora 集群维度（`DBClusterIdentifier`）下的 CloudWatch/RDS 指标：

| 指标 | 含义 |
|---|---|
| `BackupRetentionPeriodStorageUsed` | continuous backup（PITR 窗口内）的**总存储量** |
| `SnapshotStorageUsed` | 手动快照占用的存储量 |
| `TotalBackupStorageBilled` | **实际计费的 backup 量**（= 总量 − 免费额度）← 这个才是钱 |

> ⚠️ 查询坑：这些指标**刷新有延迟**，用 6 小时窗口可能拿不到数据点；拉长到 **1-2 天窗口 + period=86400** 才稳定取到最新值。

## 实测数据对比（本次验算）

**测试集群（35 天 continuous backup + 每日 DML 制造 log）：**

| 来源 | backup 计费量 | 换算日费 |
|---|---|---|
| CloudWatch `TotalBackupStorageBilled`（瞬时）| ~33 GB | ~$0.023/天 |
| Cost Explorer `Aurora:BackupUsage`（月累计平均）| ~9 GB-月 | ~$0.007/天 |

**为什么两者数字不同（但不矛盾）：**
- CloudWatch `TotalBackupStorageBilled` 是**当前时刻的瞬时计费量**（35 天窗口攒到现在的量）。
- Cost Explorer 的用量是**整月累计的平均值**——月初 backup 还没攒满、随时间增长，所以月平均低于当前瞬时值。
- **两者方向一致、量级吻合**，都指向"每天 1-2 美分"级别。CloudWatch `TotalBackupStorageBilled` 确实是账单计费依据。

**对照：保留期 1 天的小集群** → `TotalBackupStorageBilled = 0`（backup 量在免费额度内，$0）。

## 计算示例

```
TotalBackupStorageBilled = 33 GB (CloudWatch 当前值)
月费 = 33 GB × $0.021/GB-月 = $0.69/月
日费 = $0.69 / 30 ≈ $0.023/天

对比: 该集群实例本身 (db.r6g.xlarge) ≈ $205/月
→ backup 费用相对实例费用可忽略 (占比 <0.5%)
```

## 结论要点

- **Aurora backup 便宜到几乎可忽略**——除非 backup 量远超库大小（大量高频 DML 产生的变更日志 + 长保留期）。
- **监控 backup 成本看 CloudWatch `TotalBackupStorageBilled`**（集群维度），它与账单一致。
- **省钱重点不在 backup，而在实例规格**（db.r6g.xlarge 这类才是大头）。
- **一年期保留**：continuous backup 做不到（35 天上限），必须用**周期性快照**方案（如每周快照保留 365 天）。

## 查询命令参考

```bash
# CloudWatch 计费 backup 量 (集群维度, 用长窗口)
aws cloudwatch get-metric-statistics --namespace AWS/RDS \
  --metric-name TotalBackupStorageBilled \
  --dimensions Name=DBClusterIdentifier,Value=<cluster-id> \
  --start-time <2天前> --end-time <now> --period 86400 --statistics Average

# Cost Explorer 实际 backup 账单
aws ce get-cost-and-usage --time-period Start=<月初>,End=<明天> \
  --granularity MONTHLY --metrics UnblendedCost UsageQuantity \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Relational Database Service"]}}' \
  --group-by Type=DIMENSION,Key=USAGE_TYPE
# 找 USAGE_TYPE 里的 Aurora:BackupUsage
```

---

*验算日期：2026-08-26~27 · region us-east-2 · Aurora MySQL · 测试资源（集群/实例/AWS Backup plan/vault/DML cron）已于验算后全部清理。*
