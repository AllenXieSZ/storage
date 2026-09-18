# Phase 2 — git clone Benchmark (Mount-Option Tuning)

**Date:** 2026-09-18  **Region:** us-east-2 (Ohio)  **Repo cloned:** NixOS/nixpkgs (92815 files)

Cloned from a **local EBS source copy** (`git clone --no-hardlinks /data/nixpkgs-src <target>`) so
network download does not skew results — only the target filesystem's write/metadata path is measured.
Before each run: `sync && echo 3 > /proc/sys/vm/drop_caches`, `rm -rf` target, verify mount opts via `nfsstat -m`.
Measured with `/usr/bin/time -v`. Compared against Phase-1 **default-mount** baseline (defaults not re-run here).

## Mount options used (optimized)

| Storage   | Optimized mount options |
|-----------|-------------------------|
| EBS       | local gp3 (8000 IOPS / 500 MB/s), noatime reference |
| EFS       | `tls,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600` |
| S3 Files  | `tls,iam,accesspoint=…,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600` |
| JuiceFS   | `--writeback --attr-cache 300 --entry-cache 300 --dir-entry-cache 300 --cache-size 10240 --buffer-size 1024` (redis meta + S3) |

(`nconnect` is ignored under `-o tls` / stunnel single socket for EFS & S3 Files — not used.)

## Results

| Storage   | Optimized mount            | git clone time | files | Improvement vs default baseline |
|-----------|----------------------------|---------------:|------:|--------------------------------:|
| EBS       | noatime (local gp3)        |        5.11 s  | 92815 |  -2.2 %  (baseline 5.0 s)  |
| EFS       | noatime,rsize/wsize=1M,actimeo=600 |  1019.68 s  | 92815 |  -1.1 %  (baseline 1009 s) |
| S3 Files  | noatime,rsize/wsize=1M,actimeo=600 |  1021.92 s  | 92815 |  +1.4 %  (baseline 1036 s) |
| JuiceFS   | writeback + cache          |      423.76 s  | 92815 | **+78.6 %** (baseline 1982 s) |

## Verdict

**Mount-option tuning does NOT help `git clone` for NFS-backed filesystems (EFS, S3 Files).**
`git clone` into these stores is dominated by **per-file synchronous metadata round-trips** (create,
write, close, rename of ~92k small objects). Larger `rsize/wsize` only help large sequential I/O — the
working set here is tiny files — and `noatime`/`actimeo` reduce *read* revalidation, which a fresh clone
(pure writes) barely touches. Net effect for EFS/S3 Files is within noise (±1–2 %).

**JuiceFS is the exception: `--writeback` cuts clone time ~4× (1982 s → 424 s, +78.6 %).**
In writeback mode JuiceFS acknowledges writes to the local cache first and uploads to S3 asynchronously,
so git's many synchronous small writes stop blocking on S3 latency. This is a genuine, large win — but it
trades durability (data lives only in local cache until flushed) for speed, so it is only appropriate for
regenerable/scratch data.

**EBS remains ~100–200× faster** than any network store for this workload (local NVMe, no network
round-trips), and mount `noatime` makes no meaningful difference there.

**Bottom line:** for small-file-heavy workloads like `git clone`, buffer-size mount tuning is not the lever
for NFS filesystems — architecture is. Only client-side write-back caching (JuiceFS `--writeback`) moves the
needle, and only by relaxing durability.
