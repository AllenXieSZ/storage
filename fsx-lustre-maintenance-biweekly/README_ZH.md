# FSx Lustre 运维窗口双周调度器

将 Amazon FSx for Lustre 每周运维窗口自动调整为**每两周执行一次**，通过 Lambda + EventBridge Scheduler 实现。

## 背景

FSx for Lustre 运维窗口每周固定执行，无法调整频率。运维期间文件系统短暂不可用且内存缓存清除，导致运维后访问延迟升高。本方案实现隔周跳过。

## 工作原理

每个文件系统部署 **2 个 Lambda** + **2 个 EventBridge Scheduler 调度**：

| 组件 | 命名 | 作用 |
|---|---|---|
| Lambda | `fsx-mw-skip-{fs-id}` | 将运维窗口设为 `原始值 − 24小时`（幂等） |
| Lambda | `fsx-mw-restore-{fs-id}` | 将运维窗口恢复为原始值（幂等） |
| Scheduler | `fsx-mw-skip-{fs-id}` | `rate(14 days)` + `StartDate` = 下一个运维窗口−12小时 |
| Scheduler | `fsx-mw-restore-{fs-id}` | `rate(14 days)` + `StartDate` = 下一个运维窗口+12小时 |

### 核心机制：`rate(14 days)` + `StartDate`

EventBridge Scheduler 的 `rate()` 表达式支持 `StartDate` 参数——首次触发在 StartDate，之后每 14 天触发一次。

- skip 的 StartDate = 运维窗口−12小时（维护前 12 小时）
- restore 的 StartDate = 运维窗口+12小时（维护后 12 小时）
- **两者永远相隔 24 小时，不会冲突**

### 时间线示例

假设运维窗口 = Wed 02:00 UTC，部署在维护执行后那一周：

```
第 1 周（跳过）：
  Tue 14:00  skip 首次触发（StartDate）→ 运维窗口改为 Tue 02:00（已过，本周不执行维护）
  Wed 14:00  restore 首次触发（StartDate）→ 运维窗口恢复为 Wed 02:00

第 2 周（正常）：
  无触发（还没到下一个 14 天周期）
  运维窗口 = Wed 02:00 → 正常执行维护 ✅

第 3 周（跳过）：
  Tue 14:00  skip 第二次触发（StartDate + 14天）→ 运维窗口改为 Tue 02:00
  Wed 14:00  restore 第二次触发（StartDate + 14天）→ 运维窗口恢复为 Wed 02:00
  ...每 14 天循环
```

### 幂等性

Lambda 使用**绝对值设置**（不是相对偏移）：
- Skip: `运维窗口 = 固定目标值`（原始值 − 24小时）
- Restore: `运维窗口 = 原始值`
- 运维窗口已经是目标值时跳过 UpdateFileSystem 调用
- 多次触发结果相同，无副作用

### 所有时间均为 UTC

FSx Lustre 运维窗口时区固定为 UTC，EventBridge Scheduler 也使用 UTC，天然对齐。

## ⚠️ 部署时机（重要）

**必须在「上周刚完成 maintenance」后的那一周部署。**

原因：部署后首次 skip 会跳过下一个维护窗口。如果上周也被跳过 → 连续 2 周无 maintenance → 超 14 天 → AWS 可能强制执行。

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

### 3. 部署

```bash
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

部署后运维窗口**不会立即改变**——等 Scheduler 在 StartDate 触发后才会改。

### 4. 验证

```bash
# 手动测试 skip（立即触发一次看效果）
aws lambda invoke --function-name fsx-mw-skip-fs-xxxx --region us-east-2 /tmp/out.json
cat /tmp/out.json

# 检查运维窗口
aws fsx describe-file-systems --file-system-ids fs-xxxx --region us-east-2 \
  --query 'FileSystems[0].LustreConfiguration.WeeklyMaintenanceStartTime' --output text

# 手动测试 restore
aws lambda invoke --function-name fsx-mw-restore-fs-xxxx --region us-east-2 /tmp/out.json

# 测试幂等（再 invoke skip，应返回 changed=false）
aws lambda invoke --function-name fsx-mw-skip-fs-xxxx --region us-east-2 /tmp/out.json
cat /tmp/out.json

# 查看 Scheduler 调度状态
aws scheduler list-schedules --region us-east-2 \
  --query 'Schedules[?starts_with(Name,`fsx-mw-`)].{Name:Name,State:State}' --output table
```

### 5. 清理

```bash
# 清理单个文件系统的所有资源
python3 fsx_mw_scheduler.py clean --region us-east-2 --fs-id fs-xxxx

# 可选：删除共用 IAM 角色
aws iam delete-role-policy --role-name fsx-mw-lambda-role --policy-name fsx-mw-lambda-policy
aws iam delete-role --role-name fsx-mw-lambda-role
aws iam delete-role-policy --role-name fsx-mw-scheduler-role --policy-name fsx-mw-scheduler-invoke
aws iam delete-role --role-name fsx-mw-scheduler-role
```

## 架构图

```
EventBridge Scheduler                EventBridge Scheduler
rate(14 days)                        rate(14 days)
StartDate = 运维窗口 − 12小时                 StartDate = 运维窗口 + 12小时
       │                                    │
       ▼                                    ▼
  Skip Lambda                         Restore Lambda
  运维窗口 → 原始值 − 24小时                 运维窗口 → 原始值
```

## 每个文件系统创建的资源

| 资源 | 命名 | 说明 |
|---|---|---|
| Lambda × 2 | `fsx-mw-skip-{fs-id}`, `fsx-mw-restore-{fs-id}` | 幂等运维窗口设置 |
| Scheduler × 2 | `fsx-mw-skip-{fs-id}`, `fsx-mw-restore-{fs-id}` | rate(14天) + StartDate |
| IAM Role × 2 | `fsx-mw-lambda-role`, `fsx-mw-scheduler-role` | 共用，所有 FS 共享 |

## 费用

基本为零（每 14 天 2 次 Lambda 调用 / FS + Scheduler 免费层级）。

## 文件

| 文件 | 说明 |
|---|---|
| `fsx_mw_scheduler.py` | 主脚本（list + deploy + clean） |
| `iam-policy.json` | 操作用户 IAM 策略（替换 ACCOUNT_ID） |
| `lambda-execution-role-policy.json` | Lambda 执行角色策略 |
| `README.md` | 英文文档 |
| `README_ZH.md` | 中文文档（本文） |
