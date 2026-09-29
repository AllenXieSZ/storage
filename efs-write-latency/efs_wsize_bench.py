#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, time, statistics, json

MNT = sys.argv[1]
APP_IO = int(sys.argv[2])      # app pwrite size (fixed)
WSIZE = int(sys.argv[3])       # mount wsize label
FILE_SIZE = int(sys.argv[4])
ROUNDS = int(sys.argv[5])

def run_one():
    path = os.path.join(MNT, f"wtest_{WSIZE}.bin")
    buf = os.urandom(APP_IO)
    n = FILE_SIZE // APP_IO
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    lat = []
    t0 = time.perf_counter()
    off = 0
    for _ in range(n):
        s = time.perf_counter()
        w = os.pwrite(fd, buf, off)
        e = time.perf_counter()
        lat.append((e - s) * 1000.0)
        off += w
    tf0 = time.perf_counter(); os.fsync(fd); tf1 = time.perf_counter()
    t1 = time.perf_counter()
    os.close(fd); os.unlink(path)
    ls = sorted(lat)
    pct = lambda p: ls[min(len(ls)-1, int(len(ls)*p))]
    return {
        "wsize": WSIZE, "app_io": APP_IO, "n_writes": n,
        "total_ms": (t1-t0)*1000.0, "fsync_ms": (tf1-tf0)*1000.0,
        "avg_ms": statistics.mean(lat), "p50_ms": pct(0.50),
        "p99_ms": pct(0.99), "max_ms": max(lat),
        "throughput_MBps": (FILE_SIZE/1024/1024)/((t1-t0)),
    }

rounds = [run_one() for _ in range(ROUNDS)]
best = min(rounds, key=lambda x: x["total_ms"])
mean_total = statistics.mean(x["total_ms"] for x in rounds)
print(f"  best_total={best['total_ms']:.1f}ms  mean_total={mean_total:.1f}ms  "
      f"avg_pwrite={best['avg_ms']:.3f}ms  fsync={best['fsync_ms']:.1f}ms  "
      f"tput={best['throughput_MBps']:.1f}MB/s")
print("  JSON " + json.dumps({"wsize": WSIZE, "best": best, "mean_total_ms": mean_total}))
