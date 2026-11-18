# FSx Lustre Maintenance Window — Biweekly Scheduler

Convert Amazon FSx for Lustre weekly maintenance windows into **biweekly (every 2 weeks)** using Lambda + EventBridge.

## How It Works

Two Lambda functions per file system, triggered by EventBridge every 14 days:

- **Skip Lambda**: fires 12h before MW, sets MW to `original − 24h` (absolute, idempotent)
- **Restore Lambda**: fires 12h after MW, sets MW back to `original` (absolute, idempotent)

```
Week 1 (skip):  Skip shifts MW away → no window at original time → skipped
                Restore sets MW back → ready for next cycle
Week 2 (allow): Neither Lambda fires (14-day rate) → MW at original → maintenance runs
Week 3 = Week 1, ...
```

### Idempotency

Lambda functions set MW to a **hard-coded absolute value** (from CSV), not a relative shift. Invoking multiple times produces the same result. If MW is already at the target, no `UpdateFileSystem` call is made.

### Deployment Timing ⚠️

**Deploy in the week AFTER a successful maintenance.** The deploy script invokes Skip Lambda immediately, which skips the current week's maintenance. If the previous week's maintenance was also skipped, you'll exceed the 14-day limit and AWS will force maintenance.

See [FSx Lustre User Guide — Maintenance Windows](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html).

## Quick Start

```bash
# 1. List FSx Lustre file systems → CSV
python3 fsx_mw_scheduler.py list --region us-east-2

# 2. Edit CSV to keep only the file systems you want

# 3. Deploy (creates Lambda + EventBridge + invokes first skip)
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

## Test Results

Tested with 2 FSx Lustre SCRATCH_2 file systems (us-east-2):

### mw-test-1 (MW = Wed 02:00 UTC / `3:02:00`)

| Phase | MW Value | Notes |
|---|---|---|
| Before Skip | `3:02:00` | Wed 02:00 UTC |
| After Skip | `2:02:00` | **Tue 02:00** ← shifted, Wed skipped |
| After Restore | `3:02:00` | **Wed 02:00** ← restored |
| Skip again (idempotent) | `2:02:00` | Same result ✅ |

### mw-test-2 (MW = Fri 18:30 UTC / `5:18:30`)

| Phase | MW Value | Notes |
|---|---|---|
| Before Skip | `5:18:30` | Fri 18:30 UTC |
| After Skip | `4:18:30` | **Thu 18:30** ← shifted |
| After Restore | `5:18:30` | **Fri 18:30** ← restored |

## Architecture

```
EventBridge (rate 14 days)           EventBridge (rate 14 days)
     │                                    │
     ▼                                    ▼
 Skip Lambda                          Restore Lambda
 MW → original − 24h                  MW → original
 (idempotent, absolute)               (idempotent, absolute)
     │                                    │
     ▼                                    ▼
 FSx UpdateFileSystem                 FSx UpdateFileSystem
```

## Cost

Effectively zero (2 Lambda invocations per FS per 14 days, 128 MB, <1 sec each).

## Cleanup

```bash
FS_ID=fs-xxxxxxxxxxxx; REGION=us-east-2
for prefix in fsx-mw-skip fsx-mw-restore; do
  aws events remove-targets --rule "${prefix}-${FS_ID}" --ids "target-${FS_ID}" --region $REGION
  aws events delete-rule --name "${prefix}-${FS_ID}" --region $REGION
  aws lambda delete-function --function-name "${prefix}-${FS_ID}" --region $REGION
done
```

## Files

| File | Description |
|---|---|
| `fsx_mw_scheduler.py` | Main script (list + deploy) |
| `iam-policy.json` | IAM policy for operator user |
| `lambda-execution-role-policy.json` | Lambda execution role policy |
| `README.md` | This file |
| `README_ZH.md` | Chinese documentation |
