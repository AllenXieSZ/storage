#!/usr/bin/env python3
"""
EFS Lifecycle Tier Audit v3 — Multi-threaded
=============================================
v2 基础上加多线程并发遍历：对顶层目录的每个子目录分配线程池并发 os.walk+lstat。
NFS lstat 瓶颈是 RTT（~4ms），多线程可重叠往返延迟。

用法同 v2，新增 --workers 参数控制线程数（默认 16）。
"""

import argparse, csv, io, os, sys, time, threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

BATCH_SIZE_DEFAULT = 50000

def parse_args():
    p = argparse.ArgumentParser(description="EFS lifecycle tier audit v3 (multi-threaded)")
    p.add_argument("--mount", required=True)
    p.add_argument("--fs-id", required=True)
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--ia-days", type=int, required=True)
    p.add_argument("--archive-days", type=int, default=0)
    p.add_argument("--output-dir", default="/tmp/efs-audit")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    p.add_argument("--workers", type=int, default=16, help="Thread pool size")
    return p.parse_args()

def get_efs_api_sizes(fs_id, region):
    try:
        import boto3
        client = boto3.client("efs", region_name=region)
        resp = client.describe_file_systems(FileSystemId=fs_id)
        sib = resp["FileSystems"][0]["SizeInBytes"]
        return {
            "Total": sib.get("Value", 0),
            "Standard": sib.get("ValueInStandard", 0),
            "IA": sib.get("ValueInIA", 0),
            "Archive": sib.get("ValueInArchive", 0),
        }
    except Exception as e:
        print(f"[WARN] EFS API failed: {e}", file=sys.stderr)
        return None

def efs_metered_size(file_size):
    metadata = 2048
    data_metered = 4096 if file_size == 0 else ((file_size + 4095) // 4096) * 4096
    return metadata, data_metered

def classify_file(age_days, ia_days, archive_days):
    if archive_days > 0 and age_days >= archive_days:
        return "archive"
    if ia_days > 0 and age_days >= ia_days:
        return "ia"
    return "standard"

def human_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PiB"

class TierCollector:
    """Thread-safe collector for file stats and CSV rows."""
    def __init__(self, output_dir, batch_size):
        self.lock = threading.Lock()
        self.stats = {
            "standard": {"count": 0, "raw_size": 0, "metered_data": 0, "metered_metadata": 0},
            "ia":       {"count": 0, "raw_size": 0, "metered_data": 0, "metered_metadata": 0},
            "archive":  {"count": 0, "raw_size": 0, "metered_data": 0, "metered_metadata": 0},
        }
        self.file_count = 0
        self.error_count = 0
        self.dir_count = 0

        # Per-tier row buffers (flush to disk under lock)
        self.batch_size = batch_size
        self.output_dir = output_dir
        self._bufs = {t: [] for t in ("standard", "ia", "archive")}
        self._fhs = {}
        header = "path,size_bytes,atime,age_days\n"
        for t in ("standard", "ia", "archive"):
            path = os.path.join(output_dir, f"{t}_files.csv")
            fh = open(path, "w", buffering=1 << 20)
            fh.write(header)
            self._fhs[t] = fh

    def add(self, tier, fpath, file_size, atime_epoch, age_days, metadata, data_metered):
        if tier in ("ia", "archive"):
            tier_data = max(data_metered, 128 * 1024)
        else:
            tier_data = data_metered

        atime_str = datetime.fromtimestamp(atime_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = f"{fpath},{file_size},{atime_str},{age_days:.1f}\n"

        with self.lock:
            s = self.stats[tier]
            s["count"] += 1
            s["raw_size"] += file_size
            s["metered_data"] += tier_data
            s["metered_metadata"] += metadata
            self.file_count += 1

            self._bufs[tier].append(row)
            if len(self._bufs[tier]) >= self.batch_size:
                self._flush_tier(tier)

    def add_error(self):
        with self.lock:
            self.error_count += 1

    def add_dirs(self, n):
        with self.lock:
            self.dir_count += n

    def _flush_tier(self, tier):
        # Caller must hold self.lock
        if self._bufs[tier]:
            self._fhs[tier].write("".join(self._bufs[tier]))
            self._bufs[tier] = []

    def close(self):
        with self.lock:
            for t in ("standard", "ia", "archive"):
                self._flush_tier(t)
                self._fhs[t].close()

    def get_file_count(self):
        with self.lock:
            return self.file_count

def scan_subtree(root, now, ia_days, archive_days, collector):
    """Walk a subtree, lstat every file, classify and collect."""
    local_dirs = 0
    for dirpath, dirnames, filenames in os.walk(root):
        local_dirs += 1
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.lstat(fpath)
            except (OSError, PermissionError):
                collector.add_error()
                continue
            if not (st.st_mode & 0o100000):  # S_IFREG
                continue
            file_size = st.st_size
            atime_epoch = st.st_atime
            metadata, data_metered = efs_metered_size(file_size)
            age_days = (now - atime_epoch) / 86400.0
            tier = classify_file(age_days, ia_days, archive_days)
            collector.add(tier, fpath, file_size, atime_epoch, age_days, metadata, data_metered)
    collector.add_dirs(local_dirs)

def main():
    args = parse_args()
    mount = args.mount
    ia_days = args.ia_days
    archive_days = args.archive_days
    workers = args.workers
    output_dir = args.output_dir

    os.makedirs(output_dir, exist_ok=True)
    now = time.time()
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    print(f"EFS Tier Audit v3 (multi-threaded, workers={workers}, batch={args.batch_size})")
    print(f"  Mount:    {mount}")
    print(f"  FS:       {args.fs_id}")
    print(f"  IA:       AFTER_{ia_days}_DAYS")
    print(f"  Archive:  {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    print(f"  Now:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(flush=True)

    collector = TierCollector(output_dir, args.batch_size)
    t0 = time.time()

    # Phase 1: Scan root directory to find top-level entries
    root_files = []
    root_dirs = []
    try:
        for entry in os.scandir(mount):
            if entry.is_dir(follow_symlinks=False):
                root_dirs.append(entry.path)
            elif entry.is_file(follow_symlinks=False):
                root_files.append(entry.path)
    except (OSError, PermissionError) as e:
        print(f"[ERROR] Cannot scan root: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Root: {len(root_dirs)} dirs, {len(root_files)} files")
    print(f"  Dispatching {len(root_dirs)} subtrees to {workers} workers...", flush=True)

    # Phase 2: Process root-level files in main thread
    collector.add_dirs(1)  # root dir itself
    for fpath in root_files:
        try:
            st = os.lstat(fpath)
        except (OSError, PermissionError):
            collector.add_error()
            continue
        if not (st.st_mode & 0o100000):
            continue
        file_size = st.st_size
        atime_epoch = st.st_atime
        metadata, data_metered = efs_metered_size(file_size)
        age_days = (now - atime_epoch) / 86400.0
        tier = classify_file(age_days, ia_days, archive_days)
        collector.add(tier, fpath, file_size, atime_epoch, age_days, metadata, data_metered)

    # Phase 3: Fan out subtrees to thread pool
    last_progress = time.time()
    completed = 0

    def progress_monitor():
        """Print progress every 10 seconds."""
        nonlocal last_progress
        while True:
            time.sleep(10)
            t_now = time.time()
            elapsed = t_now - t0
            fc = collector.get_file_count()
            rate = fc / elapsed if elapsed > 0 else 0
            s = collector.stats
            print(f"  [{elapsed:.0f}s] {fc:,} files ({rate:.0f}/s) "
                  f"Std={s['standard']['count']:,} IA={s['ia']['count']:,} "
                  f"Arc={s['archive']['count']:,} "
                  f"threads_done={completed}/{len(root_dirs)}", flush=True)

    monitor = threading.Thread(target=progress_monitor, daemon=True)
    monitor.start()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_subtree, d, now, ia_days, archive_days, collector): d
                   for d in root_dirs}
        for future in as_completed(futures):
            completed += 1
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] subtree {futures[future]}: {e}", file=sys.stderr)

    elapsed = time.time() - t0
    collector.close()

    file_count = collector.file_count
    dir_count = collector.dir_count
    error_count = collector.error_count
    stats = collector.stats

    dir_overhead = dir_count * 6 * 1024
    predicted_standard = (
        stats["standard"]["metered_data"] +
        stats["standard"]["metered_metadata"] +
        stats["ia"]["metered_metadata"] +
        stats["archive"]["metered_metadata"] +
        dir_overhead
    )
    predicted_ia = stats["ia"]["metered_data"]
    predicted_archive = stats["archive"]["metered_data"]
    predicted_total = predicted_standard + predicted_ia + predicted_archive

    api = get_efs_api_sizes(args.fs_id, args.region)
    rate_total = file_count / elapsed if elapsed > 0 else 0

    lines = []
    lines.append("=" * 70)
    lines.append("EFS Lifecycle Tier Audit v3 Summary (multi-threaded)")
    lines.append("=" * 70)
    lines.append(f"File System:    {args.fs_id}")
    lines.append(f"Mount:          {mount}")
    lines.append(f"IA Policy:      AFTER_{ia_days}_DAYS")
    lines.append(f"Archive Policy: {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    lines.append(f"Workers:        {workers}")
    lines.append(f"Scan Time:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"Duration:       {elapsed:.1f}s ({elapsed/60:.1f}min)")
    lines.append(f"Files:          {file_count:,}")
    lines.append(f"Dirs:           {dir_count:,}")
    lines.append(f"Errors:         {error_count:,}")
    lines.append(f"Scan Rate:      {rate_total:.0f} files/s")
    lines.append("")
    lines.append("-" * 70)
    lines.append("Predicted Tier Distribution (by atime)")
    lines.append("-" * 70)
    lines.append(f"{'Tier':<10} {'Files':>12} {'Raw Size':>14} {'Metered':>14}")
    for tk, label in [("standard","Standard"),("ia","IA"),("archive","Archive")]:
        s = stats[tk]
        if tk == "standard":
            metered = (s["metered_data"] + s["metered_metadata"] +
                       stats["ia"]["metered_metadata"] +
                       stats["archive"]["metered_metadata"] +
                       dir_overhead)
        else:
            metered = s["metered_data"]
        lines.append(f"{label:<10} {s['count']:>12,} {human_bytes(s['raw_size']):>14} {human_bytes(metered):>14}")
    lines.append(f"{'TOTAL':<10} {file_count:>12,} "
                 f"{human_bytes(sum(s['raw_size'] for s in stats.values())):>14} "
                 f"{human_bytes(predicted_total):>14}")

    if api:
        lines.append("")
        lines.append("-" * 70)
        lines.append("EFS API Reported")
        lines.append("-" * 70)
        for k in ("Standard","IA","Archive","Total"):
            lines.append(f"  {k:<10} {human_bytes(api[k]):>14}  ({api[k]:,} bytes)")
        lines.append("")
        lines.append("-" * 70)
        lines.append("Predicted vs API")
        lines.append("-" * 70)
        for label, pred, actual in [
            ("Standard", predicted_standard, api["Standard"]),
            ("IA",       predicted_ia,       api["IA"]),
            ("Archive",  predicted_archive,  api["Archive"]),
            ("Total",    predicted_total,    api["Total"]),
        ]:
            if actual > 0:
                diff_pct = (pred - actual) / actual * 100
            else:
                diff_pct = 0.0 if pred == 0 else float('inf')
            lines.append(f"  {label:<10} Pred: {human_bytes(pred):>14}  "
                         f"API: {human_bytes(actual):>14}  Diff: {diff_pct:+.2f}%")

    lines.append("")
    lines.append(f"CSV: {output_dir}/{{standard,ia,archive}}_files.csv")
    lines.append("=" * 70)

    summary = "\n".join(lines)
    with open(os.path.join(output_dir, "summary.txt"), "w") as f:
        f.write(summary + "\n")
    print(summary)

if __name__ == "__main__":
    main()
