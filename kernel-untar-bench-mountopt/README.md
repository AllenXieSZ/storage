# Kernel Untar Storage Benchmark — Phase 1: Mount-Option Tuning

Does tuning **mount options** speed up small-file, metadata-heavy workloads on network storage?
Single-threaded `tar xf linux-7.2.5.tar.xz` (**101,062 files**) on one EC2 client, comparing each
storage backend's **default** mount vs **optimized** mount options.

Companion to [`kernel-untar-bench-4way`](../kernel-untar-bench-4way/) (which established the default baselines)
and [`kernel-untar-bench-phase3-npm`](../kernel-untar-bench-phase3-npm/) (same question for `npm install`).

## Test setup

| Item | Value |
|---|---|
| Region | us-east-2 (Ohio) |
| Client | 1× c7i.4xlarge (16 vCPU, 32 GiB), Amazon Linux 2023 |
| Workload | `tar xf linux-7.2.5.tar.xz`, single-threaded |
| Files produced | **101,062** per run (verified with `find | wc -l`) |
| Method | `sync && echo 3 > drop_caches` before each run; fresh target dir; `/usr/bin/time -v`; wall clock; opts verified with `nfsstat -m` |
| Default baselines | from `kernel-untar-bench-4way`: EBS 10.4 s / EFS 2392 s / S3 Files 2408 s / JuiceFS 3617 s (**not re-run here**) |

![Phase 1: default vs optimized mount](phase1_mountopt_compare.png)

## Results — `tar xf` (default baseline vs optimized mount)

| Storage | Mount variant | tar time | Files | vs default baseline |
|---|---|---|---|---|
| **EBS gp3** | optimized (`noatime`, local xfs) | **10.1 s** | 101,062 | −2.7% (noise) |
| **EFS** | optimized (`tls,noatime,nodiratime,rsize/wsize=1M`) | **2667.1 s** | 101,062 | **+11.5% (slower)** |
| **EFS** | optimized + `actimeo=600` | **2575.8 s** | 101,062 | +7.7% (slower) |
| **EFS** | `nconnect=16` raw NFS, **no tls** | **PATHOLOGICAL — aborted** | 3 in 38 min | session wedged |
| **S3 Files** | optimized (`tls,iam,noatime,nodiratime,rsize/wsize=1M`) NFSv4.2 | **2354.8 s** | 101,062 | −2.2% (noise) |
| **S3 Files** | optimized + `actimeo=600` | **2391.4 s** | 101,062 | −0.7% (noise) |
| **JuiceFS** | optimized (`--writeback --attr-cache 300 --entry-cache 300 --dir-entry-cache 300 --cache-size 10240 --buffer-size 1024`) | **135.9 s** | 101,062 | **−96.2% (26.6× faster)** |

## Which mount parameter actually helps?

**① NFS-class stores (EFS / S3 Files): mount tuning does essentially nothing (±3%, sometimes slightly worse).**
The wall is the **per-file synchronous metadata round-trip**: every `mkdir` / `open(O_CREAT)` / `write` / `rename`
in the tar stream waits for a server ACK before the next one. The tuned knobs target other things:
- `noatime` / `nodiratime` — skip access-time *reads*; a create workload barely reads atimes → no effect.
- `rsize` / `wsize = 1 MiB` — help big *sequential reads/writes*; kernel source files are tiny (~5 KB avg) → no effect.
- `actimeo=600` — caches *attributes* of files you `stat` repeatedly; tar creates each file once → no effect (and the extra cache bookkeeping can even cost a hair, hence the small +% on EFS).
- **Async is already the NFS default** — the client already pipelines/writes-behind where the protocol allows; there is no "turn on async" knob left to flip.

**② `nconnect` gives no usable benefit on EFS — two separate reasons:**
- Under the **supported `-o tls` path** (efs-utils → single stunnel socket on 127.0.0.1), `nconnect` is **silently ignored**: there is only one TCP socket, so extra connections cannot exist.
- Mounting **raw NFSv4.1 directly to the mount-target IP without tls** *does* open 16 real TCP sockets (`nconnect=16` visible in `nfsstat -m`, 16 ESTAB conns confirmed) — **but the session wedges**: RPC tasks stall in `CREATE_SESSION` / `CLOSE` (`q:xprt_pending`), and the `tar` managed only **~3 files in 38 minutes** before being aborted. EFS mount targets expect the efs-proxy path; a hand-rolled raw multi-connection NFSv4.1 session is not viable here.
- Either way: **more connections do not parallelize a serial dependency chain of creates** — the bottleneck is latency-per-create, not connection count/bandwidth.

**③ JuiceFS `--writeback` is the only optimization that actually moves the needle (−96%, 3617 s → 136 s).**
It takes S3 latency off the critical path: data writes land in a local on-disk buffer and return immediately, flushing
to S3 in the background; entry/attr/dir caches + a large local cache absorb the metadata churn. Result runs at
near-local-disk speed and even beats both NFS stores by ~17×. Trade-off: relaxed durability (unflushed writes lost on
a client crash before background upload) — fine for a rebuildable kernel tree, not for primary data.

## Bottom line

For `tar xf`-style metadata-heavy small-file workloads, **generic NFS mount options buy you nothing on EFS or S3 Files** —
the wall is per-create synchronous round-trip latency, which those knobs don't touch, and `nconnect` is either ignored
(tls) or pathological (raw). Only a filesystem that can **defer/batch writes off the critical path** (JuiceFS `--writeback`)
gives a real speedup. Nothing comes close to local EBS (10 s), which serializes all of this against local NVMe with no
network round-trip at all — ~230× faster than the best network result.

## Files

- `phase1_mountopt_compare.png` — default vs optimized bar chart (log scale)
- `phase1_results.csv` — raw per-run results (wall sec, file count, rc, verified mount options)
- `README_zh.md` — Chinese version
