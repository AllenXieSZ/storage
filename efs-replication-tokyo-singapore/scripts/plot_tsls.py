#!/usr/bin/env python3
"""Plot CloudWatch TimeSinceLastSync (Maximum, 60s) with tier windows. usage: plot_tsls.py results/cw/time_since_last_sync.csv out.png"""
import sys, csv, datetime as D
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
r = list(csv.DictReader(open(sys.argv[1])))
t = [D.datetime.fromisoformat(x["ts"]) for x in r]; v = [float(x["max_s"]) / 60 for x in r]
fig, ax = plt.subplots(figsize=(11, 4.5)); ax.plot(t, v, lw=1.5)
U = lambda s: D.datetime.fromtimestamp(s, D.timezone.utc)
for name, a, b, c in [("10/s", 1791967528, 1791968728, "tab:green"), ("100/s", 1791969299, 1791970499, "tab:orange"), ("1000/s target (~690/s actual)", 1791971733, 1791972939, "tab:red")]:
    ax.axvspan(U(a), U(b), color=c, alpha=.15, label=f"write window {name}")
ax.axhline(15, ls="--", color="k", lw=1, label="15 min RPO (doc)")
ax.set_ylabel("TimeSinceLastSync max (min)"); ax.set_xlabel("UTC"); ax.legend(fontsize=8); ax.grid(alpha=.3)
ax.set_title("EFS replication Tokyo->Singapore: CloudWatch TimeSinceLastSync")
fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(sys.argv[2], dpi=110)
