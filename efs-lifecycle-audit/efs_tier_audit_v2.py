#!/usr/bin/env python3
"""
EFS Lifecycle Tier Audit v2
===========================
遍历 EFS 挂载点所有文件，根据 atime + lifecycle 策略推断存储层，
与 EFS API 各层总量交叉对比。

v2 优化: CSV 内存缓冲(BATCH_SIZE行/次)批量写盘，避免逐行 IO 拖慢遍历。

输出:
  standard_files.csv / ia_files.csv / archive_files.csv + summary.txt

用法:
  python3 efs_tier_audit_v2.py \
    --mount /mnt/efs-poc \
    --fs-id fs-027ff9a3e720a5a4e \
    --region us-east-2 \
    --ia-days 14 \
    [--archive-days 90] \
    [--output-dir /tmp/efs-audit-poc] \
    [--batch-size 50000]
"""

import argparse, csv, io, os, sys, time
from datetime import datetime, timezone
from collections import defaultdict

BATCH_SIZE_DEFAULT = 50000  # 行数缓冲

def parse_args():
    p = argparse.ArgumentParser(description="EFS lifecycle tier audit v2 (buffered)")
    p.add_argument("--mount", required=True)
    p.add_argument("--fs-id", required=True)
    p.add_argument("--region", default="us-east-2")
    p.add_argument("--ia-days", type=int, required=True)
    p.add_argument("--archive-days", type=int, default=0)
    p.add_argument("--output-dir", default="/tmp/efs-audit")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT,
                   help="CSV buffer flush interval (rows)")
    return p.parse_args()

def get_efs_api_sizes(fs_id, region):
    try:
        import boto3
        client = boto3.client("efs", region_name=region)
        resp = client.describe_file_systems(FileSystemId=fs_id)
        sib = resp["FileSystems"][0]["SizeInBytes"]
        return {
            "Total":    sib.get("Value", 0),
            "Standard": sib.get("ValueInStandard", 0),
            "IA":       sib.get("ValueInIA", 0),
            "Archive":  sib.get("ValueInArchive", 0),
        }
    except Exception as e:
        print(f"[WARN] EFS API query failed: {e}", file=sys.stderr)
        return None

class BufferedCSV:
    """Write CSV in memory, flush to disk every batch_size rows."""
    def __init__(self, path, header, batch_size):
        self.path = path
        self.batch_size = batch_size
        self.buf = io.StringIO()
        self.writer = csv.writer(self.buf)
        self.writer.writerow(header)
        self.pending = 0
        self.total = 0
        # Open file, write header immediately
        self.fh = open(path, "w", buffering=1 << 20)  # 1MB OS buffer
        self._flush()

    def writerow(self, row):
        self.writer.writerow(row)
        self.pending += 1
        self.total += 1
        if self.pending >= self.batch_size:
            self._flush()

    def _flush(self):
        data = self.buf.getvalue()
        if data:
            self.fh.write(data)
        self.buf = io.StringIO()
        self.writer = csv.writer(self.buf)
        self.pending = 0

    def close(self):
        self._flush()
        self.fh.close()

def efs_metered_size(file_size):
    metadata = 2048  # 2 KiB
    if file_size == 0:
        data_metered = 4096
    else:
        data_metered = ((file_size + 4095) // 4096) * 4096
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

def main():
    args = parse_args()
    mount = args.mount
    ia_days = args.ia_days
    archive_days = args.archive_days
    output_dir = args.output_dir
    batch_size = args.batch_size

    os.makedirs(output_dir, exist_ok=True)
    now = time.time()
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    print(f"EFS Tier Audit v2 (buffered, batch={batch_size})")
    print(f"  Mount:    {mount}")
    print(f"  FS:       {args.fs_id}")
    print(f"  IA:       AFTER_{ia_days}_DAYS")
    print(f"  Archive:  {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    print(f"  Now:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(flush=True)

    header = ["path", "size_bytes", "atime", "age_days"]
    csvs = {
        "standard": BufferedCSV(os.path.join(output_dir, "standard_files.csv"), header, batch_size),
        "ia":       BufferedCSV(os.path.join(output_dir, "ia_files.csv"), header, batch_size),
        "archive":  BufferedCSV(os.path.join(output_dir, "archive_files.csv"), header, batch_size),
    }

    stats = defaultdict(lambda: {"count": 0, "raw_size": 0, "metered_data": 0, "metered_metadata": 0})
    file_count = 0
    error_count = 0
    t0 = time.time()
    last_progress = t0

    for dirpath, dirnames, filenames in os.walk(mount):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.lstat(fpath)
            except (OSError, PermissionError):
                error_count += 1
                continue

            if not (st.st_mode & 0o100000):  # S_IFREG
                continue

            file_size = st.st_size
            atime_epoch = st.st_atime
            metadata, data_metered = efs_metered_size(file_size)
            age_days = (now - atime_epoch) / 86400.0
            tier = classify_file(age_days, ia_days, archive_days)

            if tier in ("ia", "archive"):
                tier_data = max(data_metered, 128 * 1024)
            else:
                tier_data = data_metered

            stats[tier]["count"] += 1
            stats[tier]["raw_size"] += file_size
            stats[tier]["metered_data"] += tier_data
            stats[tier]["metered_metadata"] += metadata

            atime_str = datetime.fromtimestamp(atime_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            csvs[tier].writerow([fpath, file_size, atime_str, f"{age_days:.1f}"])

            file_count += 1
            t_now = time.time()
            if t_now - last_progress > 30:
                elapsed = t_now - t0
                rate = file_count / elapsed
                print(f"  [{elapsed:.0f}s] {file_count:,} files ({rate:.0f}/s) "
                      f"Std={stats['standard']['count']:,} IA={stats['ia']['count']:,} "
                      f"Arc={stats['archive']['count']:,}", flush=True)
                last_progress = t_now

    elapsed = time.time() - t0

    for c in csvs.values():
        c.close()

    # Dir overhead
    dir_count = 0
    for _ in os.walk(mount):
        dir_count += 1
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

    lines = []
    lines.append("=" * 70)
    lines.append("EFS Lifecycle Tier Audit v2 Summary")
    lines.append("=" * 70)
    lines.append(f"File System:    {args.fs_id}")
    lines.append(f"Mount:          {mount}")
    lines.append(f"IA Policy:      AFTER_{ia_days}_DAYS")
    lines.append(f"Archive Policy: {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    lines.append(f"Scan Time:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"Duration:       {elapsed:.1f}s ({elapsed/60:.1f}min)")
    lines.append(f"Files:          {file_count:,}")
    lines.append(f"Dirs:           {dir_count:,}")
    lines.append(f"Errors:         {error_count:,}")
    rate_total = file_count / elapsed if elapsed > 0 else 0
    lines.append(f"Scan Rate:      {rate_total:.0f} files/s")
    lines.append(f"Batch Size:     {batch_size}")
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
    lines.append(f"  standard: {csvs['standard'].total:,} rows")
    lines.append(f"  ia:       {csvs['ia'].total:,} rows")
    lines.append(f"  archive:  {csvs['archive'].total:,} rows")
    lines.append("=" * 70)

    summary = "\n".join(lines)
    with open(os.path.join(output_dir, "summary.txt"), "w") as f:
        f.write(summary + "\n")
    print(summary)

if __name__ == "__main__":
    main()
