#!/usr/bin/env python3
"""3-way comparison of RUN1 vs RUN2 vs RUN3 throughput-upgrade latency."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def load(path):
    return list(csv.DictReader(open(path)))

r1 = load("run1/results_run1.csv")
r2 = load("run2/results_run2.csv")
r3 = load("run3/results_run3.csv")

R1_DONE = 1234
R2_DONE = 1546
R3_DONE = 1336

def series(rows, op, field):
    xs, ys = [], []
    for r in rows:
        if r["phase"] == "upgrade" and r["op"] == op:
            xs.append(float(r["elapsed_sec"]))
            ys.append(float(r[field]))
    return xs, ys

fig, axes = plt.subplots(2, 2, figsize=(16, 10), sharex=True)
panels = [
    (axes[0][0], "read",  "lat_mean_us", "Read clat MEAN (us)"),
    (axes[0][1], "write", "lat_mean_us", "Write clat MEAN (us)"),
    (axes[1][0], "read",  "lat_p99_us",  "Read clat p99 (us)"),
    (axes[1][1], "write", "lat_p99_us",  "Write clat p99 (us)"),
]

runs = [
    (r1, "RUN1", "#0067C5", "o-"),
    (r2, "RUN2", "#F58220", "s-"),
    (r3, "RUN3", "#2E9E5B", "^-"),
]
dones = [(R1_DONE, "#0067C5", "RUN1 done +20.5m"),
         (R2_DONE, "#F58220", "RUN2 done +25.8m"),
         (R3_DONE, "#2E9E5B", "RUN3 done +22.3m")]

for ax, op, field, title in panels:
    for rows, lbl, color, style in runs:
        x, y = series(rows, op, field)
        ax.plot(x, y, style, color=color, markersize=3.2, label=lbl, alpha=0.85)
    for d, c, l in dones:
        ax.axvline(d, color=c, ls=":", lw=1.0)
    ax.set_title(title)
    ax.set_ylabel(field)
    ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, loc="upper right")

axes[1][0].set_xlabel("elapsed seconds since upgrade trigger (T0)")
axes[1][1].set_xlabel("elapsed seconds since upgrade trigger (T0)")

axes[0][1].annotate("RUN1 ONLY: write mean\nspike 12.3 ms @ +167 s\n(RUN2 & RUN3 have none)",
                    xy=(167, 12336), xytext=(330, 8000),
                    arrowprops=dict(arrowstyle="->", color="#0067C5"),
                    fontsize=8, color="#004a8f")
axes[0][0].annotate("RUN3 read single-outlier\nstall 14.8 ms @ +191 s\n(p99 stayed 0.4 ms)",
                    xy=(191, 14795), xytext=(330, 6000),
                    arrowprops=dict(arrowstyle="->", color="#2E9E5B"),
                    fontsize=8, color="#1c6b3d")

fig.suptitle("FSxN SINGLE_AZ_2 Throughput Upgrade 1536->3072 MBps - RUN1 vs RUN2 vs RUN3\n"
             "(fio bs=16k sync direct=1 numjobs=1 iodepth=1, 8s/round) - identical specs all 3 runs",
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig("comparison3.png", dpi=110)
print("saved comparison3.png")
