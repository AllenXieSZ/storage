# FSx Lustre 运维窗口双周调度器

将 Amazon FSx for Lustre 每周运维窗口自动调整为**每两周执行一次**，通过 Lambda + EventBridge Scheduler 实现。

## 背景

FSx for Lustre 运维窗口每周固定执行，无法调整频率。运维期间文件系统短暂不可用且内存缓存清除，导致运维后访问延迟升高。本方案实现隔周跳过。

## 工作原理

每个文件系统部署 2 个 Lambda + 4 个 EventBridge Scheduler 调度：

- **Skip Lambda**：将 MW 设为 `原始值 − 24h`（绝对值，幂等）
- **Restore Lambda**：将 MW 恢复为`原始值`（绝对值，幂等）

### 触发调度（全部使用 EventBridge Scheduler）

| 调度名 | 类型 | 用途 |
|---|---|---|
| `fsx-mw-skip-init-{fs-id}` | `at()` 一次性 | 首次 skip，精确对齐到下一个 MW−12h，触发后自动删除 |
| `fsx-mw-restore-init-{fs-id}` | `at()` 一次性 | 首次 restore，精确对齐到下一个 MW+12h，触发后自动删除 |
| `fsx-mw-skip-cycle-{fs-id}` | `rate(14 days)` + `StartDate` | 周期 skip，StartDate = 首次 skip 后 14 天 |
| `fsx-mw-restore-cycle-{fs-id}` | `rate(14 days)` + `StartDate` | 周期 restore，StartDate = 首次 restore 后 14 天 |

### 关键设计：skip 和 restore 永远不会同时触发

skip 在 MW−12h 触发，restore 在 MW+12h 触发，两者相隔 24 小时。
`rate(14 days)` 的 `StartDate` 分别对齐到各自的正确时间点，保证长期运行也不会错位。

### 时间线示例

假设 MW = Wed 02:00 UTC：
```
第 1 周（跳过）：
  Tue 14:00  skip-init at() 触发 → MW 改为 Tue 02:00（已过，本周不执行）
  Wed 14:00  restore-init at() 触发 → MW 恢复为 Wed 02:00
  init 调度自动删除

第 2 周（正常）：
  无触发（rate(14d) 还没到 StartDate）
  MW = Wed 02:00 → 正常执行 maintenance ✅

第 3 周（跳过）：
  Tue 14:00  skip-cycle rate(14d) 首次触发 → MW 改为 Tue 02:00
  Wed 14:00  restore-cycle rate(14d) 首次触发 → MW 恢复为 Wed 02:00
  ...每 14 天循环
```

### 为什么全部使用 EventBridge Scheduler？

旧版使用 EventBridge Rules `rate(14 days)` 做周期触发，但有致命缺陷：
- **Rules 的 `rate()` 首次触发 = 规则创建时间**，无法指定 StartDate
- skip 和 restore 规则同时创建 → **同时触发 → 互相打架**
- Rules 不支持 `at()` 表达式（返回 `ValidationException`）

EventBridge Scheduler 同时支持 `at()` 和 `rate()` + `StartDate`，完美解决这两个问题。

### 幂等性

Lambda 使用**绝对值设置**，原始运维窗口时间从 CSV hard code 到代码里：
- Skip Lambda：`MW = 原始值 − 24h`（固定目标值，不是相对偏移）
- Restore Lambda：`MW = 原始值`
- MW 已经是目标值时不调用 UpdateFileSystem，直接返回
- 多次触发结果相同，无副作用

### 所有时间均为 UTC

FSx Lustre MW 时区固定为 UTC，EventBridge Scheduler 也使用 UTC，天然对齐。

## ⚠️ 部署时机（重要）

**必须在「上周刚完成 maintenance」后的那一周部署。**

原因：部署后首次 at() 会在下一个 MW−12h 跳过本周 maintenance。如果上周也被跳过 → 连续 2 周无 maintenance → 超 14 天 → AWS 可能强制执行。

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

> 编辑 CSV 删除不需要调整的文件系统。

### 3. 部署 Lambda + Scheduler

```bash
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

部署后 MW **不会立即改变**——等 at() 调度在精确时间点触发后才会改。

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

### 5. 清理

```bash
# 清理单个文件系统的所有资源（含旧版 EventBridge Rules）
python3 fsx_mw_scheduler.py clean --region us-east-2 --fs-id fs-xxxx

# 可选：删除共用 IAM 角色
aws iam delete-role-policy --role-name fsx-mw-lambda-role --policy-name fsx-mw-lambda-policy
aws iam delete-role --role-name fsx-mw-lambda-role
aws iam delete-role-policy --role-name fsx-mw-scheduler-role --policy-name fsx-mw-scheduler-invoke
aws iam delete-role --role-name fsx-mw-scheduler-role

# 可选：删除操作用户
aws iam delete-user-policy --user-name fsx-mw-scheduler --policy-name fsx-mw-scheduler-policy
aws iam delete-user --user-name fsx-mw-scheduler
```

## 架构图

```
EventBridge Scheduler at()           EventBridge Scheduler at()
(首次精确对齐，触发后自动删除)          (首次精确对齐，触发后自动删除)
     │                                     │
     ▼                                     ▼
 Skip Lambda ────────────────────── Restore Lambda
 MW → original − 24h                MW → original
     ▲                                     ▲
     │                                     │
EventBridge Scheduler rate(14d)     EventBridge Scheduler rate(14d)
StartDate = skip 首次 + 14天         StartDate = restore 首次 + 14天
(与 skip-init 对齐，不与 restore 冲突)  (与 restore-init 对齐，不与 skip 冲突)
```

### 每个文件系统创建的资源

| 资源 | 命名 | 用途 |
|---|---|---|
| Lambda | `fsx-mw-skip-{fs-id}` | MW → original − 24h |
| Lambda | `fsx-mw-restore-{fs-id}` | MW → original |
| Scheduler | `fsx-mw-skip-init-{fs-id}` | 首次 skip at()，触发后自动删除 |
| Scheduler | `fsx-mw-restore-init-{fs-id}` | 首次 restore at()，触发后自动删除 |
| Scheduler | `fsx-mw-skip-cycle-{fs-id}` | rate(14d) skip，StartDate = 首次 +14d |
| Scheduler | `fsx-mw-restore-cycle-{fs-id}` | rate(14d) restore，StartDate = 首次 +14d |
| IAM Role | `fsx-mw-lambda-role` | Lambda 执行角色（共用） |
| IAM Role | `fsx-mw-scheduler-role` | Scheduler 调用 Lambda 角色（共用） |

## 费用

- Lambda + EventBridge Scheduler + IAM：基本为零（每 14 天 2 次 Lambda 调用 / FS）

## 文件

| 文件 | 说明 |
|---|---|
| `fsx_mw_scheduler.py` | 主脚本（list + deploy + clean） |
| `iam-policy.json` | 操作用户 IAM 策略（替换 ACCOUNT_ID） |
| `lambda-execution-role-policy.json` | Lambda 执行角色策略 |
| `README.md` | 英文文档 |
| `README_ZH.md` | 中文文档（本文） |
