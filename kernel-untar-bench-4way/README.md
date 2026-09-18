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
- **EFS (Elastic)** — Elastic Throughput mode, NFSv4.1 (Phase 1 baseline)
- **EFS (Bursting)** — Bursting Throughput mode, NFSv4.1
- **EBS gp3** — local root volume, provisioned 8000 IOPS / 500 MB/s (reference only, too fast to be a fair baseline)
- **S3 Files** — new service, NFSv4.2, linked to a versioned S3 bucket (prefix `s3files/`)
- **JuiceFS** — Redis metadata (on the 2nd EC2) + S3 data backend, FUSE mount

## Results — Phase 1: `tar xf` extraction (baseline = EFS)

EFS is the baseline; EBS is an observational reference only (too fast to be a fair baseline).

| Storage | Config | Extract time | Files | Relative to EFS |
|---|---|---|---|---|
| EFS (Elastic) | Elastic Throughput, NFSv4.1 | **39 m 52 s** (2392 s) | 101,062 | 1× (baseline) |
| EFS (Bursting) | Bursting Throughput, NFSv4.1 | **41 m 37 s** (2497 s) | 101,062 | ~1.04× |
| S3 Files | NFSv4.2, versioned bucket | **40 m 8 s** (2408 s) | 101,062 | ~1.01× |
| JuiceFS | Redis meta + S3 data, FUSE | **1 h 0 m 17 s** (3617 s) | 101,062 | ~1.51× |
| EBS gp3 (reference only, not baseline) | local, 8000 IOPS / 500 MB/s | **10.4 s** | 101,062 | ~0.004× |

## Results — Phase 2: `git clone` (baseline = S3 Files)

Serial single-threaded `git clone` of **NixOS/nixpkgs** (92,712 files, shallow) from a local reference repo into each backend. Page caches dropped between clones. S3 Files is the baseline; EBS is an observational reference only (too fast to be a fair baseline).

| Storage | git clone time | Files | Relative to S3 Files |
|---|---|---|---|
| S3 Files | **17 m 16 s** (1035.7 s) | 92,712 | 1× (baseline) |
| EFS (Elastic) | **16 m 49 s** (1009.2 s) | 92,712 | ~0.97× |
| EFS (Bursting) | **16 m 32 s** (992.0 s) | 92,725 | ~0.96× |
| JuiceFS | **33 m 2 s** (1981.8 s) | 92,712 | ~1.91× |
| EBS gp3 (reference only, not baseline) | **5.0 s** | 92,712 | ~0.005× |

## Takeaway

Local EBS extracts/clones the ~100k-file tree in seconds. Every network-backed store is 2+ orders of magnitude slower because single-threaded work serializes one small-file create per metadata round-trip — the bottleneck is per-file latency, not bandwidth.

- **Phase 1 (`tar xf`, baseline = EFS):** EFS and S3 Files land close (~40 min, S3 Files ~1.01× EFS); JuiceFS slowest (~60 min, ~1.51× EFS), since each file also drives an object write through the Redis→S3 path. EBS is orders of magnitude faster (10 s) but shown only as a reference.
- **Phase 2 (`git clone`):** EFS (Elastic & Bursting) and S3 Files are nearly identical (~16–17 min); JuiceFS is ~1.9× the S3 Files baseline. Clone is faster than tar because git streams the pack and writes the working tree with fewer fsync stalls, but the small-file metadata cost still dominates on all network stores.
- **EFS Bursting vs Elastic:** performance is essentially the same as Elastic for this small, short workload (untar ~1.04× Elastic, clone ~0.96×) — a fresh/empty EFS starts with a full burst-credit balance, so throughput is not throttled here. But Bursting is **cheaper**: $150/mo (storage only, no separate throughput fee) vs Elastic's $195/mo. The trade-off: Bursting's baseline is only 50 KB/s per GB stored, so at sustained high-throughput scale (once burst credits deplete) it can be throttled hard, whereas Elastic scales throughput on demand. For small or bursty workloads Bursting wins on cost; for sustained heavy I/O, Elastic (or Provisioned) is safer.

## Results — Phase 4: `npm install` (default vs optimized mount)

Single-run `npm install` of a heavyweight front-end dep tree (**66,513 files**), comparing **default vs optimized mount** options per network store (`noatime,rsize/wsize=1M,actimeo=600`; JuiceFS uses `--writeback`+cache). npm cache primed on local EBS then `--prefer-offline`, so only filesystem/metadata cost is measured. Page caches dropped between runs. EBS is an observational reference only.

| Storage | Mount (default/optimized) | npm install time | Files | Optimized vs default |
|---|---|---|---|---|
| EFS (Elastic) | default (`tls`) | **3 m 43 s** (223.1s) | 66,513 | — (baseline) |
| EFS (Elastic) | optimized (`noatime,rsize/wsize=1M,actimeo=600`) | **3 m 49 s** (228.8s) | 66,513 | **−2.6% (no gain)** |
| S3 Files | default (`tls,iam`) | **3 m 59 s** (239.4s) | 66,513 | — (baseline) |
| S3 Files | optimized (same opts) | **3 m 59 s** (238.8s) | 66,513 | **+0.3% (no gain)** |
| JuiceFS | default (redis + S3, FUSE) | **7 m 12 s** (432.1s) | 66,513 | — (baseline) |
| JuiceFS | optimized (`--writeback`+cache) | **1 m 43 s** (103.1s) | 66,513 | **76.1% faster** |
| EBS gp3 (reference only) | local, noatime | **13.1 s** | 66,513 | ~0.03× |

**Phase 4 — two key findings:**
- **① NFS-class (EFS/S3 Files): optimized mount options do essentially nothing (±3%).** npm install is write/create-dominated; each `mkdir`/`open(O_CREAT)`/`rename` is a synchronous metadata round-trip. `noatime`/`rsize`/`actimeo` tune read/attr-cache and never touch it; `nconnect` is silently ignored under `-o tls`.
- **② JuiceFS `--writeback` is the only effective optimization (−76%, 7m12s → 1m43s).** Async writes (local buffer first, background S3 upload) take S3 latency off the critical path, even beating both NFS stores. Trade-off: relaxed durability, rebuildable node_modules only.

> Full Phase 4 report (with comparison chart) at [`../kernel-untar-bench-phase3-npm/`](../kernel-untar-bench-phase3-npm/).

## Phase 3: Monthly cost estimate — 500 GB stored/written per month (us-east-2)

All rates are official AWS us-east-2 rates pulled from the AWS Pricing API (Sept 2026):

| Component | Rate (us-east-2) |
|---|---|
| EFS Standard storage | $0.30 / GB-mo |
| EFS Elastic Throughput — write | $0.06 / GB |
| EFS Elastic Throughput — read | $0.03 / GB |
| S3 Standard storage (first 50 TB) | $0.023 / GB-mo |
| S3 Files high-performance storage layer | $0.30 / GB-mo |
| S3 Files metered write / read | $0.06 / $0.03 per GB |
| S3 PUT/COPY/POST/LIST (Tier1) | $0.005 / 1,000 |
| S3 GET & other (Tier2) | $0.0004 / 1,000 |
| c7i.4xlarge Linux on-demand | $0.714 / hr |
| EBS gp3 storage | $0.08 / GB-mo |

**Assumptions:** 500 GB stored and written once/month; 500 GB read once/month (1× active-set read); S3 Files active set = full 500 GB on the high-perf layer; JuiceFS uses its default 4 MiB block → 500 GB ≈ **128,000 objects** (128k PUT to write + 128k GET to read); JuiceFS Redis runs on a dedicated c7i.4xlarge 24×7 (720 hrs) with a 30 GB gp3 root.

| Storage | Storage cost | Throughput / request cost | Compute (Redis) | **TOTAL $/mo** |
|---|---|---|---|---|
| EFS (Elastic) | $150.00 | $45.00 (30 write + 15 read) | — | **$195.00** |
| EFS (Bursting) | $150.00 | — (included in storage) | — | **$150.00** |
| S3 Files | $161.50 ($11.50 S3 + $150 layer) | $45.69 (30 write + 15 read + $0.69 req) | — | **$207.19** |
| JuiceFS | $11.50 (S3 Standard) | $0.69 (128k PUT + 128k GET) | $516.48 ($514.08 EC2 + $2.40 EBS) | **$528.67** |

**Note — cheapest at 500 GB & the JuiceFS TCO flip:** On raw *storage+IO*, JuiceFS looks cheapest by far (~$12/mo — it only pays S3 Standard) and EFS ($195) beats S3 Files ($207) slightly. But the **dedicated Redis EC2 is JuiceFS's hidden TCO driver**: at 24×7 a single c7i.4xlarge adds ~$514/mo, pushing JuiceFS to **$529/mo — the most expensive of the three** and ~2.7× the fully-managed EFS. Managed EFS and S3 Files have no compute floor, so at modest scale (500 GB) they win decisively. JuiceFS's economics only turn favorable at much larger capacities, where the fixed Redis/compute cost amortizes across many TB and its cheap S3 Standard storage ($0.023/GB-mo vs $0.30) dominates — but you would also right-size (or share) the metadata node rather than dedicate a c7i.4xlarge. **At 500 GB, EFS is the cheapest sensible choice; JuiceFS is cheapest only if you ignore its required metadata server.**
