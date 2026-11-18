# FSx Lustre Maintenance Window — Biweekly Scheduler

Convert Amazon FSx for Lustre weekly maintenance windows into **biweekly (every 2 weeks)** using Lambda + EventBridge.

## How It Works

Two Lambda functions per file system (idempotent, absolute value):

- **Skip Lambda**: sets MW to `original − 24h`
- **Restore Lambda**: sets MW back to `original`

### Trigger Schedule

| Rule | Type | Purpose |
|---|---|---|
| `fsx-mw-skip-init-{fs-id}` | Scheduler `at()` | First skip, precisely aligned to next MW−12h UTC. Auto-deletes after fire. |
| `fsx-mw-restore-init-{fs-id}` | Scheduler `at()` | First restore, precisely aligned to next MW+12h UTC. Auto-deletes after fire. |
| `fsx-mw-skip-{fs-id}` | Rules `rate(14 days)` | Ongoing skip every 14 days from deploy time. |
| `fsx-mw-restore-{fs-id}` | Rules `rate(14 days)` | Ongoing restore every 14 days from deploy time. |

**Why two types?** EventBridge Rules `rate()` starts from creation time (not MW time). Rules don't support `at()` (returns `ValidationException`). EventBridge Scheduler supports `at()` with `ActionAfterCompletion=DELETE`. So: Scheduler handles precise first trigger, Rules handle ongoing 14-day cycles.

### Deployment Timing ⚠️

**Deploy in the week AFTER a successful maintenance.** The first `at()` trigger will skip the next maintenance window. If the previous week was also skipped → exceeds 14-day limit → AWS forces maintenance.

## Quick Start

```bash
# 1. List FSx Lustre file systems → CSV
python3 fsx_mw_scheduler.py list --region us-east-2

# 2. Edit CSV to keep only target file systems

# 3. Deploy (creates Lambda + Scheduler at() + Rules rate(14d))
python3 fsx_mw_scheduler.py deploy --region us-east-2 --csv fsx_lustre_list.csv

# MW is NOT changed immediately — waits for at() trigger at the precise time
```

## Test Results (2026-11-18)

Tested with 2 FSx Lustre SCRATCH_2 file systems (us-east-2).

### mw-test-1 (MW = Wed 02:00 UTC / `3:02:00`)

| Action | MW Change | Result |
|---|---|---|
| Manual invoke skip | `3:02:00` → `2:02:00` | `changed: true` |
| Invoke skip again (idempotent) | `2:02:00` unchanged | `changed: false` |
| Invoke restore | `2:02:00` → `3:02:00` | `changed: true` |

### Issues Found & Fixed During Development

| Issue | Impact | Fix |
|---|---|---|
| Relative shift (±24h) | Double-shift on re-invoke | Absolute value (idempotent) |
| Immediate invoke on deploy | MW changed at wrong time | Replaced with Scheduler `at()` |
| EventBridge Rules `at()` | `ValidationException` | Use EventBridge Scheduler |
| Lambda Pending on invoke | `ResourceConflictException` | Wait for Active state (later removed with invoke removal) |

## Architecture

```
EventBridge Scheduler at()          EventBridge Scheduler at()
(first trigger, auto-delete)        (first trigger, auto-delete)
     │                                    │
     ▼                                    ▼
 Skip Lambda                          Restore Lambda
 MW → original − 24h                  MW → original
     ▲                                    ▲
     │                                    │
EventBridge Rules rate(14 days)      EventBridge Rules rate(14 days)
(ongoing cycle)                      (ongoing cycle)
```

## Cost

Effectively zero (2 Lambda invocations per FS per 14 days).

## Cleanup

```bash
FS_ID=fs-xxxx; REGION=us-east-2
for prefix in fsx-mw-skip fsx-mw-restore; do
  aws events remove-targets --rule "${prefix}-${FS_ID}" --ids "target-${prefix}-${FS_ID}" --region $REGION 2>/dev/null
  aws events delete-rule --name "${prefix}-${FS_ID}" --region $REGION 2>/dev/null
  aws lambda delete-function --function-name "${prefix}-${FS_ID}" --region $REGION 2>/dev/null
  aws scheduler delete-schedule --name "${prefix}-init-${FS_ID}" --region $REGION 2>/dev/null
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
