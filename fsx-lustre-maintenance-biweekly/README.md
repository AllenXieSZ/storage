# FSx Lustre Maintenance Window — Biweekly Scheduler

Convert Amazon FSx for Lustre weekly maintenance windows into **biweekly (every 2 weeks)** using Lambda + EventBridge Scheduler.

## How It Works

Per file system: **2 Lambda functions** + **2 EventBridge Scheduler schedules**.

| Component | Naming | Purpose |
|---|---|---|
| Lambda | `fsx-mw-skip-{fs-id}` | Set MW to `original − 24h` (idempotent) |
| Lambda | `fsx-mw-restore-{fs-id}` | Set MW back to `original` (idempotent) |
| Scheduler | `fsx-mw-skip-{fs-id}` | `rate(14 days)` + `StartDate` = next MW−12h |
| Scheduler | `fsx-mw-restore-{fs-id}` | `rate(14 days)` + `StartDate` = next MW+12h |

### Core: `rate(14 days)` + `StartDate`

EventBridge Scheduler's `rate()` supports `StartDate` — first invocation at StartDate, then every 14 days.

- skip StartDate = MW−12h (12 hours before maintenance)
- restore StartDate = MW+12h (12 hours after maintenance)
- **Always 24h apart → never collide**

### Timeline (MW = Wed 02:00 UTC)

```
Week 1 (skip):
  Tue 14:00  skip fires → MW = Tue 02:00 (past → no maintenance this week)
  Wed 14:00  restore fires → MW = Wed 02:00 (restored)

Week 2 (normal):
  No triggers → maintenance runs normally ✅

Week 3 (skip):
  Tue 14:00  skip fires (StartDate + 14d) → MW shifted
  Wed 14:00  restore fires (StartDate + 14d) → MW restored
  ...repeats
```

### Deployment Timing ⚠️

**Deploy in the week AFTER a successful maintenance.** Otherwise you may skip two consecutive weeks, exceeding the 14-day limit.

## Quick Start

```bash
# 1. List FSx Lustre file systems → CSV
python3 fsx_mw_scheduler.py list --region us-east-2

# 2. Edit CSV to keep only target file systems

# 3. Deploy
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv
```

## Cleanup

```bash
python3 fsx_mw_scheduler.py clean --region us-east-2 --fs-id fs-xxxx
```

## Architecture

```
EventBridge Scheduler                EventBridge Scheduler
rate(14 days)                        rate(14 days)
StartDate = MW − 12h                 StartDate = MW + 12h
       │                                    │
       ▼                                    ▼
  Skip Lambda                         Restore Lambda
  MW → original − 24h                 MW → original
```

## Cost

Effectively zero (2 Lambda invocations per FS per 14 days).

## Files

| File | Description |
|---|---|
| `fsx_mw_scheduler.py` | Main script (list + deploy + clean) |
| `iam-policy.json` | IAM policy for operator user (replace ACCOUNT_ID) |
| `lambda-execution-role-policy.json` | Lambda execution role policy |
| `README.md` | This file |
| `README_ZH.md` | Chinese documentation |
