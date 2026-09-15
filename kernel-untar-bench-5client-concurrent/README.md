# Kernel Untar / git clone — 5-Client CONCURRENT Storage Benchmark (EFS vs S3 Files vs JuiceFS)

Five EC2 clients hit the **same shared filesystem at the same moment**, each writing into its own
`clientN/` subdirectory. This measures how each shared network storage scales under 5-way concurrency
(aggregate throughput + metadata contention) — not five independent single-client runs.

## Test setup

| Item | Value |
|---|---|
| Region | us-east-2 (Ohio), single AZ (us-east-2a) |
| Clients | 5× c7i.4xlarge (16 vCPU, 32 GiB), Amazon Linux 2023 |
| Redis node (JuiceFS meta) | 1× c7i.4xlarge (shared by all 5 clients) |
| Phase 1 workload | `tar xf linux-7.2.5.tar.xz` into `clientN/` (all 5 clients simultaneously) |
| Phase 2 workload | `git clone` local NixOS/nixpkgs ref into `clientN/nixpkgs` (all 5 simultaneously) |
| Method | drop page caches before each run; coordinated start; per-client wall-clock time |

Each storage is **one shared filesystem** mounted by all 5 clients:
- **EFS (Bursting)** — Bursting Throughput, NFSv4.1, fresh (full burst credits)
- **EFS (Elastic)** — Elastic Throughput, NFSv4.1
- **S3 Files** — NFS, linked to a versioned S3 bucket (prefix `s3files/`)
- **JuiceFS** — ONE shared Redis metadata + ONE shared S3 bucket, FUSE mount on all 5 clients

Per-client counts: Phase 1 = **94,758 files/client** (tar); Phase 2 = **54,447 files/client** (clone).
"Slowest" = the last of the 5 clients to finish = the true concurrent completion time.

## Results — Phase 1: `tar xf` (5 clients concurrent)

| Storage | fastest client | mean | **slowest (concurrent done)** | vs EFS Bursting | files/client |
|---|---|---|---|---|---|
| EFS (Bursting) | 2235.3 s | 2281.2 s | **2314.6 s** (38 m 35 s) | **1.00×** (baseline) | 94,758 |
| EFS (Elastic) | 2401.7 s | 2422.2 s | **2438.8 s** (40 m 39 s) | 1.05× | 94,758 |
| S3 Files | 2431.8 s | 2443.0 s | **2457.8 s** (40 m 58 s) | 1.06× | 94,758 |
| JuiceFS | 3740.0 s | 3797.0 s | **3859.9 s** (1 h 4 m 20 s) | 1.67× | 94,758 |

## Results — Phase 2: `git clone` (5 clients concurrent)

| Storage | fastest client | mean | **slowest (concurrent done)** | vs EFS Bursting | files/client |
|---|---|---|---|---|---|
| EFS (Bursting) | 903.3 s | 922.6 s | **938.1 s** (15 m 38 s) | **1.00×** (baseline) | 54,447 |
| EFS (Elastic) | 998.2 s | 1028.3 s | **1047.6 s** (17 m 28 s) | 1.12× | 54,447 |
| S3 Files | 1047.4 s | 1053.2 s | **1061.5 s** (17 m 42 s) | 1.13× | 54,447 |
| JuiceFS | 1954.8 s | 2002.9 s | **2028.4 s** (33 m 48 s) | 2.16× | 54,447 |

## Concurrency scaling vs single-client baseline

Single-client reference times come from the earlier `kernel-untar-bench-4way` test (one client, same
workload family). The key question: does 5-way concurrency slow each client down?

**Phase 1 (`tar xf`)** — per-client slowest vs single-client baseline:

| Storage | 1-client | 5-client slowest | slowdown |
|---|---|---|---|
| EFS (Bursting) | 2497 s | 2314.6 s | ~0.93× (no slowdown) |
| EFS (Elastic) | 2392 s | 2438.8 s | ~1.02× (flat) |
| S3 Files | 2408 s | 2457.8 s | ~1.02× (flat) |
| JuiceFS | 3617 s | 3859.9 s | ~1.07× (mild) |

**Phase 2 (`git clone`)** — per-client slowest vs single-client baseline:

| Storage | 1-client | 5-client slowest | slowdown |
|---|---|---|---|
| EFS (Bursting) | 992 s | 938.1 s | ~0.95× (no slowdown) |
| EFS (Elastic) | 1009 s | 1047.6 s | ~1.04× (flat) |
| S3 Files | 1036 s | 1061.5 s | ~1.02× (flat) |
| JuiceFS | 1982 s | 2028.4 s | ~1.02× (flat) |

## Takeaway

**All four shared storages scaled essentially linearly under 5 concurrent clients** — each client finished
in about the same wall time as a single client running alone, i.e. **5× the aggregate work with almost no
per-client penalty**. The workload is per-file-latency bound (one small-file create per metadata
round-trip), and each client keeps its own independent stream of in-flight operations, so five clients
just drive five parallel pipelines against the shared backend.

- **EFS Bursting did NOT throttle.** A fresh EFS starts with a full burst-credit balance; even with 5
  clients writing ~1.5 GB each (~7.5 GB total per phase) the credits were not depleted, so Bursting stayed
  as fast as Elastic (actually slightly faster here). Bursting only risks throttling under *sustained*
  high-throughput load once credits run out.
- **EFS Elastic & S3 Files** were within ~2% of their single-client times — clean aggregate scaling, no
  contention wall hit at 5 clients.
- **JuiceFS** was the slowest in absolute terms (~1.7× the EFS/S3 Files completion time in both phases),
  but critically its **shared Redis metadata did NOT become a contention bottleneck at 5 clients** — the
  per-client slowdown vs single-client was only ~1.02–1.07×. Each file still costs a Redis round-trip plus
  an S3 object write, which is why JuiceFS is slower per-file, but Redis handled 5 concurrent clients'
  metadata load comfortably.

**Ranking by concurrent completion time (both phases): EFS Bursting < EFS Elastic ≈ S3 Files < JuiceFS.**
At 5 clients on a fresh filesystem, EFS Bursting is both the fastest and the cheapest (no separate
throughput fee); JuiceFS trails on raw speed but scales cleanly and its cost story depends on the
dedicated Redis node (see the 4-way report's cost section).

## Cost estimate (monthly cost, us-east-2)

Monthly cost for the 4 storages at **1 TB / 10 TB / 50 TB**, broken down into
Storage / Read-Write traffic / Redis metadata / Total (same format as the single-client 4-way report; 1 TB = 1024 GB).

**Unit prices (us-east-2 official list price):**
- EFS Standard storage: $0.30/GB-month (Bursting and Elastic share the same storage price)
- EFS Elastic throughput: write $0.06/GB + read $0.03/GB
- S3 Standard storage: $0.023/GB-month; S3 Files high-performance storage tier: $0.30/GB-month
- S3 Files metered: write $0.06 / read $0.03 per GB
- S3 PUT $0.005/1,000; GET $0.0004/1,000
- c7i.4xlarge on-demand $0.714/hr × 720 hr + 30 GB gp3 = **$516.48/month** (JuiceFS dedicated Redis fixed cost)

**Assumptions:** monthly write = store that capacity (one full write) + read the full set once per month; JuiceFS default 4 MiB blocks → 1 TB≈262,144 objects, 10 TB≈2,621,440, 50 TB≈13,107,200 (write=PUT, read=GET); JuiceFS Redis runs 24/7 on a dedicated c7i.4xlarge.

### 1 TB

| Storage | Storage | Read-Write traffic | Redis metadata | **Total/mo** |
|---|---|---|---|---|
| EFS (Bursting) | $307.20 | — (in storage fee) | — | **$307.20** |
| EFS (Elastic) | $307.20 | $92.16 (write 61.44 + read 30.72) | — | **$399.36** |
| S3 Files | $318.55 ($11.5 S3 + $307.2 perf tier) | $93.57 (write 61.44 + read 30.72 + req 1.41) | — | **$412.12** |
| JuiceFS | $23.55 (S3 Standard) | $1.41 (PUT+GET) | $516.48 | **$541.44** |

### 10 TB

| Storage | Storage | Read-Write traffic | Redis metadata | **Total/mo** |
|---|---|---|---|---|
| EFS (Bursting) | $3,072.00 | — (in storage fee) | — | **$3,072.00** |
| EFS (Elastic) | $3,072.00 | $921.60 (write 614.4 + read 307.2) | — | **$3,993.60** |
| S3 Files | $3,307.52 ($235.5 S3 + $3,072 perf tier) | $935.76 (write 614.4 + read 307.2 + req 14.16) | — | **$4,243.28** |
| JuiceFS | $235.52 (S3 Standard) | $14.16 (PUT+GET) | $516.48 | **$766.16** |

### 50 TB

| Storage | Storage | Read-Write traffic | Redis metadata | **Total/mo** |
|---|---|---|---|---|
| EFS (Bursting) | $15,360.00 | — (in storage fee) | — | **$15,360.00** |
| EFS (Elastic) | $15,360.00 | $4,608.00 (write 3072 + read 1536) | — | **$19,968.00** |
| S3 Files | $16,537.60 ($1,177.6 S3 + $15,360 perf tier) | $4,678.78 (write 3072 + read 1536 + req 70.78) | — | **$21,216.38** |
| JuiceFS | $1,177.60 (S3 Standard) | $70.78 (PUT+GET) | $516.48 | **$1,764.86** |

**Notes:**
- EFS Bursting has no separate throughput fee (included in storage), the cheapest EFS form on pure storage; Elastic bills read/write traffic separately.
- S3 Files has cheap underlying S3 storage, but the $0.30/GB-month high-performance tier pushes its total up to par with (or above) EFS.
- **JuiceFS TCO inversion**: data lives on cheap S3 Standard ($0.023/GB-month), but the dedicated Redis node is a ~$516/month fixed cost. At small capacity (1 TB) this fixed cost dominates and JuiceFS is the most expensive; as capacity grows it amortizes, and from 10 TB up JuiceFS total is far below EFS/S3 Files. **The larger the scale, the more JuiceFS wins.**
- This table covers storage + read/write traffic + requests + Redis compute; it excludes data-transfer fees; a real metadata node can be tuned or shared to cut cost further.
- ⚠️ Unit prices may change over time; refer to the AWS official pricing page for current rates.
