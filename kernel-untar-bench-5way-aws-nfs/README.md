# Kernel Untar Storage Benchmark — 6-Way AWS Storage Comparison

Single-threaded `tar xf` of the Linux kernel source (metadata-intensive: ~85,000+ small files, ~1.8 GB total) across **six AWS storage backends**, covering all major file storage services plus local EBS as a reference.

## Test setup

| Item | Value |
|---|---|
| Region | us-east-2 (Ohio) |
| Client | MySQL-Master (i-0dffb881b2a90daa2, c6i.xlarge, 2 vCPU / 8 GiB, us-east-2c) |
| Workload | `tar xf /tmp/linux-6.19.tar.xz` — single-threaded extraction |
| Files produced | ~85,000–92,000 per run (same archive; count varies by `find` filter) |
| Total data | ~1.8 GB |
| Method | `sync && echo 3 > /proc/sys/vm/drop_caches` before each run; wall-clock time via `/usr/bin/time -v` |

### Storage backends

| Storage | Type | Protocol | Config | Mount options | Test date |
|---|---|---|---|---|---|
| **Local EBS gp3** | Block (local) | xfs | Default | — | 2026-04-27 |
| **FSx for Lustre** | Parallel FS | Lustre (LNET/TCP) | PERSISTENT_2, 4.8 TiB, 125 MB/s/TiB, **192,000 metadata IOPS** | `noatime,flock` | **2026-10-27** |
| **FSx for NetApp ONTAP** | NFS file server | NFS v4.1 | Single-AZ Gen1 | rsize/wsize=64K ⚠️ **not optimized** | 2026-04-27 |
| **FSx for OpenZFS** | NFS file server | NFS v3 | Single-AZ 2, 1 TiB, 320 MBps | nconnect=16, rsize/wsize=1M ✅ optimized | 2026-04-27 |
| **S3 Files** | NFS gateway to S3 | NFS v4.2 | Default | s3files mount helper | 2026-04-27 |
| **EFS** | Managed NFS | NFS v4.1 | Elastic Throughput | rsize/wsize=1M, TLS | 2026-04-27 |

**Notes on mount options:**
- ONTAP was tested with default rsize/wsize=64K (not tuned to 1M). Despite this disadvantage, it still outperformed the fully-optimized OpenZFS.
- OpenZFS was tuned per AWS User Guide (NFS v3, nconnect=16, rsize/wsize=1M).
- Lustre uses native Lustre client (lfs 2.12.8), not NFS — fundamentally different protocol with no per-file metadata round-trip overhead.

## Results

| Storage | Extract time | Relative to EBS | Relative to ONTAP | Protocol |
|---|---|---|---|---|
| **Local EBS gp3** | **17.3 s** | **1.00×** (ref) | 0.02× | Local block |
| **FSx for Lustre** | **5 m 20.9 s** (320.9 s) | 18.5× | **0.38×** | Lustre |
| **FSx for NetApp ONTAP** | **14 m 13.6 s** (853.6 s) | 49.3× | 1.00× (NFS baseline) | NFS v4.1 |
| **FSx for OpenZFS** | **15 m 0.8 s** (900.8 s) | 52.1× | 1.06× | NFS v3 |
| **S3 Files** | **32 m 41.2 s** (1961.2 s) | 113.4× | 2.30× | NFS v4.2 |
| **EFS** | **36 m 7.2 s** (2167.2 s) | 125.3× | 2.54× | NFS v4.1 |

### Repeatability

| Storage | Run 1 | Run 2 | Variance |
|---|---|---|---|
| FSx for Lustre | 5 m 28.2 s | **5 m 20.9 s** | 2.2% |
| FSx for OpenZFS | 15 m 0.8 s | 15 m 3.5 s | 0.3% |

### CPU time breakdown (Lustre vs NFS)

| Storage | User (s) | System (s) | User+Sys (s) | Wall (s) | CPU% | I/O wait ratio |
|---|---|---|---|---|---|---|
| FSx for Lustre (run2) | 16.5 | 70.7 | **87.2** | 320.9 | 27% | 73% I/O wait |
| NFS backends (typical) | ~12 | ~23 | **~35** | 850–2170 | 2–4% | 96–98% I/O wait |

Lustre's higher `sys` time (70s vs ~23s for NFS) reflects the kernel Lustre client doing more local work per file (LNET protocol handling, extent lock management, stripe allocation). But the **wall time is 2.7× shorter than the fastest NFS** because Lustre's metadata protocol is fundamentally more efficient: it batches operations and doesn't require a synchronous server round-trip for every individual file create.

## Key findings

### 1. Lustre is 2.7× faster than the best NFS, but EBS still wins by 18×

FSx for Lustre at **5 m 21 s** is dramatically faster than all NFS-based services (ONTAP 14 m, OpenZFS 15 m, S3 Files 33 m, EFS 36 m). Lustre's native protocol avoids the NFS per-file synchronous metadata round-trip that dominates NFS wall time. However, local EBS at 17.3 s is still **18× faster** — the network + filesystem metadata overhead remains significant even with Lustre.

### 2. Lustre's advantage is in the protocol, not just IOPS

The 192,000 metadata IOPS provisioned for this test is far more than needed for a single-threaded tar. The speed advantage comes from Lustre's **protocol efficiency**: the Lustre client batches metadata operations and uses intent-based locks, reducing the number of network round-trips per file compared to NFS's create→write→close sequence.

### 3. NFS bottleneck confirmed: per-file synchronous round-trip

All NFS backends (ONTAP/OpenZFS/S3 Files/EFS) show `user+sys` CPU of only ~35 seconds but wall times of 14–36 minutes. The gap is 100% NFS metadata round-trip latency: every `mkdir`, `open(O_CREAT)`, `write`, and `close` for each file waits for a server ACK.

### 4. ONTAP still leads NFS despite un-optimized mount

FSx ONTAP with default rsize/wsize=64K outperformed fully-optimized OpenZFS by ~50 seconds, confirming ONTAP's WAFL metadata handling advantage in this workload.

### 5. Clear tier structure for metadata-intensive workloads

| Tier | Storage | Time range | Best for |
|---|---|---|---|
| **Tier 1** | EBS gp3 (local) | ~17 s | Build/extract locally, sync later |
| **Tier 2** | FSx for Lustre | ~5 min | Shared parallel FS, HPC/AI/large-scale |
| **Tier 3** | FSx ONTAP / OpenZFS | ~14–15 min | Shared NFS, mixed enterprise workloads |
| **Tier 4** | S3 Files / EFS | ~33–36 min | General purpose shared; avoid metadata-heavy patterns |

## Practical recommendations

1. **Metadata-heavy workloads (package installs, source trees, many small files):**
   - Best: do it on local EBS, then sync to shared storage
   - If must be shared: FSx for Lustre is ~2.7× faster than any NFS option
   - Avoid: running `tar xf` / `npm install` / `pip install` directly on EFS or S3 Files

2. **Lustre metadata IOPS provisioning:**
   - For single-client serial workloads like this, even the minimum metadata IOPS is sufficient
   - The 192,000 IOPS provisioned here was overkill for this test — the bottleneck is per-file protocol overhead, not aggregate IOPS capacity
   - High metadata IOPS matters for **multi-client concurrent** metadata storms (hundreds of nodes doing `ls -l` or checkpoint writes simultaneously)

3. **NFS mount tuning doesn't help metadata-heavy workloads:**
   - `nconnect=16` helps multi-threaded data I/O, not single-threaded metadata
   - `actimeo`/`noatime` give negligible improvement for create-heavy workloads
   - The only NFS tuning that would help is reducing the number of files (restructure the workload)

## Cost context

| Storage | Config tested | Approx. monthly cost | Notes |
|---|---|---|---|
| EBS gp3 | Default | ~$80/TB | Local, not shared |
| FSx for Lustre | P2, 4.8 TiB, 125 MB/s/TiB, 192K MD IOPS | ~$672/mo SSD + ~$1,152/mo MD IOPS | High MD IOPS is expensive; reduce if not needed |
| FSx ONTAP | Gen1 Single-AZ | ~$120–200/TB | Shared, multi-protocol, S3 tiering |
| FSx OpenZFS | SA2, 1 TiB, 320 MBps | ~$113/mo | Shared, snapshots |
| S3 Files | Default | ~$23/TB (S3) + gateway | S3-backed, new service |
| EFS | Elastic Throughput | ~$150–300/TB | Fully managed, serverless |

## Caveats

1. **Different test dates:** NFS backends tested 2026-04-27; Lustre tested 2026-10-27. Same client, same kernel archive, same method.
2. **ONTAP was not mount-optimized** — rsize/wsize=64K vs OpenZFS's 1M. A fair re-test with 1M would likely make ONTAP even faster.
3. **Three NFS backends ran in parallel** during the 2026-04-27 test on the same 2-vCPU client. CPU contention was negligible (CPU `user+sys` ~35s vs 14+ min wall time).
4. **Lustre client version 2.12.8** (AL2 default). Newer clients (2.15+) may have improved metadata performance (e.g., batch create optimizations).
5. **Single-client, single-threaded only** — does not test multi-client concurrent scaling where Lustre's advantage would be even larger.
6. **File count discrepancy:** `find -type f` returns ~85,000 (regular files only) or ~92,000 (including symlinks). The actual tar archive content is identical across all tests.

## Reproduction commands

```bash
# Download kernel source
cd /tmp && curl -LO https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.19.tar.xz

# Mount Lustre (example — replace with your FS DNS and mount name)
mkdir -p /mnt/lustre-bench
mount -t lustre -o noatime,flock <fs-id>.fsx.<region>.amazonaws.com@tcp:/<mountname> /mnt/lustre-bench

# Run test
sync && echo 3 > /proc/sys/vm/drop_caches
mkdir -p /mnt/lustre-bench/run1 && cd /mnt/lustre-bench/run1
/usr/bin/time -v tar xf /tmp/linux-6.19.tar.xz

# Count files
find /mnt/lustre-bench/run1 -type f | wc -l

# Cleanup
rm -rf /mnt/lustre-bench/run1
umount /mnt/lustre-bench
```

## Test environment details

### Lustre FS (2026-10-27)

```
FileSystemId:    fs-0879f933a37ca5922
DeploymentType:  PERSISTENT_2
StorageCapacity: 4800 GiB (SSD)
Throughput:      125 MB/s/TiB (600 MB/s total)
MetadataConfig:  USER_PROVISIONED, 192,000 IOPS
Subnet:          us-east-2c
Lustre client:   lfs 2.12.8 (Amazon Linux 2)
Mount:           noatime,flock
Status:          Deleted after test
```

### NFS backends (2026-04-27)

```
FSx ONTAP:   NFS v4.1, rsize/wsize=64K (default, not optimized)
FSx OpenZFS: fs-03520c47456c242bd, SA2, 1024 GiB, 320 MBps, NFS v3, nconnect=16, rsize/wsize=1M
S3 Files:    NFS v4.2, s3files mount helper
EFS:         fs-027ff9a3e720a5a4e, NFS v4.1, rsize/wsize=1M, TLS
```

## Related benchmarks in this repo

- [`kernel-untar-bench-4way`](../kernel-untar-bench-4way/) — EFS / S3 Files / JuiceFS / EBS (different kernel version, different client)
- [`kernel-untar-bench-5client-concurrent`](../kernel-untar-bench-5client-concurrent/) — 5-client concurrent test (EFS / S3 Files / JuiceFS)
- [`kernel-untar-bench-mountopt`](../kernel-untar-bench-mountopt/) — Mount option tuning impact
- [`kernel-untar-bench-phase3-npm`](../kernel-untar-bench-phase3-npm/) — npm install benchmark
