#!/usr/bin/env python3
# ============================================================================
# lustre_ls_csv — 用 'lfs find <dir> -maxdepth 1' 逐目录（直接查 MDT）列举文件，
#                 把 文件名/大小/时间 先缓存在内存，最后批量写入 CSV。
# SCRIPT_VERSION: v1.0-lustre-mdt-ls
#   - 参照 lustre_warmup 脚本的参数/日志风格。
#   - 用 'lfs find <dir> -maxdepth 1 -type f' 单目录 MDT 查询（不递归），
#     再对每个 file 用 'lfs find ... --printf' 一次性取 size/mtime（走 MDT，
#     避免逐个 os.stat 触发 OST glimpse）。
# ============================================================================
import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPT_VERSION = "v1.0-lustre-mdt-ls"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def run(cmd):
    """跑命令，返回 (rc, stdout, stderr)。"""
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout, p.stderr


def lfs_available():
    rc, _, _ = run(["bash", "-lc", "command -v lfs >/dev/null 2>&1 && echo ok"])
    return rc == 0


def list_dirs(root):
    """收集 root 下所有目录（含 root），用于逐目录 -maxdepth 1 扫描。"""
    dirs = []
    for dpath, dnames, _ in os.walk(root):
        dirs.append(dpath)
    return dirs


def scan_dir_files(directory):
    """
    用 'lfs find <dir> -maxdepth 1 -type f' 直接查 MDT，拿本级文件的
    路径 + 大小 + mtime。用 --printf 一次性输出，避免逐文件 stat。
    返回 list[dict]。
    格式: 路径\t大小(字节)\tmtime(epoch)
    """
    # lfs find 的 -printf 支持 %p(path) %s(size) %A@/%T@ 之类；FSx Lustre(2.15)支持 -printf。
    # 用 %y 过滤已由 -type f 保证。分隔符用 \t。
    cmd = ["lfs", "find", directory, "-maxdepth", "1", "-type", "f",
           "-printf", "%p\t%s\t%A@\n"]
    rc, out, err = run(cmd)
    rows = []
    if rc != 0:
        # 回退：不支持 -printf 时，先列路径再 os.stat（仍是 -maxdepth 1 的 MDT 列举）
        cmd2 = ["lfs", "find", directory, "-maxdepth", "1", "-type", "f"]
        rc2, out2, err2 = run(cmd2)
        if rc2 != 0:
            log(f"WARN: lfs find failed in {directory}: {err2.strip() or err.strip()}")
            return rows
        for path in out2.splitlines():
            path = path.strip()
            if not path:
                continue
            try:
                st = os.stat(path)
                rows.append({"path": path, "name": os.path.basename(path),
                             "dir": directory, "size_bytes": st.st_size,
                             "mtime_epoch": int(st.st_mtime)})
            except OSError as e:
                log(f"WARN: stat failed {path}: {e}")
        return rows

    for line in out.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path, size_s, mtime_s = parts[0], parts[1], parts[2]
        try:
            size = int(size_s)
        except ValueError:
            size = 0
        try:
            mtime = int(float(mtime_s))
        except ValueError:
            mtime = 0
        rows.append({"path": path, "name": os.path.basename(path),
                     "dir": directory, "size_bytes": size,
                     "mtime_epoch": mtime})
    return rows


def human_size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


def main():
    ap = argparse.ArgumentParser(
        description="List Lustre files via 'lfs find -maxdepth 1' (MDT query) into CSV.")
    ap.add_argument("-d", "--directory", required=True, help="Root directory to process")
    ap.add_argument("-o", "--output", default=None, help="Output CSV path (default: lustre_ls_<ts>.csv)")
    ap.add_argument("-b", "--batch", type=int, default=10000,
                    help="Progress report every N dirs (default: 10000)")
    args = ap.parse_args()

    root = args.directory
    if not os.path.isdir(root):
        log(f"ERROR: not a directory: {root}")
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = args.output or f"lustre_ls_{ts}.csv"

    log(f"Starting Lustre MDT-ls (script {SCRIPT_VERSION}) for: {root}")
    rc, ver, _ = run(["bash", "-lc", "lfs --version 2>/dev/null | awk '{print $2}'"])
    log(f"lfs client version: {ver.strip()}")
    if not lfs_available():
        log("ERROR: 'lfs' not found in PATH. Are you on a Lustre client?")
        sys.exit(1)

    start = time.time()

    # 1) 收集所有目录
    log("Enumerating directories...")
    dirs = list_dirs(root)
    total_dirs = len(dirs)
    log(f"Found {total_dirs} directories")

    # 2) 逐目录 lfs find -maxdepth 1，结果先全部放内存
    log("Scanning each directory with 'lfs find -maxdepth 1 -type f' (MDT query)...")
    records = []  # 内存缓存
    for idx, d in enumerate(dirs, 1):
        records.extend(scan_dir_files(d))
        if idx % max(1, args.batch) == 0 or idx == total_dirs:
            log(f"Scanned dirs: {idx}/{total_dirs} - files so far: {len(records)}")

    scan_elapsed = time.time() - start
    log(f"Scan done: {len(records)} files from {total_dirs} dirs in {scan_elapsed:.2f}s "
        f"({(len(records)/scan_elapsed if scan_elapsed>0 else 0):.1f} files/sec)")

    # 3) 最后一次性批量写 CSV
    log(f"Writing CSV: {out_csv}")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "dir", "path", "size_bytes", "size_human",
                    "mtime_epoch", "mtime_iso"])
        for r in records:
            iso = datetime.fromtimestamp(r["mtime_epoch"], tz=timezone.utc).isoformat() \
                if r["mtime_epoch"] else ""
            w.writerow([r["name"], r["dir"], r["path"], r["size_bytes"],
                        human_size(r["size_bytes"]), r["mtime_epoch"], iso])

    total_elapsed = time.time() - start
    log("----------------------------------------")
    log(f"Total files written: {len(records)}")
    log(f"CSV: {os.path.abspath(out_csv)}")
    log(f"Total time: {total_elapsed:.2f}s")
    log("----------------------------------------")


if __name__ == "__main__":
    main()
