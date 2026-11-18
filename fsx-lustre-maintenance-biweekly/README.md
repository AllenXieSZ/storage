# FSx for Lustre Maintenance Window — Biweekly Scheduler (v2)

[中文](README_ZH.md)

FSx for Lustre maintenance windows are weekly; there is no biweekly option. In a **skip week** this tool moves the window one day earlier (to a time that has already passed), then moves it back afterwards, so patches land at most once every two weeks.

> AWS docs: patching happens "typically once every several weeks", not every week, and a window must be **scheduled at least once every 14 days**, otherwise FSx applies a pending patch anyway. See [Maintenance windows](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html).

## How it works

```
EventBridge Scheduler (cron, UTC, weekly)
  skip    schedule: original MW −12h → in a skip week, set MW = original −24h
  restore schedule: original MW +12h → set MW = original (runs every week as a safety net)
                │
                ▼
     Lambda fsx-mw-scheduler (shared by all file systems)
       reads the CSV from S3 on every run → original MW → writes an absolute value
```

Example: original MW `3:02:00` (Wed 02:00)

| Schedule | cron | Action |
|---|---|---|
| skip | `cron(0 14 ? * TUE *)` Tue 14:00 | skip week: set `2:02:00` (Tue 02:00, already past) → no maintenance this Wed |
| restore | `cron(0 14 ? * WED *)` Wed 14:00 | set back to `3:02:00` |

## What changed from v1

| v1 problem (verified by test) | v2 |
|---|---|
| `rate(14 days)` is anchored at rule creation time; both rules fired together, nothing was skipped and the window could drift | **cron** derived from the CSV window; the Lambda decides whether this is a skip week |
| read current value ±24h — duplicates accumulate | **Idempotent**: reads the original window from the CSV every run and writes an absolute value; no API call if already at target |
| no error handling | pre-checks (AVAILABLE, no running admin action) + API retry + read-back check; failures → retries → **SQS DLQ** → **CloudWatch alarm → SNS** |
| two Lambdas per FS | one shared Lambda, reserved concurrency = 1 |

## Usage

```bash
# 1. List Lustre file systems; keep only the ones to make biweekly in the CSV
python3 fsx_mw_scheduler.py list --region us-east-2

# 2. Deploy (CSV is uploaded to S3; --first-skip-week = any day in the first skip week, default this week)
python3 fsx_mw_scheduler.py deploy --region us-east-2 --bucket <bucket-in-same-region> \
    --csv fsx_lustre_list.csv --first-skip-week 2026-11-23 --email ops@example.com

# 3. To change the original window: edit the CSV and deploy again (updates the S3 CSV and the cron)

# 4. Remove schedules
python3 fsx_mw_scheduler.py remove --region us-east-2 --all
```

CSV (`MaintenanceWindow` = original window, `d:HH:MM`, d=1 Mon … 7 Sun, UTC):
```csv
Name,FileSystemId,MaintenanceWindow,MaintenanceWindowHuman,Timezone
mw-biweekly-test,fs-0eeabbe93f4cc61f0,3:02:00,Wed 02:00 UTC,UTC
```

## Test results (2026-11-18, us-east-2, SCRATCH_2 1200 GiB, original MW 3:02:00)

Script: `test_v2.sh`

| # | Case | Window | Result |
|---|---|---|---|
| T1 | skip in a skip week | `3:02` → `2:02` | ✅ |
| T2 | skip again | stays `2:02` (NO_CHANGE) | ✅ idempotent |
| T3 | restore | `2:02` → `3:02` | ✅ |
| T4 | restore again | stays `3:02` (NO_CHANGE) | ✅ idempotent |
| T5 | skip in a non-skip week (12-01) | unchanged (NOT_SKIP_WEEK) | ✅ |
| T6 | skip the week after (12-08) | `3:02` → `2:02` | ✅ alternates; across year end: 12-22 skip / 12-29 maintain / 01-05 skip |
| T7 | skip and restore at the same time | serialized, ends at `3:02` | ✅ no drift |
| T8 | window manually set to `6:10`, then restore | `6:10` → `3:02` | ✅ corrected from CSV |
| T9 | only the S3 CSV changed to `5:18:30`, no redeploy | restore writes `5:18:30` | ✅ CSV read on every run |
| T10 | FS missing from CSV | error `CSV 中找不到文件系统` | ✅ |
| T11 | invalid event | error `事件参数非法` | ✅ |
| T12 | real Scheduler trigger (one-time schedule) | valid FS: `3:02` → `2:02`; non-existent FS: ran 3 times (1 + 2 retries), then DLQ (RetriesExhausted); alarm `fsx-mw-lambda-errors` went to ALARM | ✅ |

> Finding: Scheduler invokes Lambda asynchronously, so **function errors do not reach the Scheduler DLQ** (that one only covers delivery failures). The Lambda async OnFailure destination must be configured too; v2 sends both to `fsx-mw-dlq`.

## Notes

- Two real maintenance runs are exactly 14 days apart — **no margin**. The docs do not say whether "scheduled" means a window exists or a window has passed; **assumption (not tested)**: a window always being scheduled is enough.
- A real patch event cannot be triggered on demand, so "no patch was applied in the skip week" is not tested.
- If the original window is on Monday, skip fires on Sunday 14:00; the week is decided by the maintenance day, so it does not pick the wrong week.

## Files

| File | Description |
|---|---|
| `fsx_mw_scheduler.py` | Deploy script: `list` / `deploy` / `remove` |
| `lambda_function.py` | Lambda code |
| `test_v2.sh` | Test script |
| `iam-policy.json` | Permissions needed to run the deploy script |
