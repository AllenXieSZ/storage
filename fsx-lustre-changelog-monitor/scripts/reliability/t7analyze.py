#!/usr/bin/env python3
"""t7analyze.py <changelog_dir> <t7_times.txt> : 对每个突发阶段统计 CREAT/UNLNK 条数 vs 预期，并报整体 seq 缺口及缺口内的类型"""
import sys, glob, gzip, json, collections, os
recs = []
for f in glob.glob(f"{sys.argv[1]}/**/*.jsonl.gz", recursive=True):
    for l in gzip.open(f, "rt"): recs.append(json.loads(l))
by = {r["seq"]: r for r in recs}
ev = collections.defaultdict(dict)
for l in open(sys.argv[2]):
    t = l.split()
    if len(t) >= 3 and t[1].endswith(("_start", "_done")): ev[t[0]][t[1]] = float(t[2])
from datetime import datetime, timezone
def ts(s): return datetime.strptime(s[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
for tag, e in ev.items():
    a = e.get("create_start", e.get("cp_start")); b = e.get("rm_done")
    rs = [r for r in recs if a - 1 <= ts(r["time"]) <= b + 5]
    s = sorted(r["seq"] for r in rs)
    c = collections.Counter(r["type"] for r in rs)
    gaps = [(x, y) for x, y in zip(s, s[1:]) if y - x > 1]
    print(f"{tag}: recs={len(rs)} {dict(c)} seq {s[0] if s else '-'}..{s[-1] if s else '-'} gaps={len(gaps)} missing={sum(y-x-1 for x,y in gaps)}")
u = sorted(by); gaps = [(x, y) for x, y in zip(u, u[1:]) if y - x > 1]
print(f"ALL: n={len(recs)} uniq={len(u)} range {u[0]}..{u[-1]} gaps={len(gaps)} missing={sum(y-x-1 for x,y in gaps)}")
for x, y in gaps[:20]: print(f"  gap {x}..{y} ({y-x-1})  before={by[x]['type']}@{by[x]['time'][11:23]} after={by[y]['type']}@{by[y]['time'][11:23]}")
