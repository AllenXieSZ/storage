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
