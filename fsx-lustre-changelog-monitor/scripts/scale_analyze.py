#!/usr/bin/env python3
"""规模测试分析：负载 ops 日志 vs S3 中的 changelog .jsonl.gz
用法: python3 scale_analyze.py <ops_csv_dir> <changelog_dir(aws s3 sync 下来的)>
"""
import csv, glob, gzip, json, os, sys, collections, statistics

ops_dir, cl_dir = sys.argv[1], sys.argv[2]

# ---- 负载端 ----
ops = []
for f in sorted(glob.glob(f"{ops_dir}/*.csv")):
    ops += list(csv.DictReader(open(f)))
t0 = min(float(o["start"]) for o in ops); t1 = max(float(o["end"]) for o in ops)
cnt = collections.Counter(o["type"] for o in ops)
fail = sum(1 for o in ops if o["ok"] != "1")
print(f"== 负载: {len(ops)} ops, 失败 {fail}, 时长 {t1-t0:.0f}s, {len(ops)/(t1-t0):.1f} ops/s")
def pct(v, p): v = sorted(v); return v[min(len(v)-1, int(len(v)*p/100))]
for t in ["write", "read", "overwrite", "trunc_rewrite", "rename", "delete"]:
    lat = [float(o["latency_ms"]) for o in ops if o["type"] == t]
    print(f"  {t:14s} n={len(lat):6d}  P50={pct(lat,50):6.2f}ms  P99={pct(lat,99):7.2f}ms  max={max(lat):8.2f}ms")
per_client = collections.Counter(o["client"] for o in ops)
print("  per client:", dict(per_client))

# ---- changelog ----
recs, files = [], []
for f in sorted(glob.glob(f"{cl_dir}/**/*.jsonl.gz", recursive=True)):
    files.append(os.path.getsize(f))
    for l in gzip.open(f, "rt"):
        recs.append(json.loads(l))
seqs = sorted(r["seq"] for r in recs)
dup = len(seqs) - len(set(seqs))
us = sorted(set(seqs))
gaps = [(a, b) for a, b in zip(us, us[1:]) if b - a > 1]
missing = sum(b - a - 1 for a, b in gaps)
print(f"\n== Changelog: {len(recs)} 条, seq {us[0]}..{us[-1]} (跨度 {us[-1]-us[0]+1}), 重复 {dup}, 缺口 {len(gaps)} 处 / 缺 {missing} 条")
if gaps: print("  前 10 个缺口:", gaps[:10])
tc = collections.Counter(r["type"] for r in recs)
print("  按 type:", dict(tc.most_common()))
print(f"  文件数 {len(files)}, 总 {sum(files)/1e6:.2f} MB, 每文件 avg {statistics.mean(files)/1e3:.0f} KB max {max(files)/1e3:.0f} KB, "
      f"每条 {sum(files)/len(recs):.1f} B (压缩后)")

# ---- 对账：只看负载目录下的文件名 ----
def bn(r):
    for k in ("name", "path", "old_path"):
        if r.get(k): return os.path.basename(r[k])
    return None
load_ips = set()
recs_load = [r for r in recs if (bn(r) or "").startswith("c") or r["type"] in ("TRUNC", "MTIME", "HSM", "SATTR", "CLOSE")]
created = collections.Counter(os.path.basename(o["path"]) for o in ops if o["type"] == "write")
renamed = set(os.path.basename(o["new_path"]) for o in ops if o["type"] == "rename")
deleted = set(os.path.basename(o["path"]) for o in ops if o["type"] == "delete")
cl_creat = set(r["name"] for r in recs if r["type"] == "CREAT" and r.get("name"))
cl_ren_new = set(r["name"] for r in recs if r["type"] == "RENME" and r.get("name"))
cl_unl = set(os.path.basename(r["path"]) for r in recs if r["type"] == "UNLNK" and r.get("path"))
print("\n== 对账（按文件名）")
print(f"  write  {sum(created.values())} 次 → CREAT 命中 {len(set(created) & cl_creat)}, 未命中 {len(set(created) - cl_creat)}")
print(f"  rename {len(renamed)} 次 → RENME 命中 {len(renamed & cl_ren_new)}, 未命中 {len(renamed - cl_ren_new)}")
print(f"  delete {len(deleted)} 次 → UNLNK 命中 {len(deleted & cl_unl)}, 未命中 {len(deleted - cl_unl)}")
print(f"  overwrite {cnt['overwrite']} + trunc_rewrite {cnt['trunc_rewrite']} 次 → TRUNC {tc['TRUNC']} / MTIME {tc['MTIME']}")
print(f"  read {cnt['read']} 次 → 无记录（预期）")

# ---- 记录时间 vs 操作时间 每分钟分布 ----
from datetime import datetime, timezone
def ts(s): return datetime.strptime(s[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
per_min = collections.Counter(int(ts(r["time"]) // 60) for r in recs)
print(f"\n== changelog 记录速率: avg {len(recs)/(t1-t0):.0f} 条/s, 峰值分钟 {max(per_min.values())/60:.0f} 条/s")
