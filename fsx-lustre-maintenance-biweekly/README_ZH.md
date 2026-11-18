# FSx Lustre 运维窗口双周调度器

将 Amazon FSx for Lustre 每周运维窗口自动调整为 **每两周执行一次**，通过 Lambda + EventBridge 实现，部署后无需任何手动操作。

## 背景问题

FSx for Lustre 的运维窗口（Maintenance Window）是 **每周固定时间** 执行，AWS 不提供原生的频率调整选项。运维期间文件系统会短暂不可用，且内存缓存会被清除——导致运维后一段时间内访问延迟明显升高。对于生产环境，每周一次运维可能太频繁、影响业务。

本方案通过自动"挪窗口"的方式，**隔一周跳过一次运维**，等效实现双周运维。

## 工作原理

对每个 FSx Lustre 文件系统，脚本会部署 **两个 Lambda 函数**，由 EventBridge 每 14 天触发一次：

```
第 1 周（跳过运维）：
  Lambda A 在运维窗口前 12 小时触发
    → 将运维窗口往前挪 24 小时
    → 原来的运维时间点已经没有窗口了 → 运维被跳过

  Lambda B 在原运维时间后 12 小时触发
    → 将运维窗口往后挪 24 小时
    → 恢复到原来的位置，等待下一个周期

第 2 周（正常运维）：
  两个 Lambda 都不触发（14 天一次的调度周期）
    → 运维窗口保持在原位 → 正常执行运维

第 3 周 = 第 1 周（跳过），第 4 周 = 第 2 周（正常），如此循环...
```

### 举例 — 运维窗口 = 每周三 02:00 UTC

| 阶段 | 运维窗口值 | 触发者 |
|---|---|---|
| 初始状态 | `3:02:00` → **周三 02:00 UTC** | — |
| Lambda A 执行后（-24h） | `2:02:00` → **周二 02:00 UTC** | 跳过 Lambda（周二 14:00 UTC 触发） |
| Lambda B 执行后（+24h） | `3:02:00` → **周三 02:00 UTC** ✅ 恢复 | 恢复 Lambda（周三 14:00 UTC 触发） |

### FSx 运维窗口格式说明

- **格式**：`d:HH:MM`，其中 `d` = 1（周一）到 7（周日）
- **时区**：始终是 **UTC**（不可配置时区）
- **时长**：30 分钟窗口
- **硬性约束**：AWS 要求运维窗口 **至少每 14 天执行一次**。如果超过 14 天没有命中运维窗口，AWS 会强制执行运维。

> **来源**：[Amazon FSx for Lustre 用户指南 — 运维窗口](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html)

## 前置条件

- Python 3.9+，已安装 `boto3`
- 一个有 FSx Lustre 文件系统的 AWS 账号
- AWS CLI 已配置好凭证

## 部署步骤

### 1. 创建 IAM 用户

```bash
# 创建用户
aws iam create-user --user-name fsx-mw-scheduler

# 创建 Access Key
aws iam create-access-key --user-name fsx-mw-scheduler
# 记下输出中的 AccessKeyId 和 SecretAccessKey
```

### 2. 附加 IAM 权限策略

该用户需要以下权限：列出/更新 FSx 文件系统、创建/调用 Lambda 函数、管理 EventBridge 规则、创建 Lambda 执行角色。

编辑 `iam-policy.json`，将所有 `ACCOUNT_ID` 替换为你的 12 位 AWS 账号 ID：

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" iam-policy.json > /tmp/iam-policy-resolved.json

aws iam put-user-policy \
  --user-name fsx-mw-scheduler \
  --policy-name fsx-mw-scheduler-policy \
  --policy-document file:///tmp/iam-policy-resolved.json
```

### 3. 配置凭证

```bash
export AWS_ACCESS_KEY_ID=<你的AccessKeyId>
export AWS_SECRET_ACCESS_KEY=<你的SecretAccessKey>
```

### 4. 列出 FSx Lustre 文件系统 → 生成 CSV

```bash
python3 fsx_mw_scheduler.py list --region us-east-2
```

输出示例：
```
✅ Wrote 2 FSx Lustre file systems to fsx_lustre_list.csv
   fs-02e88f8550a3572d3  mw-test-1                       MW=3:02:00 (Wed 02:00 UTC)
   fs-0247683a1e4d5b957  mw-test-2                       MW=5:18:30 (Fri 18:30 UTC)
```

生成的 CSV 文件（`fsx_lustre_list.csv`）：
```csv
Name,FileSystemId,MaintenanceWindow,MaintenanceWindowHuman,Timezone
mw-test-1,fs-02e88f8550a3572d3,3:02:00,Wed 02:00 UTC,UTC
mw-test-2,fs-0247683a1e4d5b957,5:18:30,Fri 18:30 UTC,UTC
```

> **提示**：编辑 CSV 文件，删除不需要调整为双周运维的文件系统。

### 5. 部署 Lambda + EventBridge

```bash
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

输出示例：
```
📋 Read 2 file systems from fsx_lustre_list.csv
   ✅ Created IAM role fsx-mw-lambda-role

============================================================
📁 mw-test-1 (fs-02e88f8550a3572d3)  MW=3:02:00 (Wed 02:00 UTC)
   Lambda A (skip): fsx-mw-skip-fs-02e88f8550a3572d3
     Fires at: TUE 14:00 UTC (12h before MW)
     Action: shift MW -24h
     ✅ Lambda created
     ✅ EventBridge rule: fsx-mw-skip-fs-02e88f8550a3572d3 (rate(14 days))
   Lambda B (restore): fsx-mw-restore-fs-02e88f8550a3572d3
     Fires at: WED 14:00 UTC (12h after MW)
     Action: shift MW +24h
     ✅ Lambda created
     ✅ EventBridge rule: fsx-mw-restore-fs-02e88f8550a3572d3 (rate(14 days))

============================================================
📁 mw-test-2 (fs-0247683a1e4d5b957)  MW=5:18:30 (Fri 18:30 UTC)
   Lambda A (skip): fsx-mw-skip-fs-0247683a1e4d5b957
     Fires at: FRI 06:30 UTC (12h before MW)
     Action: shift MW -24h
     ✅ Lambda created
     ✅ EventBridge rule: fsx-mw-skip-fs-0247683a1e4d5b957 (rate(14 days))
   Lambda B (restore): fsx-mw-restore-fs-0247683a1e4d5b957
     Fires at: SAT 06:30 UTC (12h after MW)
     Action: shift MW +24h
     ✅ Lambda created
     ✅ EventBridge rule: fsx-mw-restore-fs-0247683a1e4d5b957 (rate(14 days))

============================================================
🎉 Deployment complete!
```

## 测试结果

在 us-east-2 区域用 2 个 FSx Lustre SCRATCH_2 文件系统进行了实测，手动触发 Lambda 验证了完整的跳过→恢复周期：

### 测试 1：mw-test-1（运维窗口 = 周三 02:00 UTC / `3:02:00`）

| 阶段 | 运维窗口值 | 可读格式 |
|---|---|---|
| Lambda A 执行前 | `3:02:00` | 周三 02:00 UTC |
| Lambda A 执行后（−24h） | `2:02:00` | **周二 02:00 UTC** ← 往前挪了，周三的运维被跳过 |
| Lambda B 执行后（+24h） | `3:02:00` | **周三 02:00 UTC** ← 恢复原位 |

Lambda A 返回值：
```json
{"statusCode": 200, "body": "FSx fs-02e88f8550a3572d3: shifted MW from Wed 02:00 UTC to Tue 02:00 UTC (-24h)", "oldMW": "3:02:00", "newMW": "2:02:00"}
```

Lambda B 返回值：
```json
{"statusCode": 200, "body": "FSx fs-02e88f8550a3572d3: shifted MW from Tue 02:00 UTC to Wed 02:00 UTC (+24h)", "oldMW": "2:02:00", "newMW": "3:02:00"}
```

### 测试 2：mw-test-2（运维窗口 = 周五 18:30 UTC / `5:18:30`）

| 阶段 | 运维窗口值 | 可读格式 |
|---|---|---|
| Lambda A 执行前 | `5:18:30` | 周五 18:30 UTC |
| Lambda A 执行后（−24h） | `4:18:30` | **周四 18:30 UTC** ← 往前挪了，周五的运维被跳过 |
| Lambda B 执行后（+24h） | `5:18:30` | **周五 18:30 UTC** ← 恢复原位 |

Lambda A 返回值：
```json
{"statusCode": 200, "body": "FSx fs-0247683a1e4d5b957: shifted MW from Fri 18:30 UTC to Thu 18:30 UTC (-24h)", "oldMW": "5:18:30", "newMW": "4:18:30"}
```

Lambda B 返回值：
```json
{"statusCode": 200, "body": "FSx fs-0247683a1e4d5b957: shifted MW from Thu 18:30 UTC to Fri 18:30 UTC (+24h)", "oldMW": "4:18:30", "newMW": "5:18:30"}
```

## 架构图

```
EventBridge（rate: 14 天）          EventBridge（rate: 14 天）
     │                                    │
     ▼                                    ▼
 Lambda A                             Lambda B
 "fsx-mw-skip-{fs-id}"               "fsx-mw-restore-{fs-id}"
 触发时间: 运维窗口前 12h             触发时间: 运维窗口后 12h
 动作: 运维窗口 −24h                  动作: 运维窗口 +24h
     │                                    │
     ▼                                    ▼
 FSx UpdateFileSystem                 FSx UpdateFileSystem
 （把窗口往前挪一天）                 （把窗口挪回原位）
```

### 每个文件系统创建的资源

| 资源 | 命名规则 | 用途 |
|---|---|---|
| Lambda 函数 | `fsx-mw-skip-{fs-id}` | 将运维窗口往前挪 24 小时（跳过本周运维） |
| Lambda 函数 | `fsx-mw-restore-{fs-id}` | 将运维窗口往后挪 24 小时（恢复原位） |
| EventBridge 规则 | `fsx-mw-skip-{fs-id}` | 每 14 天触发跳过 Lambda |
| EventBridge 规则 | `fsx-mw-restore-{fs-id}` | 每 14 天触发恢复 Lambda |
| IAM 角色 | `fsx-mw-lambda-role` | 所有 Lambda 共用（每个账号 1 个） |

### IAM 权限说明

**IAM 用户权限**（`iam-policy.json`）— 运行部署脚本用：
- `fsx:DescribeFileSystems`、`fsx:UpdateFileSystem` — 列出和更新运维窗口
- `lambda:Create/Delete/Invoke/Update*` — 管理 Lambda 函数（限定 `fsx-mw-*` 前缀）
- `events:PutRule/PutTargets/Delete*` — 管理 EventBridge 规则（限定 `fsx-mw-*` 前缀）
- `iam:CreateRole/GetRole/PutRolePolicy/PassRole` — 创建 Lambda 执行角色
- `sts:GetCallerIdentity` — 自动获取账号 ID

**Lambda 执行角色权限**（`lambda-execution-role-policy.json`）— Lambda 运行时用：
- `fsx:DescribeFileSystems`、`fsx:UpdateFileSystem` — 读取和更新运维窗口
- `logs:Create*/PutLogEvents` — CloudWatch 日志

## 注意事项

### 14 天硬性限制

[FSx Lustre 用户指南](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html) 原文：

> *"You can move your maintenance window as frequently as required, provided that a maintenance window is scheduled at least once every 14 days. If a patch is released and you haven't scheduled a maintenance window within 14 days, FSx for Lustre will proceed with maintenance on the file system to ensure its security and reliability."*

翻译：你可以随意调整运维窗口，但 **至少每 14 天必须命中一次运维窗口**。如果超过 14 天没有执行运维，AWS 会强制执行以确保安全性。

本方案正好工作在 **14 天边界上**——跳过一周、执行一周。这是 AWS 允许的最大间隔。如果时间漂移或 EventBridge 投递延迟，AWS 可能会强制执行运维。

### EventBridge `rate(14 days)` 的行为

- `rate(14 days)` 从规则**创建时间**开始，每 14 天触发一次
- 第一次触发可能和期望的运维窗口偏移时间不完全对齐。后续周期会自动修正，因为每个 Lambda 执行前都会**读取当前的运维窗口值**再进行偏移
- 如果需要精确的首次时间对齐，可以在部署后手动触发一次 Lambda A 来初始化第一次跳过

### 费用

- **Lambda**：约 $0.00/月（每个文件系统每 14 天 2 次调用，128MB 内存，每次 <1 秒）
- **EventBridge**：约 $0.00/月（每个文件系统 2 条定时规则）
- **IAM**：免费
- **总计**：对于任意合理数量的文件系统，费用基本为零

## 清理资源

```bash
# 删除某个文件系统对应的 Lambda 函数和 EventBridge 规则
FS_ID=fs-xxxxxxxxxxxx
REGION=us-east-2

for prefix in fsx-mw-skip fsx-mw-restore; do
  aws events remove-targets --rule "${prefix}-${FS_ID}" --ids "target-${FS_ID}" --region $REGION
  aws events delete-rule --name "${prefix}-${FS_ID}" --region $REGION
  aws lambda delete-function --function-name "${prefix}-${FS_ID}" --region $REGION
done

# （可选）删除共享的 Lambda 执行角色
aws iam delete-role-policy --role-name fsx-mw-lambda-role --policy-name fsx-mw-lambda-policy
aws iam delete-role --role-name fsx-mw-lambda-role

# （可选）删除 IAM 用户
aws iam delete-user-policy --user-name fsx-mw-scheduler --policy-name fsx-mw-scheduler-policy
aws iam delete-access-key --user-name fsx-mw-scheduler --access-key-id <KEY_ID>
aws iam delete-user --user-name fsx-mw-scheduler
```

## 文件说明

| 文件 | 说明 |
|---|---|
| `fsx_mw_scheduler.py` | 主脚本 — 支持 `list`（列出文件系统）和 `deploy`（部署 Lambda + EventBridge）两个命令 |
| `iam-policy.json` | 操作用户的 IAM 权限策略（需替换 `ACCOUNT_ID`） |
| `lambda-execution-role-policy.json` | Lambda 执行角色的 IAM 权限策略 |
| `README.md` | 英文文档 |
| `README_ZH.md` | 本文（中文文档） |
