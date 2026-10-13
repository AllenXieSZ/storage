#!/usr/bin/env python3
"""partsalvage.py <file.part...> : 尽量读出被截断的 .jsonl.gz.part 中的完整 JSON 行，打印 条数/首尾 seq"""
import sys, gzip, json, zlib
for f in sys.argv[1:]:
    raw = open(f, "rb").read(); d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try: txt = d.decompress(raw)
    except Exception as e: txt = b""
    lines = txt.split(b"\n"); good = []
    for l in lines:
        try: good.append(json.loads(l))
        except Exception: pass
    s = [r["seq"] for r in good]
    print(f"{f.split('/')[-1]} bytes={len(raw)} recs={len(good)} seq={min(s) if s else '-'}..{max(s) if s else '-'} last_time={good[-1]['time'] if good else '-'}")
