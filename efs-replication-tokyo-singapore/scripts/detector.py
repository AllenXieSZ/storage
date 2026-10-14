#!/usr/bin/env python3
"""Watch replicated EFS (read-only dest). Records first time each file is visible with size==1MiB.
usage: detector.py /efs_dst /tmp/det   (writes seen.csv, partial.csv, hb.csv, scans.csv in that dir)
Layout rate<R>/<sec>/h<h>of<H>/f_k. Leaf dirs are 'done' once all expected files are complete -> never rescanned.
"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
root, out = sys.argv[1], sys.argv[2]
INTERVAL = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
ONLY = sys.argv[4] if len(sys.argv) > 4 else None  # e.g. rate1000: only watch this tier
FULL = 1 << 20
os.makedirs(out, exist_ok=True)
seen_f = open(f"{out}/seen.csv", "a", buffering=1 << 16)
part_f = open(f"{out}/partial.csv", "a", buffering=1)
hb_f = open(f"{out}/hb.csv", "a", buffering=1)
scan_f = open(f"{out}/scans.csv", "a", buffering=1)
complete = {}   # secdir -> set(names complete)
done_dirs = set()
partial_logged = set()
pool = ThreadPoolExecutor(64)

def st(p):
    try: return os.stat(p).st_size
    except FileNotFoundError: return None

while True:
    t_start = time.time(); nstat = 0; nnew = 0
    try:
        rates = [x for x in os.listdir(root) if x.startswith("rate") and (ONLY is None or x == ONLY)]
    except FileNotFoundError:
        rates = []
    for r in rates:
        R = int(r[4:])
        rp = os.path.join(root, r)
        leaves = []
        for sd in os.listdir(rp):
            if f"{r}/{sd}" in done_dirs: continue
            try: hs = os.listdir(os.path.join(rp, sd))
            except FileNotFoundError: continue
            for h in hs:
                key = f"{r}/{sd}/{h}"
                if key in done_dirs: continue
                hi, H = map(int, h[1:].split("of"))
                leaves.append((key, len(range(hi, R, H))))
            # a sec dir is done when it has all host subdirs and all are done
            if hs and all(f"{r}/{sd}/{h}" in done_dirs for h in hs) and len(hs) == int(hs[0].split("of")[1]):
                done_dirs.add(f"{r}/{sd}")
        def scan_leaf(item):
            key, exp = item
            dp = os.path.join(root, key)
            c = complete.get(key, set())
            res = []
            try:
                with os.scandir(dp) as it:   # READDIRPLUS attrs -> cheap size check
                    for e in it:
                        if e.name in c: continue
                        try: sz = e.stat().st_size
                        except FileNotFoundError: sz = None
                        res.append((e.name, sz, time.time()))
            except FileNotFoundError: return key, exp, []
            return key, exp, res
        for key, exp, res in pool.map(scan_leaf, leaves):
            c = complete.setdefault(key, set())
            nstat += len(res)
            for n, s, ts in res:
                if s == FULL:
                    c.add(n); nnew += 1
                    seen_f.write(f"{key}/{n},{ts:.6f}\n")
                elif s is not None and (key, n, s) not in partial_logged:
                    partial_logged.add((key, n, s))
                    part_f.write(f"{key}/{n},{s},{ts:.6f}\n")
            if len(c) >= exp:
                done_dirs.add(key); del complete[key]
    seen_f.flush()
    try:
        hb = [int(x) for x in os.listdir(os.path.join(root, "hb"))]
        hb_f.write(f"{time.time():.6f},{max(hb) if hb else ''},{len(hb)}\n")
    except FileNotFoundError:
        hb_f.write(f"{time.time():.6f},,0\n")
    t_end = time.time()
    scan_f.write(f"{t_start:.6f},{t_end:.6f},{nstat},{nnew}\n")
    time.sleep(max(0, INTERVAL - (t_end - t_start)))
