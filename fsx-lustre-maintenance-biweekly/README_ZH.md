# FSx Lustre 运维窗口双周调度器

将 Amazon FSx for Lustre 每周运维窗口自动调整为**每两周执行一次**，通过 Lambda + EventBridge 实现。

## 背景

FSx for Lustre 运维窗口每周固定执行，无法调整频率。运维期间文件系统短暂不可用且内存缓存清除，导致运维后访问延迟升高。本方案实现隔周跳过。

## 工作原理

每个文件系统部署 2 个 Lambda + 2 条 EventBridge 规则（`rate(14 days)`）：

- **Skip Lambda**：运维窗口前 12h 触发，将 MW 设为 `原始值 − 24h`
- **Restore Lambda**：运维窗口后 12h 触发，将 MW 恢复为`原始值`

```
第 1 周（跳过）：
  Skip Lambda → MW 挪到前一天 → 原时间点无窗口 → 跳过
  Restore Lambda → MW 恢复原位

第 2 周（正常）：
  两个 Lambda 都不触发（14天周期还没到）
  MW 在原位 → 正常执行 maintenance

第 3 周 = 第 1 周，循环...
```

### 幂等性

Lambda 使用**绝对值设置**，原始运维窗口时间从 CSV hard code 到代码里：
- Skip Lambda：`MW = 原始值 − 24h`（固定目标值，不是相对偏移）
- Restore Lambda：`MW = 原始值`（固定目标值）
- MW 已经是目标值时不调用 UpdateFileSystem，直接返回
- **多次触发结果相同**，无副作用

### EventBridge 调度

使用 `rate(14 days)`，首次触发时间 = 规则创建时间。部署脚本在创建规则后**自动 invoke Skip Lambda 一次**，对齐首次跳过周期。

### 举例 — 运维窗口 = 周三 02:00 UTC（`3:02:00`）

| 阶段 | MW 值 | 说明 |
|---|---|---|
| 初始 | `3:02:00` (Wed 02:00) | 原始值 |
| Skip Lambda 执行后 | `2:02:00` (Tue 02:00) | MW 挪走，Wed 无窗口 → 跳过 |
| Restore Lambda 执行后 | `3:02:00` (Wed 02:00) | 恢复原位 |

## ⚠️ 部署时机（重要）

**必须在「上周刚完成 maintenance」后的那一周部署。**

原因：
1. AWS 要求运维窗口至少每 14 天命中一次，超过 14 天会强制执行
2. 部署时会立即 invoke Skip Lambda，跳过本周的 maintenance
3. 如果上周的 maintenance 也被跳过了 → 连续 2 周无 maintenance → 超过 14 天 → AWS 强制执行

正确时序：
```
上周：maintenance 正常执行 ✅
本周：部署 → Skip 跳过本周 ✅（距上次 maintenance ≤ 14 天）
下周：rate(14 days) 还没到 → maintenance 正常执行 ✅
再下周：rate(14 days) 到了 → Skip 跳过 ✅（距上次 ≤ 14 天）
```

错误时序：
```
上周：已经跳过了 maintenance ❌
本周：部署 → Skip 又跳过 → 连续 2 周无 maintenance → 超 14 天 → AWS 强制执行 ❗
```

> **来源**：[FSx Lustre User Guide — Maintenance Windows](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html)

## 前置条件

- Python 3.9+，已安装 `boto3`
- AWS 账号有 FSx Lustre 文件系统
- AWS CLI 已配置凭证

## 使用步骤

### 1. 创建 IAM 用户并附加权限

```bash
aws iam create-user --user-name fsx-mw-scheduler
aws iam create-access-key --user-name fsx-mw-scheduler

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" iam-policy.json > /tmp/iam-policy-resolved.json
aws iam put-user-policy \
  --user-name fsx-mw-scheduler \
  --policy-name fsx-mw-scheduler-policy \
  --policy-document file:///tmp/iam-policy-resolved.json

export AWS_ACCESS_KEY_ID=<your-key>
export AWS_SECRET_ACCESS_KEY=<your-secret>
```

### 2. 列出文件系统 → CSV

```bash
python3 fsx_mw_scheduler.py list --region us-east-2
```

输出：
```
✅ Wrote 2 FSx Lustre file systems to fsx_lustre_list.csv
   fs-02e88f8550a3572d3  mw-test-1       MW=3:02:00 (Wed 02:00 UTC)
   fs-0247683a1e4d5b957  mw-test-2       MW=5:18:30 (Fri 18:30 UTC)
```

> 编辑 CSV 删除不需要调整的文件系统。

### 3. 部署 Lambda + EventBridge

```bash
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

部署脚本会：
1. 创建 IAM 执行角色（共用）
2. 为每个 FS 创建 Skip + Restore 两个 Lambda（幂等，绝对值）
3. 为每个 Lambda 创建 `rate(14 days)` EventBridge 规则
4. **自动 invoke Skip Lambda 一次**，开始第一个跳过周期

## 测试结果

2 个 SCRATCH_2 文件系统（us-east-2），手动 invoke 验证完整周期：

### mw-test-1（MW = Wed 02:00 UTC / `3:02:00`）

| 阶段 | MW 值 | 说明 |
|---|---|---|
| 初始 | `3:02:00` | Wed 02:00 UTC |
| Skip 执行后 | `2:02:00` | **Tue 02:00** ← 跳过 |
| Restore 执行后 | `3:02:00` | **Wed 02:00** ← 恢复 |
| 再次 Skip（幂等验证） | `2:02:00` | 结果一致 ✅ |

Skip Lambda 返回：
```json
{"statusCode": 200, "body": "FSx fs-02e88f8550a3572d3 [skip]: MW changed from Wed 02:00 UTC to Tue 02:00 UTC (original=3:02:00)", "changed": true}
```

再次调用 Skip Lambda（已经是 Tue 02:00）：
```json
{"statusCode": 200, "body": "FSx fs-02e88f8550a3572d3 [skip]: MW is already 2:02:00, no change (idempotent)", "changed": false}
```

### mw-test-2（MW = Fri 18:30 UTC / `5:18:30`）

| 阶段 | MW 值 | 说明 |
|---|---|---|
| 初始 | `5:18:30` | Fri 18:30 UTC |
| Skip 执行后 | `4:18:30` | **Thu 18:30** ← 跳过 |
| Restore 执行后 | `5:18:30` | **Fri 18:30** ← 恢复 |

## 架构

```
EventBridge (rate 14 days)           EventBridge (rate 14 days)
     │                                    │
     ▼                                    ▼
 Skip Lambda                          Restore Lambda
 MW → original − 24h                  MW → original
 (幂等，绝对值)                        (幂等，绝对值)
     │                                    │
     ▼                                    ▼
 FSx UpdateFileSystem                 FSx UpdateFileSystem
```

### 每个文件系统创建的资源

| 资源 | 命名 | 用途 |
|---|---|---|
| Lambda | `fsx-mw-skip-{fs-id}` | MW → original − 24h |
| Lambda | `fsx-mw-restore-{fs-id}` | MW → original |
| EventBridge | `fsx-mw-skip-{fs-id}` | 14 天触发 Skip |
| EventBridge | `fsx-mw-restore-{fs-id}` | 14 天触发 Restore |
| IAM Role | `fsx-mw-lambda-role` | 共用（每账号 1 个） |

## 费用

- Lambda + EventBridge + IAM：基本为零（每 FS 每 14 天 2 次调用）

## 清理

```bash
FS_ID=fs-xxxxxxxxxxxx
REGION=us-east-2

for prefix in fsx-mw-skip fsx-mw-restore; do
  aws events remove-targets --rule "${prefix}-${FS_ID}" --ids "target-${FS_ID}" --region $REGION
  aws events delete-rule --name "${prefix}-${FS_ID}" --region $REGION
  aws lambda delete-function --function-name "${prefix}-${FS_ID}" --region $REGION
done

# 可选：删除共用角色和 IAM 用户
aws iam delete-role-policy --role-name fsx-mw-lambda-role --policy-name fsx-mw-lambda-policy
aws iam delete-role --role-name fsx-mw-lambda-role
```

## 文件

| 文件 | 说明 |
|---|---|
| `fsx_mw_scheduler.py` | 主脚本（list + deploy） |
| `iam-policy.json` | 操作用户 IAM 策略（替换 ACCOUNT_ID） |
| `lambda-execution-role-policy.json` | Lambda 执行角色策略 |
| `README.md` | 英文文档 |
| `README_ZH.md` | 中文文档（本文） |
