# Kernel Untar Storage Benchmark — 5-Way AWS NFS Comparison

Single-threaded `tar xf` of the Linux kernel source (metadata-intensive: ~85,000 small files, 1.8 GB total) across **five AWS storage backends**, including FSx for NetApp ONTAP and FSx for OpenZFS.

## Test setup

| Item | Value |
|---|---|
| Region | us-east-2 (Ohio) |
| Client | MySQL-Master (i-0dffb881b2a90daa2, c6i.xlarge, 2 vCPU / 8 GiB, us-east-2c) |
| Workload | `tar xf /tmp/linux-6.19.tar.xz` — single-threaded extraction |
| Files produced | ~85,000 per run |
| Total data | ~1.8 GB |
| Method | `sync && echo 3 > /proc/sys/vm/drop_caches` before each run; wall-clock time via `/usr/bin/time` |
| Date | 2026-04-27 |

### Storage backends

| Storage | Type | Mount protocol | Mount options |
|---|---|---|---|
| **Local EBS gp3** | Block (local) | xfs | Default (reference only) |
| **FSx for NetApp ONTAP** | NFS file server | NFS v4.1 | rsize/wsize=64K ⚠️ **not optimized** |
| **FSx for OpenZFS** | NFS file server | NFS v3 | nconnect=16, rsize/wsize=1M ✅ optimized per User Guide |
| **S3 Files** | NFS gateway to S3 | NFS v4.2 | Default s3files mount helper |
| **EFS** | Managed NFS | NFS v4.1 | rsize/wsize=1M, TLS |

**Important note on ONTAP mount options:** ONTAP was tested with default rsize/wsize=64K (not tuned to 1M). Despite this disadvantage, it still outperformed the fully-optimized OpenZFS — suggesting ONTAP's metadata handling is inherently faster for this workload. A re-test with optimized mount options would likely widen the gap further.

## Results

| Storage | Extract time | Relative to ONTAP | Mount options |
|---|---|---|---|
| Local EBS gp3 | **17.3 s** | 0.02× (reference) | — |
| **FSx for NetApp ONTAP** | **14 m 13.6 s** (853.6 s) | **1.00×** (baseline) | NFS v4.1, rsize/wsize=64K ⚠️ |
| **FSx for OpenZFS** | **15 m 0.8 s** (900.8 s) | 1.06× | NFS v3, nconnect=16, rsize/wsize=1M ✅ |
| **S3 Files** | **32 m 41.2 s** (1961.2 s) | 2.30× | NFS v4.2 |
| **EFS** | **36 m 7.2 s** (2167.2 s) | 2.54× | NFS v4.1, rsize/wsize=1M, TLS |

![5-Way AWS NFS Storage Comparison](results.png)

### Repeatability

OpenZFS was tested twice: 15 m 0.8 s and 15 m 3.5 s (< 0.3% variance), confirming reproducibility.

## Key findings

### 1. Bottleneck is 100% NFS metadata round-trip, not bandwidth

All five NFS backends show `user+sys` CPU time of only ~35 seconds — virtually identical to the local EBS extraction. The remaining minutes of wall-clock time are spent waiting for NFS metadata round-trips: every `mkdir`, `open(O_CREAT)`, `write`, and `close` for each of ~85,000 files requires a synchronous server acknowledgment before the next operation begins.

### 2. ONTAP leads despite un-optimized mount options

FSx ONTAP, mounted with default rsize/wsize=64K (not tuned), was still **~50 seconds faster** than FSx OpenZFS mounted with full User Guide optimizations (NFS v3, nconnect=16, rsize/wsize=1M). This points to ONTAP's WAFL filesystem and metadata caching being inherently efficient at handling high-frequency small-file creates.

### 3. S3 Files and EFS are ~2× slower than ONTAP/OpenZFS

Both S3 Files and EFS took roughly double the time of the FSx services. For metadata-intensive workloads (many small files), the per-operation latency of these services is significantly higher.

### 4. nconnect=16 doesn't help single-threaded tar

OpenZFS was mounted with `nconnect=16` (16 parallel TCP connections), but since `tar` is single-threaded and metadata operations are serialized, only one connection is active at a time. `nconnect` benefits multi-threaded concurrent I/O, not serial metadata-heavy workloads.

### 5. Local EBS is ~50× faster — and that's the point

The 17.3-second EBS result vs ~14+ minute NFS results (a ~50× gap) illustrates the fundamental cost of network metadata round-trips. For metadata-intensive workloads like package installs, source tree extractions, or build systems with many small files, consider:

- **Extract/build locally on EBS**, then sync results to shared storage
- **Use a caching layer** (e.g., FSx for Lustre PCC, JuiceFS client cache) to absorb metadata locally
- **Restructure the workload** to use fewer, larger files (tar archives, container images)

## Tier summary

| Tier | Backends | Relative speed | Use case fit |
|---|---|---|---|
| **Tier 1** | EBS gp3 (local) | 50× faster | Build/extract locally, sync later |
| **Tier 2** | FSx ONTAP, FSx OpenZFS | 1.0–1.06× | Best shared NFS for mixed workloads |
| **Tier 3** | S3 Files, EFS | 2.3–2.5× | General purpose shared storage; avoid metadata-heavy patterns |

## Cost context (at time of test)

| Storage | Approx. monthly cost | Notes |
|---|---|---|
| EBS gp3 | ~$80/TB | Local, not shared |
| FSx ONTAP | ~$120–200/TB | Shared, multi-protocol, tiering to S3 |
| FSx OpenZFS | ~$113/month (1 TiB, SA2, 320 MBps) | Shared, snapshots |
| S3 Files | ~$23/TB (S3 storage) + gateway | New service, S3-backed |
| EFS | ~$150–300/TB (Elastic) | Fully managed, serverless |

## Caveats

1. **ONTAP was not mount-optimized** — rsize/wsize=64K vs OpenZFS's 1M. A fair re-test with 1M would likely make ONTAP even faster.
2. **Three backends (EFS/S3 Files/ONTAP) ran in parallel** on the same 2-vCPU client, introducing potential minor CPU contention. However, since CPU `user+sys` was only ~35s vs 14+ min wall time, the bottleneck was clearly network, not CPU.
3. **Single-client, single-threaded only** — does not test concurrent multi-client scaling.
4. **Kernel version:** Linux 6.19 (~85K files). Newer kernels may have slightly different file counts.

## Related benchmarks in this repo

- [`kernel-untar-bench-4way`](../kernel-untar-bench-4way/) — EFS / S3 Files / JuiceFS / EBS (4-way, different kernel version, different client)
- [`kernel-untar-bench-5client-concurrent`](../kernel-untar-bench-5client-concurrent/) — 5-client concurrent test (EFS / S3 Files / JuiceFS)
- [`kernel-untar-bench-mountopt`](../kernel-untar-bench-mountopt/) — Mount option tuning impact
- [`kernel-untar-bench-phase3-npm`](../kernel-untar-bench-phase3-npm/) — npm install benchmark
