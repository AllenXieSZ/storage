# FSx Lustre 运维窗口双周调度器

将 Amazon FSx for Lustre 每周运维窗口自动调整为**每两周执行一次**，通过 Lambda + EventBridge 实现。

## 背景

FSx for Lustre 运维窗口每周固定执行，无法调整频率。运维期间文件系统短暂不可用且内存缓存清除，导致运维后访问延迟升高。本方案实现隔周跳过。

## 工作原理

每个文件系统部署 2 个 Lambda + 2 种 EventBridge 触发规则：

- **Skip Lambda**：将 MW 设为 `原始值 − 24h`（绝对值，幂等）
- **Restore Lambda**：将 MW 恢复为`原始值`（绝对值，幂等）

### 触发调度

| 规则 | 类型 | 用途 |
|---|---|---|
| `fsx-mw-skip-init-{fs-id}` | EventBridge **Scheduler** `at()` | 首次 skip，精确对齐到下一个 MW−12h UTC 时间点，触发后自动删除 |
| `fsx-mw-restore-init-{fs-id}` | EventBridge **Scheduler** `at()` | 首次 restore，精确对齐到下一个 MW+12h UTC 时间点，触发后自动删除 |
| `fsx-mw-skip-{fs-id}` | EventBridge **Rules** `rate(14 days)` | 后续周期，每 14 天触发一次 skip |
| `fsx-mw-restore-{fs-id}` | EventBridge **Rules** `rate(14 days)` | 后续周期，每 14 天触发一次 restore |

```
第 1 周（跳过）：
  at() 首次触发 Skip Lambda（MW−12h）→ MW 挪到前一天 → 原时间点无窗口 → 跳过
  at() 首次触发 Restore Lambda（MW+12h）→ MW 恢复原位

第 2 周（正常）：
  无触发（at() 已自动删除，rate(14 days) 还没到）
  MW 在原位 → 正常执行 maintenance

第 3 周（跳过）：
  rate(14 days) 触发 Skip + Restore → 同第 1 周
  ...循环
```

### 为什么用两种规则？

- **EventBridge Rules 的 `rate()` 不支持指定首次触发时间**：首次触发 = 规则创建时间，无法对齐到 MW±12h
- **EventBridge Rules 不支持 `at()` 表达式**（实测报 `ValidationException`）
- **EventBridge Scheduler 支持 `at()`**（精确到秒）+ `ActionAfterCompletion=DELETE`（触发后自动清理）
- 所以：Scheduler `at()` 负责首次精确对齐，Rules `rate(14 days)` 负责后续周期

### 幂等性

Lambda 使用**绝对值设置**，原始运维窗口时间从 CSV hard code 到代码里：
- Skip Lambda：`MW = 原始值 − 24h`
- Restore Lambda：`MW = 原始值`
- MW 已经是目标值时不调用 UpdateFileSystem，直接返回
- 多次触发结果相同，无副作用

### 所有时间均为 UTC

FSx Lustre MW 时区固定为 UTC，EventBridge Scheduler/Rules 也使用 UTC，天然对齐。

## ⚠️ 部署时机（重要）

**必须在「上周刚完成 maintenance」后的那一周部署。**

原因：部署后首次 at() 会在下一个 MW−12h 跳过本周 maintenance。如果上周也被跳过 → 连续 2 周无 maintenance → 超 14 天 → AWS 强制执行。

> **来源**：[FSx Lustre User Guide — Maintenance Windows](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html)
> *至少每 14 天必须命中一次运维窗口，否则 AWS 强制执行。*

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

> 编辑 CSV 删除不需要调整的文件系统。

### 3. 部署 Lambda + EventBridge

```bash
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

部署后 MW **不会立即改变**——等 at() 规则在精确时间点触发后才会改。

### 4. 验证（手动 invoke 测试）

```bash
# 测试 skip
aws lambda invoke --function-name fsx-mw-skip-fs-xxxx --region us-east-2 /tmp/out.json
cat /tmp/out.json

# 检查 MW 是否变了
aws fsx describe-file-systems --file-system-ids fs-xxxx --region us-east-2 \
  --query 'FileSystems[0].LustreConfiguration.WeeklyMaintenanceStartTime' --output text

# 测试 restore
aws lambda invoke --function-name fsx-mw-restore-fs-xxxx --region us-east-2 /tmp/out.json
cat /tmp/out.json

# 测试幂等（再 invoke 一次 skip，应返回 changed=false）
aws lambda invoke --function-name fsx-mw-skip-fs-xxxx --region us-east-2 /tmp/out.json
cat /tmp/out.json
```

## 测试结果

2 个 SCRATCH_2 文件系统（us-east-2），2026-11-18 实测。

### mw-test-1（MW = Wed 02:00 UTC / `3:02:00`）

| 操作 | MW 变化 | Lambda 返回 |
|---|---|---|
| 手动 invoke skip | `3:02:00` → `2:02:00` | `changed: true` |
| 再次 invoke skip（幂等） | `2:02:00` 不变 | `changed: false` |
| invoke restore | `2:02:00` → `3:02:00` | `changed: true` |

Scheduler at() 规则：
- skip-init: `at(2026-11-24T14:00:00)` — 下周二 14:00 UTC（MW 前 12h）
- restore-init: `at(2026-11-18T14:00:00)` — 今天 14:00 UTC（MW 后 12h）

### mw-test-2（MW = Fri 18:30 UTC / `5:18:30`）

Scheduler at() 规则：
- skip-init: `at(2026-11-20T06:30:00)` — 周四 06:30 UTC（MW 前 12h）
- restore-init: `at(2026-11-21T06:30:00)` — 周五 06:30 UTC（MW 后 12h）

## 架构

```
EventBridge Scheduler at()          EventBridge Scheduler at()
(首次，触发后自动删除)                (首次，触发后自动删除)
     │                                    │
     ▼                                    ▼
 Skip Lambda                          Restore Lambda
 MW → original − 24h                  MW → original
     ▲                                    ▲
     │                                    │
EventBridge Rules rate(14 days)      EventBridge Rules rate(14 days)
(后续周期)                             (后续周期)
```

### 每个文件系统创建的资源

| 资源 | 命名 | 用途 |
|---|---|---|
| Lambda | `fsx-mw-skip-{fs-id}` | MW → original − 24h |
| Lambda | `fsx-mw-restore-{fs-id}` | MW → original |
| Scheduler | `fsx-mw-skip-init-{fs-id}` | 首次 skip at()，触发后自动删除 |
| Scheduler | `fsx-mw-restore-init-{fs-id}` | 首次 restore at()，触发后自动删除 |
| EB Rule | `fsx-mw-skip-{fs-id}` | rate(14 days) skip |
| EB Rule | `fsx-mw-restore-{fs-id}` | rate(14 days) restore |
| IAM Role | `fsx-mw-lambda-role` | Lambda 执行角色（共用） |
| IAM Role | `fsx-mw-scheduler-role` | Scheduler 调用 Lambda 角色（共用） |

## 费用

- Lambda + EventBridge + Scheduler + IAM：基本为零

## 清理

```bash
FS_ID=fs-xxxxxxxxxxxx
REGION=us-east-2

# 删 Lambda + EventBridge Rules
for prefix in fsx-mw-skip fsx-mw-restore; do
  aws events remove-targets --rule "${prefix}-${FS_ID}" --ids "target-${prefix}-${FS_ID}" --region $REGION 2>/dev/null
  aws events delete-rule --name "${prefix}-${FS_ID}" --region $REGION 2>/dev/null
  aws lambda delete-function --function-name "${prefix}-${FS_ID}" --region $REGION 2>/dev/null
  aws scheduler delete-schedule --name "${prefix}-init-${FS_ID}" --region $REGION 2>/dev/null
done

# 可选：删共用角色和用户
aws iam delete-role-policy --role-name fsx-mw-lambda-role --policy-name fsx-mw-lambda-policy
aws iam delete-role --role-name fsx-mw-lambda-role
aws iam delete-role-policy --role-name fsx-mw-scheduler-role --policy-name fsx-mw-scheduler-invoke
aws iam delete-role --role-name fsx-mw-scheduler-role
```

## 文件

| 文件 | 说明 |
|---|---|
| `fsx_mw_scheduler.py` | 主脚本（list + deploy） |
| `iam-policy.json` | 操作用户 IAM 策略（替换 ACCOUNT_ID） |
| `lambda-execution-role-policy.json` | Lambda 执行角色策略 |
| `README.md` | 英文文档 |
| `README_ZH.md` | 中文文档（本文） |
