#!/usr/bin/env python3
"""
EFS Lifecycle Tier Audit — Multi-threaded
==========================================
Walk EFS mount, classify files into Standard/IA/Archive by atime,
cross-validate against EFS API per-tier totals.

Parallelism: uses a thread pool to concurrently lstat files across
directories. For large flat directories (100K+ files, no subdirs),
file lists are split into chunks and processed in parallel.

Usage:
  python3 efs_tier_audit.py \
    --mount /mnt/efs --fs-id fs-xxx --region us-east-2 \
    --ia-days 30 [--archive-days 90] --workers 32
"""

import argparse, os, sys, time, threading, queue
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

BATCH_SIZE_DEFAULT = 50000

def parse_args():
    p = argparse.ArgumentParser(description="EFS lifecycle tier audit")
    p.add_argument("--mount", required=True)
    p.add_argument("--fs-id", required=True)
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--ia-days", type=int, required=True)
    p.add_argument("--archive-days", type=int, default=0)
    p.add_argument("--output-dir", default="/tmp/efs-audit")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    p.add_argument("--workers", type=int, default=32)
    return p.parse_args()

def get_efs_api_sizes(fs_id, region):
    try:
        import boto3
        client = boto3.client("efs", region_name=region)
        resp = client.describe_file_systems(FileSystemId=fs_id)
        sib = resp["FileSystems"][0]["SizeInBytes"]
        return {k: sib.get(k, 0) for k in ("Value", "ValueInStandard", "ValueInIA", "ValueInArchive")}
    except Exception as e:
        print(f"[WARN] EFS API failed: {e}", file=sys.stderr)
        return None

def efs_metered_size(file_size):
    metadata = 2048
    data = 4096 if file_size == 0 else ((file_size + 4095) // 4096) * 4096
    return metadata, data

def classify(age_days, ia_days, archive_days):
    if archive_days > 0 and age_days >= archive_days:
        return "archive"
    if ia_days > 0 and age_days >= ia_days:
        return "ia"
    return "standard"

def human_bytes(n):
    for u in ("B","KiB","MiB","GiB","TiB"):
        if abs(n) < 1024: return f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} PiB"


class Collector:
    """Thread-safe stats + CSV buffer."""
    def __init__(self, output_dir, batch_size):
        self.lock = threading.Lock()
        self.stats = {t: {"count":0,"raw":0,"mdata":0,"mmeta":0} for t in ("standard","ia","archive")}
        self.file_count = 0
        self.error_count = 0
        self.dir_count = 0
        self._batch = batch_size
        self._bufs = {t: [] for t in ("standard","ia","archive")}
        self._fhs = {}
        for t in ("standard","ia","archive"):
            fh = open(os.path.join(output_dir, f"{t}_files.csv"), "w", buffering=1<<20)
            fh.write("path,size_bytes,atime,age_days\n")
            self._fhs[t] = fh

    def add(self, tier, path, size, atime_ep, age, meta, data):
        td = max(data, 131072) if tier != "standard" else data
        at = datetime.fromtimestamp(atime_ep, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = f"{path},{size},{at},{age:.1f}\n"
        with self.lock:
            s = self.stats[tier]
            s["count"] += 1; s["raw"] += size; s["mdata"] += td; s["mmeta"] += meta
            self.file_count += 1
            self._bufs[tier].append(row)
            if len(self._bufs[tier]) >= self._batch:
                self._flush(tier)

    def add_error(self):
        with self.lock: self.error_count += 1

    def add_dirs(self, n):
        with self.lock: self.dir_count += n

    def _flush(self, t):
        if self._bufs[t]:
            self._fhs[t].write("".join(self._bufs[t]))
            self._bufs[t] = []

    def close(self):
        with self.lock:
            for t in self._bufs: self._flush(t)
            for f in self._fhs.values(): f.close()

    def get_fc(self):
        with self.lock: return self.file_count


def lstat_batch(file_paths, now, ia_days, archive_days, collector):
    """lstat a batch of file paths and classify."""
    for fpath in file_paths:
        try:
            st = os.lstat(fpath)
        except (OSError, PermissionError):
            collector.add_error()
            continue
        if not (st.st_mode & 0o100000): continue
        sz = st.st_size
        at = st.st_atime
        meta, data = efs_metered_size(sz)
        age = (now - at) / 86400.0
        tier = classify(age, ia_days, archive_days)
        collector.add(tier, fpath, sz, at, age, meta, data)


def walk_and_dispatch(mount, now, ia_days, archive_days, collector, pool, workers):
    """
    Walk directory tree. For each directory:
    - If it has subdirs, just collect files in this dir and submit as one batch.
    - Large flat dirs (many files, no subdirs): split file list into chunks
      and submit each chunk as a separate task for parallel lstat.
    """
    CHUNK = 5000  # files per chunk for parallel lstat
    futures = []

    for dirpath, dirnames, filenames in os.walk(mount):
        collector.add_dirs(1)
        if not filenames:
            continue
        fpaths = [os.path.join(dirpath, f) for f in filenames]
        # Split into chunks for parallelism
        for i in range(0, len(fpaths), CHUNK):
            chunk = fpaths[i:i+CHUNK]
            fut = pool.submit(lstat_batch, chunk, now, ia_days, archive_days, collector)
            futures.append(fut)

    return futures


def main():
    args = parse_args()
    mount, ia_days, archive_days = args.mount, args.ia_days, args.archive_days
    workers, output_dir = args.workers, args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    now = time.time()
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    print(f"EFS Tier Audit (workers={workers}, chunk=5000)")
    print(f"  Mount:    {mount}")
    print(f"  FS:       {args.fs_id}")
    print(f"  IA:       AFTER_{ia_days}_DAYS")
    print(f"  Archive:  {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    print(f"  Now:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(flush=True)

    collector = Collector(output_dir, args.batch_size)
    t0 = time.time()

    # Progress monitor
    stop_monitor = threading.Event()
    def monitor():
        while not stop_monitor.wait(10):
            el = time.time() - t0
            fc = collector.get_fc()
            r = fc/el if el > 0 else 0
            s = collector.stats
            print(f"  [{el:.0f}s] {fc:,} files ({r:.0f}/s) "
                  f"Std={s['standard']['count']:,} IA={s['ia']['count']:,} "
                  f"Arc={s['archive']['count']:,}", flush=True)
    mon = threading.Thread(target=monitor, daemon=True)
    mon.start()

    # Main walk + parallel lstat
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = walk_and_dispatch(mount, now, ia_days, archive_days, collector, pool, workers)
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: print(f"[ERROR] {e}", file=sys.stderr)

    stop_monitor.set()
    elapsed = time.time() - t0
    collector.close()

    fc = collector.file_count
    dc = collector.dir_count
    ec = collector.error_count
    stats = collector.stats
    do = dc * 6 * 1024  # dir overhead

    ps = stats["standard"]["mdata"] + stats["standard"]["mmeta"] + \
         stats["ia"]["mmeta"] + stats["archive"]["mmeta"] + do
    pi = stats["ia"]["mdata"]
    pa = stats["archive"]["mdata"]
    pt = ps + pi + pa

    api_raw = get_efs_api_sizes(args.fs_id, args.region)
    api = None
    if api_raw:
        api = {"Standard": api_raw["ValueInStandard"], "IA": api_raw["ValueInIA"],
               "Archive": api_raw["ValueInArchive"], "Total": api_raw["Value"]}

    rate = fc / elapsed if elapsed > 0 else 0
    L = []
    L.append("=" * 70)
    L.append("EFS Lifecycle Tier Audit Summary")
    L.append("=" * 70)
    L.append(f"File System:    {args.fs_id}")
    L.append(f"Mount:          {mount}")
    L.append(f"IA Policy:      AFTER_{ia_days}_DAYS")
    L.append(f"Archive Policy: {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    L.append(f"Workers:        {workers}")
    L.append(f"Scan Time:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    L.append(f"Duration:       {elapsed:.1f}s ({elapsed/60:.1f}min)")
    L.append(f"Files:          {fc:,}")
    L.append(f"Dirs:           {dc:,}")
    L.append(f"Errors:         {ec:,}")
    L.append(f"Scan Rate:      {rate:.0f} files/s")
    L.append("")
    L.append("-" * 70)
    L.append("Predicted Tier Distribution (by atime)")
    L.append("-" * 70)
    L.append(f"{'Tier':<10} {'Files':>12} {'Raw Size':>14} {'Metered':>14}")
    for tk, lb in [("standard","Standard"),("ia","IA"),("archive","Archive")]:
        s = stats[tk]
        m = ps if tk == "standard" else s["mdata"]
        L.append(f"{lb:<10} {s['count']:>12,} {human_bytes(s['raw']):>14} {human_bytes(m):>14}")
    L.append(f"{'TOTAL':<10} {fc:>12,} "
             f"{human_bytes(sum(s['raw'] for s in stats.values())):>14} "
             f"{human_bytes(pt):>14}")
    if api:
        L.append("")
        L.append("-" * 70)
        L.append("EFS API Reported")
        L.append("-" * 70)
        for k in ("Standard","IA","Archive","Total"):
            L.append(f"  {k:<10} {human_bytes(api[k]):>14}  ({api[k]:,} bytes)")
        L.append("")
        L.append("-" * 70)
        L.append("Predicted vs API")
        L.append("-" * 70)
        for lb, p, a in [("Standard",ps,api["Standard"]),("IA",pi,api["IA"]),
                          ("Archive",pa,api["Archive"]),("Total",pt,api["Total"])]:
            d = ((p-a)/a*100) if a > 0 else (0.0 if p == 0 else float('inf'))
            L.append(f"  {lb:<10} Pred: {human_bytes(p):>14}  API: {human_bytes(a):>14}  Diff: {d:+.2f}%")
    L.append("")
    L.append(f"CSV: {output_dir}/{{standard,ia,archive}}_files.csv")
    L.append("=" * 70)

    summary = "\n".join(L)
    with open(os.path.join(output_dir, "summary.txt"), "w") as f:
        f.write(summary + "\n")
    print(summary)

if __name__ == "__main__":
    main()
