# FSx Lustre Maintenance Window — Biweekly Scheduler

Convert Amazon FSx for Lustre weekly maintenance windows into **biweekly (every 2 weeks)** using Lambda + EventBridge, with zero manual intervention after deployment.

## Problem

FSx for Lustre performs maintenance **weekly** during your configured maintenance window. There is no native setting to change the frequency. During maintenance the file system is briefly unavailable, and the in-memory cache is cleared — causing higher latencies afterward. For workloads where weekly patching is too disruptive, reducing the frequency to biweekly is desirable.

## How It Works

For each FSx Lustre file system, the script deploys **two Lambda functions** triggered by EventBridge every 14 days:

```
Week 1 (skip maintenance):
  Lambda A fires 12h BEFORE the maintenance window
    → shifts the window BACK 24 hours
    → the original MW time passes with no window scheduled → maintenance skipped

  Lambda B fires 12h AFTER the original MW time
    → shifts the window FORWARD 24 hours
    → restores the window to its original position for the next cycle

Week 2 (allow maintenance):
  Neither Lambda fires (14-day rate schedule)
    → maintenance window stays at its original time → maintenance executes normally

Week 3 = Week 1 (skip), Week 4 = Week 2 (allow), ...
```

### Example — Maintenance Window = Wednesday 02:00 UTC

| Phase | Maintenance Window | Triggered By |
|---|---|---|
| Original | `3:02:00` → **Wed 02:00 UTC** | — |
| After Lambda A (`-24h`) | `2:02:00` → **Tue 02:00 UTC** | Skip Lambda (Tue 14:00 UTC) |
| After Lambda B (`+24h`) | `3:02:00` → **Wed 02:00 UTC** ✅ restored | Restore Lambda (Wed 14:00 UTC) |

### FSx Maintenance Window Format

- **Format**: `d:HH:MM` where `d` = 1 (Monday) through 7 (Sunday)
- **Timezone**: Always **UTC** (no timezone setting)
- **Duration**: 30-minute window
- **Constraint**: AWS requires a maintenance window to be hit at least once every **14 days**. If not, AWS will force maintenance regardless of the window setting.

> **Source**: [Amazon FSx for Lustre User Guide — Maintenance Windows](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html)

## Prerequisites

- Python 3.9+ with `boto3` installed
- An AWS account with FSx Lustre file systems
- AWS CLI configured (for IAM user/key setup)

## Setup — Step by Step

### 1. Create IAM User

```bash
# Create the user
aws iam create-user --user-name fsx-mw-scheduler

# Create access key
aws iam create-access-key --user-name fsx-mw-scheduler
# Save the AccessKeyId and SecretAccessKey from the output
```

### 2. Attach IAM Policy

The user needs permissions to: list/update FSx file systems, create/invoke Lambda functions, manage EventBridge rules, and create the Lambda execution role.

Edit `iam-policy.json` — replace all `ACCOUNT_ID` with your 12-digit AWS account ID:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" iam-policy.json > /tmp/iam-policy-resolved.json

aws iam put-user-policy \
  --user-name fsx-mw-scheduler \
  --policy-name fsx-mw-scheduler-policy \
  --policy-document file:///tmp/iam-policy-resolved.json
```

### 3. Configure Credentials

```bash
export AWS_ACCESS_KEY_ID=<your-access-key-id>
export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
```

### 4. List FSx Lustre File Systems → CSV

```bash
python3 fsx_mw_scheduler.py list --region us-east-2
```

Output:
```
✅ Wrote 2 FSx Lustre file systems to fsx_lustre_list.csv
   fs-02e88f8550a3572d3  mw-test-1                       MW=3:02:00 (Wed 02:00 UTC)
   fs-0247683a1e4d5b957  mw-test-2                       MW=5:18:30 (Fri 18:30 UTC)
```

CSV file (`fsx_lustre_list.csv`):
```csv
Name,FileSystemId,MaintenanceWindow,MaintenanceWindowHuman,Timezone
mw-test-1,fs-02e88f8550a3572d3,3:02:00,Wed 02:00 UTC,UTC
mw-test-2,fs-0247683a1e4d5b957,5:18:30,Fri 18:30 UTC,UTC
```

> **Tip**: Edit the CSV to remove any file systems you don't want to convert to biweekly.

### 5. Deploy Lambda + EventBridge

```bash
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

Output:
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

## Test Results

Tested with 2 FSx Lustre SCRATCH_2 file systems (us-east-2). Manual Lambda invocations verified the full cycle:

### Test 1: mw-test-1 (MW = Wed 02:00 UTC / `3:02:00`)

| Phase | MW Value | Human Readable |
|---|---|---|
| Before Lambda A | `3:02:00` | Wed 02:00 UTC |
| After Lambda A (−24h) | `2:02:00` | **Tue 02:00 UTC** ← shifted back, Wed window skipped |
| After Lambda B (+24h) | `3:02:00` | **Wed 02:00 UTC** ← restored |

Lambda A output:
```json
{"statusCode": 200, "body": "FSx fs-02e88f8550a3572d3: shifted MW from Wed 02:00 UTC to Tue 02:00 UTC (-24h)", "oldMW": "3:02:00", "newMW": "2:02:00"}
```

Lambda B output:
```json
{"statusCode": 200, "body": "FSx fs-02e88f8550a3572d3: shifted MW from Tue 02:00 UTC to Wed 02:00 UTC (+24h)", "oldMW": "2:02:00", "newMW": "3:02:00"}
```

### Test 2: mw-test-2 (MW = Fri 18:30 UTC / `5:18:30`)

| Phase | MW Value | Human Readable |
|---|---|---|
| Before Lambda A | `5:18:30` | Fri 18:30 UTC |
| After Lambda A (−24h) | `4:18:30` | **Thu 18:30 UTC** ← shifted back, Fri window skipped |
| After Lambda B (+24h) | `5:18:30` | **Fri 18:30 UTC** ← restored |

Lambda A output:
```json
{"statusCode": 200, "body": "FSx fs-0247683a1e4d5b957: shifted MW from Fri 18:30 UTC to Thu 18:30 UTC (-24h)", "oldMW": "5:18:30", "newMW": "4:18:30"}
```

Lambda B output:
```json
{"statusCode": 200, "body": "FSx fs-0247683a1e4d5b957: shifted MW from Thu 18:30 UTC to Fri 18:30 UTC (+24h)", "oldMW": "4:18:30", "newMW": "5:18:30"}
```

## Architecture

```
EventBridge (rate: 14 days)          EventBridge (rate: 14 days)
     │                                    │
     ▼                                    ▼
 Lambda A                             Lambda B
 "fsx-mw-skip-{fs-id}"               "fsx-mw-restore-{fs-id}"
 Fires: MW − 12h                     Fires: MW + 12h
 Action: MW − 24h                    Action: MW + 24h
     │                                    │
     ▼                                    ▼
 FSx UpdateFileSystem                 FSx UpdateFileSystem
 (shift window back)                  (shift window forward)
```

### Resources Created Per File System

| Resource | Name Pattern | Purpose |
|---|---|---|
| Lambda Function | `fsx-mw-skip-{fs-id}` | Shift MW back 24h (skip maintenance) |
| Lambda Function | `fsx-mw-restore-{fs-id}` | Shift MW forward 24h (restore) |
| EventBridge Rule | `fsx-mw-skip-{fs-id}` | Trigger skip Lambda every 14 days |
| EventBridge Rule | `fsx-mw-restore-{fs-id}` | Trigger restore Lambda every 14 days |
| IAM Role | `fsx-mw-lambda-role` | Shared by all Lambda functions (1 per account) |

### IAM Permissions

**IAM User** (`iam-policy.json`) — for running the script:
- `fsx:DescribeFileSystems`, `fsx:UpdateFileSystem` — list and update MW
- `lambda:Create/Delete/Invoke/Update*` — manage Lambda functions (scoped to `fsx-mw-*`)
- `events:PutRule/PutTargets/Delete*` — manage EventBridge rules (scoped to `fsx-mw-*`)
- `iam:CreateRole/GetRole/PutRolePolicy/PassRole` — create Lambda execution role
- `sts:GetCallerIdentity` — auto-detect account ID

**Lambda Execution Role** (`lambda-execution-role-policy.json`) — for Lambda runtime:
- `fsx:DescribeFileSystems`, `fsx:UpdateFileSystem` — read and update MW
- `logs:Create*/PutLogEvents` — CloudWatch Logs

## Important Considerations

### 14-Day Hard Limit

From the [FSx Lustre User Guide](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html):

> *"You can move your maintenance window as frequently as required, provided that a maintenance window is scheduled at least once every 14 days. If a patch is released and you haven't scheduled a maintenance window within 14 days, FSx for Lustre will proceed with maintenance on the file system to ensure its security and reliability."*

This biweekly approach operates **at the 14-day boundary** — skipping one week, then allowing the next. This is the maximum stretch AWS permits. If timing drifts or EventBridge delivery is delayed, AWS may force maintenance to maintain the 14-day guarantee.

### EventBridge `rate(14 days)` Behavior

- `rate(14 days)` fires at the time the rule was **created**, then every 14 days.
- The first invocation may not align perfectly with the desired MW offset. Subsequent cycles self-correct because each Lambda reads the **current** MW value before shifting.
- If you need precise initial timing, manually invoke Lambda A once after deployment to seed the first skip.

### Cost

- **Lambda**: ~$0.00/month (2 invocations per FS per 14 days, 128 MB, <1 sec each)
- **EventBridge**: ~$0.00/month (2 rules per FS, scheduled)
- **IAM**: Free
- **Total**: Effectively free for any reasonable number of file systems

## Cleanup

```bash
# Delete Lambda functions and EventBridge rules for a specific FS
FS_ID=fs-xxxxxxxxxxxx
REGION=us-east-2

for prefix in fsx-mw-skip fsx-mw-restore; do
  aws events remove-targets --rule "${prefix}-${FS_ID}" --ids "target-${FS_ID}" --region $REGION
  aws events delete-rule --name "${prefix}-${FS_ID}" --region $REGION
  aws lambda delete-function --function-name "${prefix}-${FS_ID}" --region $REGION
done

# (Optional) Delete the shared Lambda role
aws iam delete-role-policy --role-name fsx-mw-lambda-role --policy-name fsx-mw-lambda-policy
aws iam delete-role --role-name fsx-mw-lambda-role

# (Optional) Delete the IAM user
aws iam delete-user-policy --user-name fsx-mw-scheduler --policy-name fsx-mw-scheduler-policy
aws iam delete-access-key --user-name fsx-mw-scheduler --access-key-id <KEY_ID>
aws iam delete-user --user-name fsx-mw-scheduler
```

## Files

| File | Description |
|---|---|
| `fsx_mw_scheduler.py` | Main script — `list` and `deploy` commands |
| `iam-policy.json` | IAM policy for the operator user (replace `ACCOUNT_ID`) |
| `lambda-execution-role-policy.json` | IAM policy for the Lambda execution role |
| `README.md` | This file |
