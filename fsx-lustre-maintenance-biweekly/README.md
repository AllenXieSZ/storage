# FSx Lustre Maintenance Window — Biweekly Scheduler

Convert Amazon FSx for Lustre weekly maintenance windows into **biweekly (every 2 weeks)** using Lambda + EventBridge Scheduler.

## How It Works

Two Lambda functions per file system (idempotent, absolute value):

- **Skip Lambda**: sets MW to `original − 24h`
- **Restore Lambda**: sets MW back to `original`

### Trigger Schedule (all EventBridge Scheduler)

| Schedule | Type | Purpose |
|---|---|---|
| `fsx-mw-skip-init-{fs-id}` | `at()` one-shot | First skip, aligned to MW−12h. Auto-deletes after fire. |
| `fsx-mw-restore-init-{fs-id}` | `at()` one-shot | First restore, aligned to MW+12h. Auto-deletes after fire. |
| `fsx-mw-skip-cycle-{fs-id}` | `rate(14 days)` | Ongoing skip, `StartDate` = first skip + 14 days. |
| `fsx-mw-restore-cycle-{fs-id}` | `rate(14 days)` | Ongoing restore, `StartDate` = first restore + 14 days. |

### Key Design: skip and restore never fire at the same time

Skip fires at MW−12h, restore fires at MW+12h — 24 hours apart. The `rate(14 days)` schedules use `StartDate` aligned to their respective fire times, so they stay properly offset forever.

### Timeline Example

MW = Wed 02:00 UTC:
```
Week 1 (skip):
  Tue 14:00  skip-init at() → MW = Tue 02:00 (past → no maintenance this week)
  Wed 14:00  restore-init at() → MW = Wed 02:00 (restored for next cycle)
  init schedules auto-delete

Week 2 (normal):
  No triggers (rate(14d) StartDate not reached yet)
  MW = Wed 02:00 → maintenance runs normally ✅

Week 3 (skip):
  Tue 14:00  skip-cycle rate(14d) → MW = Tue 02:00
  Wed 14:00  restore-cycle rate(14d) → MW = Wed 02:00
  ...repeats every 14 days
```

### Why all EventBridge Scheduler (not Rules)?

The previous version used EventBridge Rules `rate(14 days)` for ongoing triggers. This had a fatal flaw:
- Rules `rate()` fires based on **creation time**, with no `StartDate` control
- skip and restore rules created at the same time → **fire at the same time → conflict**
- Rules don't support `at()` expressions (`ValidationException`)

EventBridge Scheduler supports both `at()` and `rate()` + `StartDate`, solving both problems.

### Deployment Timing ⚠️

**Deploy in the week AFTER a successful maintenance.** The first `at()` trigger will skip the next maintenance window. If the previous week was also skipped → exceeds 14-day limit → AWS may force maintenance.

## Quick Start

```bash
# 1. List FSx Lustre file systems → CSV
python3 fsx_mw_scheduler.py list --region us-east-2

# 2. Edit CSV to keep only target file systems

# 3. Deploy (creates Lambda + Scheduler at() + Scheduler rate(14d))
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv

# MW is NOT changed immediately — waits for at() trigger at the precise time
```

## Cleanup

```bash
# Clean up all resources for one file system (including legacy EB Rules)
python3 fsx_mw_scheduler.py clean --region us-east-2 --fs-id fs-xxxx
```

## Architecture

```
EventBridge Scheduler at()           EventBridge Scheduler at()
(first trigger, auto-delete)         (first trigger, auto-delete)
     │                                     │
     ▼                                     ▼
 Skip Lambda ────────────────────── Restore Lambda
 MW → original − 24h                MW → original
     ▲                                     ▲
     │                                     │
EventBridge Scheduler rate(14d)     EventBridge Scheduler rate(14d)
StartDate = skip first + 14d        StartDate = restore first + 14d
```

## Cost

Effectively zero (2 Lambda invocations per FS per 14 days + Scheduler free tier).

## Files

| File | Description |
|---|---|
| `fsx_mw_scheduler.py` | Main script (list + deploy + clean) |
| `iam-policy.json` | IAM policy for operator user (replace ACCOUNT_ID) |
| `lambda-execution-role-policy.json` | Lambda execution role policy |
| `README.md` | This file |
| `README_ZH.md` | Chinese documentation |
