# EFS Lifecycle Tier Audit

Identify which files have been tiered to EFS Infrequent Access (IA) or Archive storage classes by analyzing POSIX `atime` timestamps, then cross-validate against the EFS API's per-tier byte counts.

## Background

**Problem**: EFS provides no per-file storage class query API. Unlike S3 (where each object has a `StorageClass` attribute), EFS only exposes aggregate byte totals per tier via `DescribeFileSystems` → `SizeInBytes.ValueInStandard / ValueInIA / ValueInArchive`.

**Solution**: Since EFS lifecycle management transitions files based on "time since last accessed in Standard", and the default NFS mount uses `relatime` (which tracks access time at day-level granularity), we can infer each file's storage tier from its POSIX `atime` and the configured lifecycle policy days.

## How It Works

1. Multi-threaded `os.walk()` + `os.lstat()` across top-level subdirectories (metadata only — **no file data is read**, so **no IA/Archive access charges** are incurred, and **no atime updates** are triggered)
2. For each regular file, read `st_atime` and `st_size` from the inode
3. Classify the file based on age vs. lifecycle policy thresholds:
   - `age < ia_days` → **Standard**
   - `ia_days ≤ age < archive_days` → **IA**
   - `age ≥ archive_days` → **Archive**
4. Compute EFS metered sizes (2 KiB metadata + data rounded to 4 KiB; 128 KiB minimum for IA/Archive)
5. Compare predicted per-tier totals against the EFS API
6. Output per-tier CSV file lists + summary report

## Test Results

### Test 1: 189 GiB, 560K files

| Parameter | Value |
|---|---|
| **File System** | `fs-0e77227a1ecaac809` |
| **Total Size** | 189 GiB |
| **Files** | 560,054 |
| **Lifecycle Policy** | TransitionToIA = AFTER_1_DAY |
| **Workers** | 16 threads |
| **Scan Duration** | **91 s (1.5 min)** |
| **Scan Rate** | **6,161 files/s** |

**Accuracy:**

| Tier | Predicted (atime) | EFS API | Deviation |
|---|---|---|---|
| Standard | 1.07 GiB | 1.09 GiB | **−1.56%** |
| IA | 187.99 GiB | 187.99 GiB | **+0.00%** |
| Archive | 0 | 0 | — |
| **Total** | **189.06 GiB** | **189.08 GiB** | **−0.01%** |

- Standard 1.07 GiB = pure metadata (560K files × 2 KiB + 760 dirs × 6 KiB). The −1.56% gap is from directory inode size approximation (actual directory data size varies with entry count).
- IA matched exactly — all 560,054 files had atime > 1 day old.
- **0 files misclassified.**

**Speed progression:**

| Elapsed | Files Scanned | Rate (files/s) |
|---|---|---|
| 10s | 52,054 | 5,192 |
| 30s | 159,054 | 5,294 |
| 50s | 281,054 | 5,615 |
| 70s | 421,054 | 6,009 |
| 91s | 560,054 | 6,161 |

### Test 2: 2.4 TiB, 7.6M+ files (partial scan)

| Parameter | Value |
|---|---|
| **File System** | `fs-027ff9a3e720a5a4e` |
| **Total Size** | 2,384 GiB (2.4 TiB) |
| **Files Scanned** | 7,576,603 (scan stopped manually) |
| **Lifecycle Policy** | TransitionToIA = AFTER_14_DAYS |
| **Workers** | 1 thread (ran before multi-threaded version) |
| **Scan Duration** | 33,941 s (9.4 hours, stopped early) |
| **Scan Rate** | 224–290 files/s (single-threaded) |

**Speed over time (single-threaded, sustained without degradation):**

| Elapsed | Files Scanned | Rate (files/s) |
|---|---|---|
| 2 min | 35,244 | 290 |
| 60 min | 1,020,003 | 285 |
| 180 min | 2,920,083 | 250 |
| 420 min | 5,420,066 | 243 |
| 560 min | 7,576,603 | 224 |

At multi-threaded rates (~6,000 files/s), this 7.6M file scan would complete in ~21 minutes instead of 9+ hours.

## Performance

- **Scan rate**: ~6,000 files/s with 16 threads (tested on a general-purpose EC2 instance)
- **Bottleneck**: NFS `lstat()` round-trip latency. Multi-threading overlaps RTT across concurrent directory subtrees, achieving ~27× throughput vs single-threaded traversal.
- **Cost**: Zero. Only metadata operations (`lstat`) are performed — no file data reads, no IA/Archive access charges, no atime updates.
- **Accuracy**: < 2% deviation from EFS API reported sizes. IA tier matched exactly in testing.

## Methodology Notes

### Why `atime` works

- EFS default NFS mount option is `relatime` (confirmed: `rw,relatime,vers=4.1,...`). This updates atime once per day when a file is accessed — sufficient granularity for lifecycle policies (minimum 1 day).
- EFS lifecycle uses an internal timer (not POSIX atime), but both track "last data access time" with similar semantics.
- `noatime` mount would break this method. Always verify with `mount | grep efs`.

### What counts as "access"

- **Updates atime**: `read()`, `cat`, `cp` (source), application `open()+read()`
- **Does NOT update atime**: `ls -l`, `stat`, `du`, `find` (metadata-only), `chmod`, `chown`
- This matches EFS lifecycle behavior: "Metadata operations such as listing the contents of a directory don't count as file access."

### Metered size calculation

- Each file: 2 KiB metadata (always in Standard) + data rounded up to 4 KiB
- IA/Archive files: data portion has 128 KiB minimum billing
- Directories: ~6 KiB each (2 KiB metadata + 4 KiB data), always in Standard
- EFS API `ValueInStandard` includes all file metadata (including metadata of IA/Archive files)

### Limitations

1. `relatime` updates atime at most once per day — granularity is sufficient for lifecycle policies but not sub-day precision
2. Historical Archive transitions from removed policies cannot be detected from current atime alone
3. Files accessed between the policy threshold and scan time may show as Standard when EFS has already transitioned them (rare in practice)

## Usage

```bash
python3 efs_tier_audit.py \
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
| `--archive-days` | TransitionToArchive policy (days, 0 = none) | 0 |
| `--output-dir` | Output directory for CSVs + summary | /tmp/efs-audit |
| `--batch-size` | CSV write buffer size (rows) | 50000 |
| `--workers` | Thread pool size | 16 |

**Output:**

- `standard_files.csv` — files predicted in Standard tier
- `ia_files.csv` — files predicted in IA tier
- `archive_files.csv` — files predicted in Archive tier
- `summary.txt` — tier distribution + API comparison

Each CSV contains: `path, size_bytes, atime, age_days`

**Requirements:** Python 3.6+, `boto3` (optional, for API comparison)
