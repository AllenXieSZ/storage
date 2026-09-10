#!/usr/bin/env python3
# ============================================================================
# lustre_ls_csv_parallel — 用 'lfs find <dir> -maxdepth 1'（lfs 层，直接 MDT 查询）
#   逐目录列举文件的 名字/大小/时间，多进程并发（-j）扫描 → 内存汇总 → 批量写 CSV。
# SCRIPT_VERSION: v2.0-parallel
# ============================================================================
import argparse, csv, os, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

SCRIPT_VERSION = "v2.0-parallel"

def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)

def scan_one(directory):
    """单目录 lfs find -maxdepth 1，返回 rows。子进程执行。"""
    cmd = ["lfs", "find", directory, "-maxdepth", "1", "-type", "f",
           "-printf", "%p\t%s\t%A@\n"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    rows = []
    if p.returncode != 0:
        return rows
    for line in p.stdout.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        try:
            size = int(parts[1])
        except ValueError:
            size = 0
        try:
            mtime = int(float(parts[2]))
        except ValueError:
            mtime = 0
        rows.append((os.path.basename(parts[0]), directory, parts[0], size, mtime))
    return rows

def human_size(n):
    for u in ("B","K","M","G","T"):
        if n < 1024: return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}P"

def main():
    ap = argparse.ArgumentParser(description="Parallel Lustre lfs-find -> CSV")
    ap.add_argument("-d","--directory", required=True)
    ap.add_argument("-o","--output", default=None)
    ap.add_argument("-j","--jobs", type=int, default=32, help="parallel worker processes (default 32)")
    args = ap.parse_args()

    root = args.directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = args.output or f"lustre_ls_par_{ts}.csv"

    log(f"Starting parallel MDT-ls ({SCRIPT_VERSION}) for: {root}")
    rc, ver = subprocess.getstatusoutput("lfs --version 2>/dev/null | awk '{print $2}'")
    log(f"lfs version: {ver.strip()} ; jobs={args.jobs}")

    start = time.time()
    log("Enumerating directories...")
    dirs = [d for d,_,_ in os.walk(root)]
    log(f"Found {len(dirs)} directories")

    log(f"Scanning with {args.jobs} parallel workers ('lfs find -maxdepth 1')...")
    records = []
    done = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(scan_one, d): d for d in dirs}
        for fut in as_completed(futs):
            records.extend(fut.result())
            done += 1
            if done % 2000 == 0 or done == len(dirs):
                log(f"Scanned dirs: {done}/{len(dirs)} - files: {len(records)}")

    scan_elapsed = time.time() - start
    log(f"Scan done: {len(records)} files in {scan_elapsed:.2f}s "
        f"({len(records)/scan_elapsed if scan_elapsed>0 else 0:.1f} files/sec)")

    log(f"Writing CSV: {out_csv}")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name","dir","path","size_bytes","size_human","mtime_epoch","mtime_iso"])
        for name, d, path, size, mtime in records:
            iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else ""
            w.writerow([name, d, path, size, human_size(size), mtime, iso])

    log("----------------------------------------")
    log(f"Total files: {len(records)} | Total time: {time.time()-start:.2f}s")
    log(f"CSV: {os.path.abspath(out_csv)}")
    log("----------------------------------------")

if __name__ == "__main__":
    main()
