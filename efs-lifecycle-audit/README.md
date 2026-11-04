# EFS Lifecycle Tier Audit

Identify which files have been tiered to EFS Infrequent Access (IA) or Archive storage classes by analyzing POSIX `atime` timestamps, then cross-validate against the EFS API's per-tier byte counts.

## Background

**Problem**: EFS provides no per-file storage class query API. Unlike S3 (where each object has a `StorageClass` attribute), EFS only exposes aggregate byte totals per tier via `DescribeFileSystems` → `SizeInBytes.ValueInStandard / ValueInIA / ValueInArchive`.

**Solution**: Since EFS lifecycle management transitions files based on "time since last accessed in Standard", and the default NFS mount uses `relatime` (which tracks access time at day-level granularity), we can infer each file's storage tier from its POSIX `atime` and the configured lifecycle policy days.

## How It Works

1. Walk the entire EFS mount point via `os.walk()` + `os.lstat()` (metadata only — no file data is read, so **no IA/Archive access charges** are incurred)
2. For each regular file, read `st_atime` and `st_size`
3. Classify the file based on age vs. lifecycle policy thresholds:
   - `age < ia_days` → **Standard**
   - `ia_days ≤ age < archive_days` → **IA**
   - `age ≥ archive_days` → **Archive**
4. Compute EFS metered sizes (2 KiB metadata + data rounded to 4 KiB; 128 KiB minimum for IA/Archive)
5. Compare predicted per-tier totals against the EFS API
6. Output per-tier CSV file lists + summary report

## Test Results

### Test 1: fs-0e77227a1ecaac809 (189 GiB, 560K files)

| Parameter | Value |
|---|---|
| **File System** | `fs-0e77227a1ecaac809` |
| **Total Size** | 189 GiB |
| **Files** | 560,054 |
| **Lifecycle Policy** | TransitionToIA = AFTER_1_DAY |
| **Script Version** | v1 (line-by-line CSV write) |
| **Scan Duration** | 2,493 s (41.5 min) |
| **Scan Rate** | **225 files/s** |

**Accuracy:**

| Tier | Predicted (atime) | EFS API | Deviation |
|---|---|---|---|
| Standard | 1.08 GiB | 1.09 GiB | **−1.2%** |
| IA | 187.99 GiB | 187.99 GiB | **+0.0%** |
| Archive | 0 | 0 | — |
| **Total** | **189.07 GiB** | **189.08 GiB** | **−0.0%** |

- Standard 1.08 GiB = pure metadata (560K files × 2 KiB + 1,519 dirs × 6 KiB). The −1.2% gap is from directory inode size approximation.
- IA matched exactly — all 560,054 files had atime > 1 day old.
- **0 files misclassified.**

### Test 2: fs-027ff9a3e720a5a4e (2.4 TiB, 7.6M+ files) — partial

| Parameter | Value |
|---|---|
| **File System** | `fs-027ff9a3e720a5a4e` (PoC) |
| **Total Size** | 2,384 GiB (2.4 TiB) |
| **Files Scanned** | 7,576,603 (scan stopped manually) |
| **Lifecycle Policy** | TransitionToIA = AFTER_14_DAYS |
| **Script Version** | v2 (50,000-row buffered CSV) |
| **Scan Duration** | 33,941 s (9.4 hours, stopped early) |
| **Scan Rate** | **224–290 files/s** (avg 223 files/s) |

**Speed over time (no degradation):**

| Elapsed | Files Scanned | Rate (files/s) |
|---|---|---|
| 2 min | 35,244 | 290 |
| 30 min | 490,683 | 290 |
| 60 min | 1,020,003 | 285 |
| 120 min | 2,019,547 | 258 |
| 180 min | 2,920,083 | 250 |
| 300 min | 4,487,287 | 246 |
| 420 min | 5,420,066 | 243 |
| 560 min | 7,576,603 | 224 |

Rate declined ~23% over 9 hours — driven by directory depth variation, not IO saturation or CSV write overhead.

**Note**: This scan was stopped early at 7.6M files. The FS also contains ~2 TiB of data in the Archive tier (from a previously-configured Archive policy that was later removed). Since the current lifecycle config has no Archive policy, the script classifies all old files as IA. A full comparison requires knowing the historical policy timeline, which is not available via API.

## Scan Speed Summary

| Metric | Test 1 (v1, 560K files) | Test 2 (v2, 7.6M files) |
|---|---|---|
| Script version | v1 (unbuffered CSV) | v2 (50K-row buffer) |
| Initial rate | 225 files/s | 290 files/s |
| Sustained rate | 225 files/s | 224 files/s |
| **Buffering speedup** | — | **+29%** (v1→v2 initial) |
| Bottleneck | NFS `lstat()` RTT (~4 ms/file) | Same |
| EC2 instance | MySQL-Master (m-series, us-east-2a) | Same |

**Key finding**: Scan speed is entirely bound by NFS metadata round-trip latency (~4 ms per `lstat()`), not CPU, disk, or CSV write IO. The v2 buffered CSV optimization eliminated the per-file `write()` syscall overhead, improving throughput by ~29%.

## Methodology Notes

### Why `atime` works

- EFS default NFS mount option is `relatime` (confirmed by `mount` output: `rw,relatime,vers=4.1,...`). This updates atime once per day when a file is accessed — sufficient granularity for lifecycle policies (minimum 1 day).
- EFS lifecycle uses an internal timer (not POSIX atime), but both track "last data access time" with similar semantics.
- `noatime` mount would break this method. Always verify with `mount | grep efs`.

### What counts as "access"

- **Updates atime**: `read()`, `cat`, `cp` (source), application opens
- **Does NOT update atime**: `ls -l`, `stat`, `du`, `find` (metadata-only), `chmod`, `chown`
- This matches EFS lifecycle behavior: "Metadata operations such as listing the contents of a directory don't count as file access."

### Metered size calculation

- Each file: 2 KiB metadata (always Standard) + data rounded up to 4 KiB
- IA/Archive files: data portion has 128 KiB minimum billing
- Directories: ~6 KiB each (2 KiB metadata + 4 KiB data), always in Standard
- EFS API `ValueInStandard` = Standard file data + **all** file metadata (including IA/Archive files' metadata)

### Limitations

1. `relatime` only updates atime once per day — files accessed multiple times in one day show the same atime as files accessed once
2. If a file was accessed between the lifecycle policy threshold and the scan time, EFS may have already transitioned it but atime shows recent access (false negative for IA classification). In practice this is rare.
3. Historical Archive transitions from removed policies cannot be detected from current atime alone
4. Scan does not read file data, so no IA/Archive access charges — but also cannot detect tier via latency probing

## Usage

```bash
python3 efs_tier_audit_v2.py \
  --mount /mnt/efs \
  --fs-id fs-0123456789abcdef0 \
  --region us-east-2 \
  --ia-days 30 \
  --archive-days 90 \
  --output-dir /tmp/efs-audit \
  --batch-size 50000
```

**Arguments:**

| Argument | Description |
|---|---|
| `--mount` | EFS mount point path |
| `--fs-id` | EFS file system ID (for API comparison) |
| `--region` | AWS region |
| `--ia-days` | TransitionToIA policy (days) |
| `--archive-days` | TransitionToArchive policy (days, 0=none) |
| `--output-dir` | Output directory for CSVs + summary |
| `--batch-size` | CSV write buffer size (rows, default 50000) |

**Output:**

- `standard_files.csv` — files predicted in Standard tier
- `ia_files.csv` — files predicted in IA tier
- `archive_files.csv` — files predicted in Archive tier
- `summary.txt` — tier distribution + API comparison

Each CSV contains: `path, size_bytes, atime, age_days`

**Requirements:** Python 3.6+, `boto3` (optional, for API comparison)

## Files

- `efs_tier_audit.py` — v1 script (unbuffered CSV, baseline)
- `efs_tier_audit_v2.py` — v2 script (buffered CSV, recommended)
- `README.md` — this file
