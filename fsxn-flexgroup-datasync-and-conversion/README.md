# FSx for NetApp ONTAP — FlexGroup Cross-HA Distribution & In-Place FlexVol→FlexGroup Conversion

**语言 / Language**: [中文](./README_ZH.md) · English (this page)

> 📌 **Why so fast/slow?** Metadata ops vs physical ops timing — see [WHY_FAST_SLOW.md](../fsxn-flexgroup-rebalance/WHY_FAST_SLOW.md):
> FlexVol→FlexGroup conversion / expand **<1min** (metadata only, no data move); throughput scale **~36-44min**, add HA pair **~10-26min** (provision real servers); volume move **1h54m** (physically moves 1TB hot volume).

A focused, clean record of two experiments run on **Amazon FSx for NetApp ONTAP (Gen2, ONTAP 9.18.1P5, us-east-2)**:

1. **DataSync transfer + rebalance** — copy 800 GB from a 1‑HA‑pair FlexVol into a 2‑HA‑pair FlexGroup and observe whether data auto-balances across the two aggregates. Full timings + observations.
2. **In-place FlexVol → FlexGroup conversion** — convert a FlexVol to a FlexGroup *in place* (no data copy), expand it across both aggregates, and measure how data distribution converges. Detailed process + charts.

> All numbers below are **measured**, not inferred. Resource IDs, account IDs and IPs are redacted with `<...>` placeholders.

---

## Environment

| Item | Value |
|---|---|
| Service | FSx for NetApp ONTAP, **Gen2** (`DeploymentType=SINGLE_AZ_2`) |
| ONTAP version | 9.18.1P5 |
| Region / AZ | us-east-2 / us-east-2c |
| Bastion | EC2 via SSM, `sshpass`/`expect` installed → drives ONTAP CLI |
| ONTAP admin | `fsxadmin` (password redacted) |
| `volume conversion` | Hidden at admin level on FSx; requires `set -privilege diagnostic` |

Gen2 HA/throughput constraint learned the hard way:
- **1 HA pair** accepts `ThroughputCapacityPerHAPair=384`.
- **2 HA pairs** only accept `[1536, 3072, 6144]`.
- You **cannot** jump 1HA/384 → 2HA directly: FSx wants throughput unchanged while expanding HA, but 2HA rejects 384. **You must first raise throughput to 1536 within 1HA, then expand to 2HA.**

---

# Part 1 — DataSync transfer + rebalance

**Goal:** Copy `8 × 100 GiB = 800 GiB` from a **1‑HA‑pair FlexVol** (source) into a **2‑HA‑pair FlexGroup** (target, 8 constituents across aggr1+aggr2) via **AWS DataSync**, then check whether the data auto-balances **aggr1 ≈ aggr2**.

## Setup

```bash
# Source: 1 HA pair, Gen2 Single-AZ, 2048 GB, 384 MB/s
aws fsx create-file-system --file-system-type ONTAP --storage-capacity 2048 \
  --subnet-ids <SUBNET_ID> --region us-east-2 \
  --ontap-configuration \
  'DeploymentType=SINGLE_AZ_2,HAPairs=1,ThroughputCapacityPerHAPair=384,FsxAdminPassword=<PW>,PreferredSubnetId=<SUBNET_ID>'

# Target: 2 HA pairs, Gen2 Single-AZ
aws fsx create-file-system --file-system-type ONTAP --storage-capacity 2048 \
  --subnet-ids <SUBNET_ID> --region us-east-2 \
  --ontap-configuration \
  'DeploymentType=SINGLE_AZ_2,HAPairs=2,ThroughputCapacityPerHAPair=1536,FsxAdminPassword=<PW>,PreferredSubnetId=<SUBNET_ID>'
```

```bash
# SVMs (via aws CLI, NOT ONTAP `vserver create` which FSx blocks)
aws fsx create-storage-virtual-machine --file-system-id <SRC_FS_ID> --name srcsvm --region us-east-2
aws fsx create-storage-virtual-machine --file-system-id <DST_FS_ID> --name dstsvm --region us-east-2
```

```bash
# Source FlexVol
volume create -vserver srcsvm -volume srcvol -aggregate aggr1 \
  -size 1200GB -junction-path /srcvol -security-style unix

# Target FlexGroup: 8 constituents across aggr1 + aggr2 (multiplier 4)
volume create -vserver dstsvm -volume dstvol -aggr-list aggr1,aggr2 \
  -aggr-list-multiplier 4 -size 1600GB -junction-path /dstvol -security-style unix
```

```bash
# Generate 800 GiB of REAL (non-sparse) data on the source
mount -t nfs -o nfsvers=3 <SRC_NFS_IP>:/srcvol /mnt/src
for i in $(seq 1 8); do
  dd if=/dev/urandom of=/mnt/src/file_$i.bin bs=1M count=102400 status=progress
done
```

```bash
# DataSync: source + dest FSx-ONTAP locations, one task, BASIC mode (default)
aws datasync create-location-fsx-ontap ... # source SVM /srcvol (NFS)
aws datasync create-location-fsx-ontap ... # dest   SVM /dstvol (NFS)
aws datasync create-task --source-location-arn <SRC_LOC> --destination-location-arn <DST_LOC> ...
aws datasync start-task-execution --task-arn <TASK_ARN>
```

## Results — full transfer (800 GiB)

| Metric | Value |
|---|---|
| Bytes transferred / written | 858,993,459,200 B = **800 GiB** |
| Files | 9 (8 files + dir) |
| **Transfer duration** | 2,428,244 ms ≈ **40.5 min** |
| Transfer throughput | ≈ **354 MB/s** (0.345 GB/s) |
| **Verify duration** | 4,056,062 ms ≈ **67.6 min** ⚠️ |
| **Total duration** | ≈ **108.5 min** |

⚠️ **Observation:** With `VerifyMode=ONLY_FILES_TRANSFERRED`, the read-back verify on large files (67.6 min) is **1.67× longer than the transfer itself** (40.5 min). For large-file transfers, use `NONE` or `POINT_IN_TIME_CONSISTENT` to save wall time.

### Distribution after full transfer — **NOT balanced**

| Aggregate | Used | Share |
|---|---|---|
| aggr1 (node-01) | 209.0 GB | 23% |
| aggr2 (node-03) | 616.1 GB | 68% |

Per-constituent (8 constituents):
- aggr1: `0001`=0.5G, `0003`=0.5G, `0005`=102G, `0007`=102G → **2 files ≈ 204 G**
- aggr2: `0002`=202G, `0004`=202G, `0006`=102G, `0008`=102G → **6 files ≈ 608 G**

**Conclusion:** FlexGroup hashes **per file** onto constituents. With only 8 large files, the hash lands **6 on aggr2 / 2 on aggr1** → **≈ 200:600 (23:68)**, far from the ideal 400:400. FlexGroup constituents grow elastically (`0002`/`0004` auto-grew to ~305 GB to hold two 202 GB files). **Root cause of skew = too few files; hash noise dominates.**

## Results — incremental transfer (150 GiB)

Added new files to the source, re-ran the **same** DataSync task:

| Metric | Value |
|---|---|
| Bytes transferred | 161,061,273,600 B = **150 GiB** |
| Files transferred | 4 (3 new × 50 GiB + dir) |
| Transfer duration | 492,233 ms ≈ **8.2 min** |
| Throughput | ≈ **327 MB/s** |

- DataSync transferred **only the new files** (~150 GiB), **not** the 800 GiB again → confirms incremental behaviour. (150 not 100 GiB because an extra 50 GiB fio warm-up file on the source was also picked up as "new".)
- Distribution after increment: aggr1 = 311.6 GB (34%), aggr2 = 666.6 GB (73%) → **still skewed ~32:68**. The 3 new 50 GiB files each landed on a single constituent (`0001` 0.5→51.3G, `0002` 202→252.4G, `0003` 0.5→51.3G).

## DataSync cost (BASIC mode)

Source: <https://aws.amazon.com/datasync/pricing/> — BASIC mode **$0.0125 / GB** (per-GB rate is the same across regions).

| Transfer | Data | Cost (decimal GB) |
|---|---|---|
| Full (800 GiB) | 859.0 GB | **$10.74** |
| Incremental (150 GiB) | 161.06 GB | **$2.01** |
| **Total** | | **≈ $12.75** |

No cross-region / cross-AZ Data Transfer OUT charges (same region/VPC/account). FSxN SSD storage billed separately.

### fio during source in-place upgrade (context)

Separately, the **source** FSx was upgraded in place (1HA/384 → throughput 1536 → 2HA/4096) with fio running throughout. Timeline:

- **throughput 384→1536** (within 1HA): ~**44 min**. During upgrade throughput dropped to ~145–176 MiB/s (from ~340 baseline).
- **HA 1→2** (storage 2048→4096 simultaneously): ~**26 min**. After: aggr1 = 1.09 TB (62%), aggr2 = 880 KB (0%) → **100:0, all on aggr1**.

![Source FSx in-place upgrade — fio full-run performance](01_datasync_source_upgrade_fio_timeline.png)

⚠️ **The source FlexVol could NOT be converted to FlexGroup** — see the blocker below, which is exactly why Part 2 uses a clean control volume.

### ⛔ Blocker: a DataSync-source FlexVol cannot convert to FlexGroup

`volume conversion start` (diag) on the source volume failed:

```
Error: the destination of a SnapMirror relationship with source volume srcvol
is not a FlexVol volume. Delete and release the copy to cloud relationship...
```

- **Root cause:** `srcvol` was used as a **DataSync FSx-ONTAP source location**. DataSync's underlying mechanism is **SnapMirror-to-Cloud (SM-C)**, which leaves a hidden *copy-to-cloud* relationship + a reference snapshot (`backup-…`) on the source volume.
- This SM-C relationship is **invisible to the customer CLI** (`snapmirror show` / `list-destinations` all empty, even at diag) and **cannot be released** by `fsxadmin` — it is managed internally by the FSx service.
- Deleting the DataSync task + source location **does not** release it; the reference snapshot **cannot be deleted** (it's referenced by the hidden SM-C relationship).
- **Hard constraint:** *A FlexVol that has ever been a DataSync FSx-ONTAP source cannot be converted in place to FlexGroup.*

---

# Part 2 — In-place FlexVol → FlexGroup conversion (clean control)

**Goal:** On a **brand-new FlexVol that never touches DataSync**, run the identical upgrade path and prove the in-place conversion **succeeds** — isolating the DataSync-source identity as the true blocker in Part 1. Then expand the FlexGroup across both aggregates and measure how distribution converges.

## Full chain + timeline (measured, UTC)

fio (4K randrw 70% iodepth32 numjobs4 + 1M seqrw iodepth16 numjobs2, direct/libaio) ran continuously through the whole chain.

| Time (UTC) | Event | Duration | Notes |
|---|---|---|---|
| 01:19 | fio start (baseline, 1HA FlexVol) | — | ~157 MiB/s read + ~149 MiB/s write (**~306 MiB/s total**) |
| 01:22:03 | throughput 384→1536 START | | |
| 01:58:34 | throughput upgrade **COMPLETED** | **~36.5 min** | during: ~115 MiB/s write (degraded) |
| 01:58:44 | HA expand 1→2 + storage 2048→4096 START | | |
| 02:08:39 | HA expand **COMPLETED** | **~10 min** | aggr1 (node-01) + aggr2 (node-03) now present |
| 02:09:11 | `volume conversion start` (diag, Job 67) | | FlexVol→FlexGroup |
| 02:09:~40 | conversion **SUCCESS** | **< 1 min** | single constituent `mfvol__0001` on aggr1 |
| 02:10:10 | `volume expand -aggr-list aggr1,aggr2 -multiplier 4` (Job 71) | **SUCCESS** | → **9 constituents** |
| 02:12 – 02:21 | write 100 / 300 / 500 × 1 GiB files | ~90s / batch | measure distribution convergence |

### Conversion commands (measured, working)

```bash
ssh fsxadmin@<MGMT_IP>
set -privilege diagnostic -confirmations off

# Optional pre-flight (reports blockers without converting)
volume conversion start -vserver mfsvm -volume mfvol -check-only true
#   → only WARNINGs (irreversible / efficiency running / no capacity added), NO errors

# Convert in place (no data copy, no extra space)
volume conversion start -vserver mfsvm -volume mfvol
#   → [Job 67] Job succeeded   → single-constituent FlexGroup mfvol__0001 (aggr1)

# Expand across both aggregates → multi-aggr FlexGroup
volume expand -vserver mfsvm -volume mfvol -aggr-list aggr1,aggr2 -aggr-list-multiplier 4
#   → [Job 71] 9 constituents
#     aggr1: __0001,__0002,__0004,__0006,__0008 (5)
#     aggr2: __0003,__0005,__0007,__0009        (4)
```

> **Conversion is irreversible** (FlexGroup can't convert back to FlexVol; snapshots become pre-conversion). See `flexvol_to_flexgroup_conversion_prereqs.md` for the full NetApp prerequisite checklist.

### Result: conversion succeeds on a clean volume ✅

The clean FlexVol converted in **< 1 minute** with no errors. Combined with Part 1's blocker, this **double-confirms**:

- **DataSync-source identity is the real, hard blocker** for in-place conversion (residual hidden copy-to-cloud SM-C relationship + `backup-*` reference snapshot).
- A volume that **never** served as a DataSync source converts cleanly.

## fio across the whole chain

![Conversion full chain — fio timeseries](02_conversion_full_chain_fio.png)

- **Baseline (1HA/384):** ~306 MiB/s total.
- **Throughput upgrade / HA expand / convert+expand:** transient dips to ~90–140 MiB/s (volume operations interrupt I/O).
- **Steady state (2HA/1536):** **~900+ MiB/s** — roughly **3.5×** the 1HA baseline.

## Distribution convergence — hash converges fast; residual skew is *structural*

After conversion+expand, wrote 100 / 300 / 500 × 1 GiB files and measured per-aggregate share (fio's 49 GB baseline on `__0001` subtracted):

| Files | aggr1 % | aggr2 % | total GB |
|---|---|---|---|
| 100 | 56.4 | 43.6 | 108.2 |
| 300 | 55.3 | 44.7 | 310.2 |
| 500 | 55.0 | 45.0 | 510.9 |

![Multi-file distribution convergence](03_multifile_balance_convergence.png)

**Two-part conclusion:**

1. **File-hash distribution converges very fast** — by 100 files it's already 56:44 (vs Part 1's 8 files → 25:75, and other tests 5 files → 40:60). Few large files = hash noise; many files = near-even.
2. **The residual ~55:45 is NOT hash randomness — it is STRUCTURAL.** The original converted constituent stays on **aggr1**, then a symmetric `+4/+4` expand yields **5 constituents on aggr1 vs 4 on aggr2** → balance **floor = 5/9 : 4/9 = 55.6 : 44.4**. At the per-constituent level (500 files) each of the 9 constituents holds ~52–58 GB — **near-perfectly even**.

**To reach a true 50:50**, make both aggregates hold an equal number of constituents (e.g. add one more constituent to aggr2 for 5:5), rather than trying to fix it by writing more files.

---

## Key takeaways

- **Gen2 upgrade path is ordered:** raise throughput to 1536 *within* 1HA first, *then* expand to 2HA (storage must double). You can't go 1HA/384 → 2HA directly.
- **DataSync per-file hashing needs many files to look balanced.** 8 large files skewed 25:75; 100+ small files converge to the structural floor.
- **DataSync verify on large files is expensive** (67.6 min vs 40.5 min transfer). Choose `VerifyMode` deliberately.
- **In-place FlexVol→FlexGroup conversion is fast (< 1 min) and free of data copy** — *on a clean volume*. It is **hard-blocked** if the volume was ever a DataSync FSx-ONTAP source (hidden SM-C copy-to-cloud relationship the customer can't release).
- **Steady-state throughput after 2HA/1536 ≈ 3.5× the 1HA/384 baseline** for this workload.
- **Residual FlexGroup skew is structural** (unequal constituent count per aggregate), not hash randomness — fix it by equalizing constituents, not by adding files.

## Files

| File | Description |
|---|---|
| `README.md` | This document |
| `01_datasync_source_upgrade_fio_timeline.png` | Source FSx (DataSync side) in-place upgrade — fio full-run BW/IOPS by phase |
| `02_conversion_full_chain_fio.png` | Clean-control full chain fio timeseries (baseline → upgrade → HA expand → convert+expand → multi-file write) |
| `03_multifile_balance_convergence.png` | Distribution convergence at 100/300/500 files vs structural floor |
| `flexvol_to_flexgroup_conversion_prereqs.md` | NetApp official prerequisite checklist for in-place conversion |
