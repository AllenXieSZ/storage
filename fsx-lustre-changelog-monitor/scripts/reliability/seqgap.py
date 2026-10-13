#!/usr/bin/env python3
"""seqgap.py <file...> : 读 lfs changelog 原始文本(.txt) 或 collector 输出(.jsonl.gz)，打印条数/范围/重复/缺口"""
import sys, gzip, json
def seqs(f):
    if f.endswith(".gz"):
        return [json.loads(l)["seq"] for l in gzip.open(f, "rt")]
    return [int(l.split()[0]) for l in open(f, errors="replace") if l[:1].isdigit()]
allv = []
for f in sys.argv[1:]: allv += seqs(f)
u = sorted(set(allv))
gaps = [(a, b) for a, b in zip(u, u[1:]) if b - a > 1]
print(f"n={len(allv)} uniq={len(u)} dup={len(allv)-len(u)} range={u[0]}..{u[-1]} gaps={len(gaps)} missing={sum(b-a-1 for a,b in gaps)} first_gaps={gaps[:8]}")
