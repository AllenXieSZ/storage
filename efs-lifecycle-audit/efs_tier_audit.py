#!/usr/bin/env python3
"""
EFS Lifecycle Tier Audit
========================
遍历 EFS 挂载点所有文件，根据 atime 和生命周期策略推断每个文件的存储层
（Standard / IA / Archive），与 EFS API 报告的各层总量交叉对比。

输出：
  - standard_files.csv  (推断为 Standard 层的文件清单)
  - ia_files.csv        (推断为 IA 层的文件清单)
  - archive_files.csv   (推断为 Archive 层的文件清单)
  - summary.txt         (汇总 + 对比 API 数据)

用法:
  python3 efs_tier_audit.py \
    --mount /mnt/efs-lifecycle-test \
    --fs-id fs-0e77227a1ecaac809 \
    --region us-east-2 \
    --ia-days 1 \
    [--archive-days 90] \
    [--output-dir /tmp/efs-audit]

依赖: boto3 (可选，用于拉 API 对比数据；没有则跳过对比)
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

def parse_args():
    p = argparse.ArgumentParser(description="EFS lifecycle tier audit by atime")
    p.add_argument("--mount", required=True, help="EFS mount point path")
    p.add_argument("--fs-id", required=True, help="EFS file system ID")
    p.add_argument("--region", default="us-east-2", help="AWS region")
    p.add_argument("--ia-days", type=int, required=True,
                   help="TransitionToIA days (e.g. 1, 7, 30)")
    p.add_argument("--archive-days", type=int, default=0,
                   help="TransitionToArchive days (0 = no archive policy)")
    p.add_argument("--output-dir", default="/tmp/efs-audit",
                   help="Output directory for CSV and summary")
    return p.parse_args()

def get_efs_api_sizes(fs_id, region):
    """Fetch ValueInStandard/ValueInIA/ValueInArchive from EFS API."""
    try:
        import boto3
        client = boto3.client("efs", region_name=region)
        resp = client.describe_file_systems(FileSystemId=fs_id)
        fs = resp["FileSystems"][0]
        sib = fs["SizeInBytes"]
        return {
            "Total":    sib.get("Value", 0),
            "Standard": sib.get("ValueInStandard", 0),
            "IA":       sib.get("ValueInIA", 0),
            "Archive":  sib.get("ValueInArchive", 0),
        }
    except ImportError:
        print("[WARN] boto3 not available, skipping API comparison", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Failed to query EFS API: {e}", file=sys.stderr)
        return None

def efs_metered_size(file_size):
    """
    Approximate EFS metered size for a regular file.
    EFS meters: 2 KiB metadata + data rounded up to 4 KiB.
    For IA/Archive, files < 128 KiB are billed as 128 KiB (data portion).
    We return (standard_metered, ia_metered) to allow comparison.
    """
    metadata = 2 * 1024  # 2 KiB inode metadata (always in Standard)
    if file_size == 0:
        data_metered = 4 * 1024  # empty file still 4 KiB
    else:
        data_metered = ((file_size + 4095) // 4096) * 4096  # round up to 4 KiB
    return metadata, data_metered

def classify_file(atime_epoch, now_epoch, ia_days, archive_days):
    """
    Classify a file based on its atime and lifecycle policy.
    Returns: "Standard", "IA", or "Archive"
    """
    age_days = (now_epoch - atime_epoch) / 86400.0

    if archive_days > 0 and age_days >= archive_days:
        return "Archive"
    if ia_days > 0 and age_days >= ia_days:
        return "IA"
    return "Standard"

def human_bytes(n):
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
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

    os.makedirs(output_dir, exist_ok=True)

    now = time.time()
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    print(f"EFS Tier Audit")
    print(f"  Mount:        {mount}")
    print(f"  FS ID:        {args.fs_id}")
    print(f"  IA policy:    AFTER_{ia_days}_DAY{'S' if ia_days>1 else ''}")
    if archive_days:
        print(f"  Archive policy: AFTER_{archive_days}_DAYS")
    else:
        print(f"  Archive policy: None")
    print(f"  Now (UTC):    {now_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Output:       {output_dir}")
    print()

    # Open CSV writers
    csv_files = {}
    csv_writers = {}
    for tier in ["standard", "ia", "archive"]:
        path = os.path.join(output_dir, f"{tier}_files.csv")
        f = open(path, "w", newline="", buffering=1)
        w = csv.writer(f)
        w.writerow(["path", "size_bytes", "atime", "age_days"])
        csv_files[tier] = f
        csv_writers[tier] = w

    # Stats accumulators
    # For comparison with API: Standard counts metadata + data for Standard files,
    # plus metadata (2K) for IA/Archive files (metadata always in Standard).
    # IA/Archive counts only the data portion (with 128K minimum).
    stats = defaultdict(lambda: {"count": 0, "raw_size": 0, "metered_data": 0, "metered_metadata": 0})

    file_count = 0
    error_count = 0
    t0 = time.time()
    last_progress = t0

    for dirpath, dirnames, filenames in os.walk(mount):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                st = os.lstat(fpath)  # lstat to not follow symlinks
            except (OSError, PermissionError) as e:
                error_count += 1
                continue

            # Skip non-regular files (symlinks, sockets, etc.)
            if not (st.st_mode & 0o100000):  # S_IFREG
                continue

            file_size = st.st_size
            atime_epoch = st.st_atime
            metadata, data_metered = efs_metered_size(file_size)

            tier = classify_file(atime_epoch, now, ia_days, archive_days)

            # For IA/Archive, data portion has 128 KiB minimum billing
            if tier in ("IA", "Archive"):
                ia_data = max(data_metered, 128 * 1024)
            else:
                ia_data = data_metered

            tier_key = tier.lower()
            stats[tier_key]["count"] += 1
            stats[tier_key]["raw_size"] += file_size
            stats[tier_key]["metered_data"] += ia_data if tier != "Standard" else data_metered
            stats[tier_key]["metered_metadata"] += metadata

            atime_str = datetime.fromtimestamp(atime_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            age_d = (now - atime_epoch) / 86400.0
            csv_writers[tier_key].writerow([fpath, file_size, atime_str, f"{age_d:.1f}"])

            file_count += 1
            if time.time() - last_progress > 10:
                elapsed = time.time() - t0
                rate = file_count / elapsed if elapsed > 0 else 0
                print(f"  ... scanned {file_count:,} files ({rate:.0f}/s) ...", flush=True)
                last_progress = time.time()

    elapsed = time.time() - t0

    # Close CSV files
    for f in csv_files.values():
        f.close()

    # Build comparison
    # EFS API ValueInStandard = Standard data + ALL metadata (Standard + IA + Archive)
    # EFS API ValueInIA = IA data only (with 128K min rounding)
    # EFS API ValueInArchive = Archive data only (with 128K min rounding)
    predicted_standard = (
        stats["standard"]["metered_data"] +
        stats["standard"]["metered_metadata"] +
        stats["ia"]["metered_metadata"] +
        stats["archive"]["metered_metadata"]
    )
    predicted_ia = stats["ia"]["metered_data"]
    predicted_archive = stats["archive"]["metered_data"]
    predicted_total = predicted_standard + predicted_ia + predicted_archive

    # Also account for directory inodes (approximate)
    # Each dir = 2 KiB metadata + at least 4 KiB data, always in Standard
    dir_count = 0
    for dirpath, dirnames, _ in os.walk(mount):
        dir_count += 1 + len(dirnames)
    dir_overhead = dir_count * 6 * 1024  # 6 KiB per dir (2 meta + 4 data)
    predicted_standard += dir_overhead
    predicted_total += dir_overhead

    # Get API data
    api = get_efs_api_sizes(args.fs_id, args.region)

    # Write summary
    summary_path = os.path.join(output_dir, "summary.txt")
    lines = []
    lines.append("=" * 70)
    lines.append("EFS Lifecycle Tier Audit Summary")
    lines.append("=" * 70)
    lines.append(f"File System:    {args.fs_id}")
    lines.append(f"Mount:          {mount}")
    lines.append(f"IA Policy:      AFTER_{ia_days}_DAY{'S' if ia_days>1 else ''}")
    lines.append(f"Archive Policy: {'AFTER_'+str(archive_days)+'_DAYS' if archive_days else 'None'}")
    lines.append(f"Scan Time:      {now_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"Scan Duration:  {elapsed:.1f}s")
    lines.append(f"Files Scanned:  {file_count:,}")
    lines.append(f"Dirs Found:     {dir_count:,}")
    lines.append(f"Errors:         {error_count:,}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("Predicted Tier Distribution (by atime)")
    lines.append("-" * 70)
    lines.append(f"{'Tier':<10} {'Files':>10} {'Raw Size':>14} {'Metered Size':>14}")
    for tier_key, label in [("standard", "Standard"), ("ia", "IA"), ("archive", "Archive")]:
        s = stats[tier_key]
        if tier_key == "standard":
            metered = (s["metered_data"] + s["metered_metadata"] +
                       stats["ia"]["metered_metadata"] +
                       stats["archive"]["metered_metadata"] +
                       dir_overhead)
        else:
            metered = s["metered_data"]
        lines.append(f"{label:<10} {s['count']:>10,} {human_bytes(s['raw_size']):>14} {human_bytes(metered):>14}")
    lines.append(f"{'TOTAL':<10} {file_count:>10,} {human_bytes(sum(s['raw_size'] for s in stats.values())):>14} {human_bytes(predicted_total):>14}")

    if api:
        lines.append("")
        lines.append("-" * 70)
        lines.append("EFS API Reported Sizes")
        lines.append("-" * 70)
        lines.append(f"  Standard:  {human_bytes(api['Standard']):>14}  ({api['Standard']:,} bytes)")
        lines.append(f"  IA:        {human_bytes(api['IA']):>14}  ({api['IA']:,} bytes)")
        lines.append(f"  Archive:   {human_bytes(api['Archive']):>14}  ({api['Archive']:,} bytes)")
        lines.append(f"  Total:     {human_bytes(api['Total']):>14}  ({api['Total']:,} bytes)")

        lines.append("")
        lines.append("-" * 70)
        lines.append("Comparison: Predicted vs API")
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
                diff_pct = 0 if pred == 0 else float('inf')
            lines.append(f"  {label:<10} Predicted: {human_bytes(pred):>14}  API: {human_bytes(actual):>14}  Diff: {diff_pct:+.1f}%")

    lines.append("")
    lines.append("=" * 70)
    lines.append("CSV Files:")
    lines.append(f"  {os.path.join(output_dir, 'standard_files.csv')}")
    lines.append(f"  {os.path.join(output_dir, 'ia_files.csv')}")
    lines.append(f"  {os.path.join(output_dir, 'archive_files.csv')}")
    lines.append("=" * 70)

    summary_text = "\n".join(lines)
    with open(summary_path, "w") as f:
        f.write(summary_text + "\n")

    print(summary_text)

if __name__ == "__main__":
    main()
