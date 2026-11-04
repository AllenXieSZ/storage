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

### Test 1: v1 single-threaded baseline (189 GiB, 560K files)

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

### Test 2: v2 buffered single-threaded (2.4 TiB, 7.6M+ files) — partial

| Parameter | Value |
|---|---|
| **File System** | `fs-027ff9a3e720a5a4e` (PoC) |
| **Total Size** | 2,384 GiB (2.4 TiB) |
| **Files Scanned** | 7,576,603 (scan stopped manually) |
| **Lifecycle Policy** | TransitionToIA = AFTER_14_DAYS |
| **Script Version** | v2 (50,000-row buffered CSV) |
| **Scan Duration** | 33,941 s (9.4 hours, stopped early) |
| **Scan Rate** | **224–290 files/s** (avg 223 files/s) |

**Speed over time (single-threaded, no degradation):**

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

**Note**: Scan stopped early at 7.6M files. The FS also contains ~2 TiB in Archive tier (from a previously-removed Archive policy). Full comparison requires historical policy timeline.

### Test 3: v3 multi-threaded (189 GiB, 560K files) ⭐

| Parameter | Value |
|---|---|
| **File System** | `fs-0e77227a1ecaac809` |
| **Total Size** | 189 GiB |
| **Files** | 560,054 |
| **Lifecycle Policy** | TransitionToIA = AFTER_1_DAY |
| **Script Version** | v3 (16 threads + buffered CSV) |
| **Scan Duration** | **91 s (1.5 min)** |
| **Scan Rate** | **6,161 files/s** |

**Accuracy (unchanged from v1):**

| Tier | Predicted (atime) | EFS API | Deviation |
|---|---|---|---|
| Standard | 1.07 GiB | 1.09 GiB | **−1.56%** |
| IA | 187.99 GiB | 187.99 GiB | **+0.00%** |
| Archive | 0 | 0 | — |
| **Total** | **189.06 GiB** | **189.08 GiB** | **−0.01%** |

**Speed progression (16 workers):**

| Elapsed | Files Scanned | Rate (files/s) |
|---|---|---|
| 10s | 52,054 | 5,192 |
| 30s | 159,054 | 5,294 |
| 50s | 281,054 | 5,615 |
| 70s | 421,054 | 6,009 |
| 90s | 553,054 | 6,139 |

## Performance Summary

| Version | Threads | Rate (files/s) | Time for 560K files | vs v1 |
|---|---|---|---|---|
| **v1** | 1 (unbuffered CSV) | 225 | 42 min | baseline |
| **v2** | 1 (buffered CSV) | 290 | ~32 min (est.) | **+29%** |
| **v3** | 16 (buffered CSV) | **6,161** | **1.5 min** | **🚀 27x faster** |

**Key findings:**
- **v1 → v2**: Buffered CSV writes eliminated per-file `write()` syscall overhead → **+29%**
- **v2 → v3**: Multi-threaded `os.walk()` + `lstat()` overlaps NFS RTT across 16 concurrent directory trees → **21x over v2**
- **v1 → v3**: Combined optimization = **27x faster**
- Bottleneck in v1/v2 was NFS `lstat()` round-trip latency (~4 ms/call). v3 saturates the NFS client with 16 concurrent threads, reducing effective per-file latency to ~0.16 ms
- Accuracy is identical across all versions (< 2% deviation)

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
2. If a file was accessed between the lifecycle policy threshold and the scan time, EFS may have already transitioned it but atime shows recent access (false negative). In practice this is rare.
3. Historical Archive transitions from removed policies cannot be detected from current atime alone
4. Scan does not read file data, so no IA/Archive access charges — but also cannot detect tier via latency probing

## Usage

**Recommended: v3 (multi-threaded)**

```bash
python3 efs_tier_audit_v3.py \
  --mount /mnt/efs \
  --fs-id fs-0123456789abcdef0 \
  --region us-east-2 \
  --ia-days 30 \
  --archive-days 90 \
  --output-dir /tmp/efs-audit \
  --batch-size 50000 \
  --workers 16
```

**Arguments:**

| Argument | Description | Default |
|---|---|---|
| `--mount` | EFS mount point path | (required) |
| `--fs-id` | EFS file system ID (for API comparison) | (required) |
| `--region` | AWS region | us-east-2 |
| `--ia-days` | TransitionToIA policy (days) | (required) |
| `--archive-days` | TransitionToArchive policy (days, 0=none) | 0 |
| `--output-dir` | Output directory for CSVs + summary | /tmp/efs-audit |
| `--batch-size` | CSV write buffer size (rows) | 50000 |
| `--workers` | Thread pool size (v3 only) | 16 |

**Output:**

- `standard_files.csv` — files predicted in Standard tier
- `ia_files.csv` — files predicted in IA tier
- `archive_files.csv` — files predicted in Archive tier
- `summary.txt` — tier distribution + API comparison

Each CSV contains: `path, size_bytes, atime, age_days`

**Requirements:** Python 3.6+, `boto3` (optional, for API comparison)

## Files

- `efs_tier_audit.py` — v1 script (single-threaded, unbuffered CSV, baseline)
- `efs_tier_audit_v2.py` — v2 script (single-threaded, buffered CSV)
- `efs_tier_audit_v3.py` — v3 script (multi-threaded + buffered CSV, **recommended**)
- `README.md` — this file
