import json, glob, sys, statistics as st
rows = []
for f in glob.glob(sys.argv[1] + '.*'):
    if f.endswith('.err'): continue
    for l in open(f):
        try: rows.append(json.loads(l))
        except: pass
go = float(sys.argv[2]); n = len(rows)
tot = sorted(r['start'] + r['total'] - go for r in rows); imp = sorted(r['imp'] for r in rows)
q = lambda a, p: a[min(len(a) - 1, int(p * len(a)))]
print(json.dumps({'n': n, 'p50': q(tot, .5), 'p90': q(tot, .9), 'p99': q(tot, .99), 'max': tot[-1], 'import_p50': q(imp, .5), 'import_p99': q(imp, .99)}))
