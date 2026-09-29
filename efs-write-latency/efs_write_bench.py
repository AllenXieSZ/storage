#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EFS Elastic Throughput write-latency benchmark.

For each pwrite() I/O size (512K, 1M, 2M, 4M, 8M):
  - write a 200 MiB file to EFS using os.pwrite() in fixed-size chunks
  - measure total wall-clock time to write the whole file
  - measure per-pwrite latency (avg / p50 / p99 / max)
  - fsync at the end and measure fsync time separately
Each io size is run on a FRESH file. O_DIRECT is NOT used (EFS/NFS path);
we fsync to force data to the server so timings reflect real durable writes.
Multiple rounds per io size; report the best (min total-time) round to reduce noise,
plus mean across rounds.
"""
import os, sys, time, statistics, json

FILE_SIZE = 200 * 1024 * 1024          # 200 MiB
IO_SIZES = [512*1024, 1*1024*1024, 2*1024*1024, 4*1024*1024, 8*1024*1024]
ROUNDS = 3
TARGET_DIR = sys.argv[1] if len(sys.argv) > 1 else "/mnt/efs"

def human(n):
    for u in ["B","K","M","G"]:
        if n < 1024: return f"{n}{u}"
        n //= 1024
    return f"{n}T"

def run_one(io_size):
    path = os.path.join(TARGET_DIR, f"efs_wtest_{io_size}.bin")
    buf = os.urandom(io_size)
    n_writes = FILE_SIZE // io_size
    # open with O_CREAT|O_WRONLY|O_TRUNC; no O_DIRECT (unsupported reliably on NFS)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    lat = []
    t0 = time.perf_counter()
    off = 0
    for _ in range(n_writes):
        s = time.perf_counter()
        written = os.pwrite(fd, buf, off)
        e = time.perf_counter()
        if written != io_size:
            raise RuntimeError(f"short write {written}!={io_size}")
        lat.append((e - s) * 1000.0)   # ms
        off += io_size
    # durability: flush to EFS server
    tf0 = time.perf_counter()
    os.fsync(fd)
    tf1 = time.perf_counter()
    t1 = time.perf_counter()
    os.close(fd)
    os.unlink(path)

    total_ms = (t1 - t0) * 1000.0
    fsync_ms = (tf1 - tf0) * 1000.0
    lat_sorted = sorted(lat)
    def pct(p):
        return lat_sorted[min(len(lat_sorted)-1, int(len(lat_sorted)*p))]
    return {
        "io_size": io_size,
        "n_writes": n_writes,
        "total_ms": total_ms,          # includes all pwrite + fsync
        "fsync_ms": fsync_ms,
        "pwrite_sum_ms": sum(lat),
        "avg_ms": statistics.mean(lat),
        "p50_ms": pct(0.50),
        "p99_ms": pct(0.99),
        "max_ms": max(lat),
        "min_ms": min(lat),
        "throughput_MBps": (FILE_SIZE/1024/1024) / (total_ms/1000.0),
    }

def main():
    results = {}
    for io in IO_SIZES:
        rounds = []
        for r in range(ROUNDS):
            res = run_one(io)
            rounds.append(res)
            print(f"[{human(io)}] round{r+1}: total={res['total_ms']:.1f}ms "
                  f"avg_pwrite={res['avg_ms']:.3f}ms fsync={res['fsync_ms']:.1f}ms "
                  f"tput={res['throughput_MBps']:.1f}MB/s", flush=True)
        best = min(rounds, key=lambda x: x["total_ms"])
        mean_total = statistics.mean(x["total_ms"] for x in rounds)
        mean_avg = statistics.mean(x["avg_ms"] for x in rounds)
        results[io] = {"best": best, "rounds": rounds,
                       "mean_total_ms": mean_total, "mean_avg_ms": mean_avg}
    print("\n===== JSON =====")
    print(json.dumps({str(k): v for k, v in results.items()}, indent=2))

if __name__ == "__main__":
    main()
