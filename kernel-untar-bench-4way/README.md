# Kernel Untar Storage Benchmark — 4-Way (EFS vs S3 Files vs JuiceFS vs EBS)

Single-threaded `tar xf` extraction of the Linux kernel source across four storage backends on one EC2 client.

## Test setup

| Item | Value |
|---|---|
| Region | us-east-2 (Ohio) |
| Client | 1× c7i.4xlarge (16 vCPU, 32 GiB), Amazon Linux 2023 |
| Redis node (JuiceFS meta) | 1× c7i.4xlarge |
| Workload | `tar xf linux-7.2.5.tar.xz` (latest stable kernel), single-threaded |
| Extracted files | 101,062 per backend |
| Method | drop page caches (`echo 3 > drop_caches`) before each run, wall-clock time |

Backends:
- **EBS gp3** — local root volume, provisioned 8000 IOPS / 500 MB/s (baseline)
- **EFS** — Elastic Throughput mode, NFSv4.1
- **S3 Files** — new service, NFSv4.2, linked to a versioned S3 bucket (prefix `s3files/`)
- **JuiceFS** — Redis metadata (on the 2nd EC2) + S3 data backend, FUSE mount

## Results — Phase 1: `tar xf` extraction

| Storage | Config | Extract time | Files | Relative to EBS |
|---|---|---|---|---|
| EBS gp3 | local, 8000 IOPS / 500 MB/s | **10.4 s** | 101,062 | 1× (baseline) |
| EFS | Elastic Throughput, NFSv4.1 | **39 m 52 s** (2392 s) | 101,062 | ~231× |
| S3 Files | NFSv4.2, versioned bucket | **40 m 8 s** (2408 s) | 101,062 | ~232× |
| JuiceFS | Redis meta + S3 data, FUSE | **1 h 0 m 17 s** (3617 s) | 101,062 | ~349× |

## Results — Phase 2: `git clone` (baseline = S3 Files)

Serial single-threaded `git clone` of **NixOS/nixpkgs** (92,712 files, shallow) from a local reference repo into each backend. Page caches dropped between clones. S3 Files is the baseline; EBS is an observational reference only (too fast to be a fair baseline).

| Storage | git clone time | Files | Relative to S3 Files |
|---|---|---|---|
| S3 Files | **17 m 16 s** (1035.7 s) | 92,712 | 1× (baseline) |
| EFS (Elastic) | **16 m 49 s** (1009.2 s) | 92,712 | ~0.97× |
| JuiceFS | **33 m 2 s** (1981.8 s) | 92,712 | ~1.91× |
| EBS gp3 (reference only, not baseline) | **5.0 s** | 92,712 | ~0.005× |

## Takeaway

Local EBS extracts/clones the ~100k-file tree in seconds. Every network-backed store is 2+ orders of magnitude slower because single-threaded work serializes one small-file create per metadata round-trip — the bottleneck is per-file latency, not bandwidth.

- **Phase 1 (`tar xf`):** EFS and S3 Files land close (~40 min); JuiceFS slowest (~60 min), since each file also drives an object write through the Redis→S3 path.
- **Phase 2 (`git clone`):** EFS and S3 Files are nearly identical (~17 min, EFS marginally faster); JuiceFS is ~1.9× the S3 Files baseline. Clone is faster than tar because git streams the pack and writes the working tree with fewer fsync stalls, but the small-file metadata cost still dominates on all network stores.
