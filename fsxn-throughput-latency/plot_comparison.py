#!/usr/bin/env python3
"""Side-by-side comparison of RUN1 vs RUN2 throughput-upgrade latency."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def load(path):
    return list(csv.DictReader(open(path)))

r1 = load("run1/results_run1.csv")
r2 = load("run2/results_run2.csv")

R1_DONE = 1234  # RUN1 upgrade duration (s)
R2_DONE = 1546  # RUN2 upgrade duration (s)

def series(rows, op, field):
    xs, ys = [], []
    for r in rows:
        if r["phase"] == "upgrade" and r["op"] == op:
            xs.append(float(r["elapsed_sec"]))
            ys.append(float(r[field]))
    return xs, ys

fig, axes = plt.subplots(2, 2, figsize=(15, 10), sharex=True)
panels = [
    (axes[0][0], "read",  "lat_mean_us", "Read clat MEAN (µs)"),
    (axes[0][1], "write", "lat_mean_us", "Write clat MEAN (µs)"),
    (axes[1][0], "read",  "lat_p99_us",  "Read clat p99 (µs)"),
    (axes[1][1], "write", "lat_p99_us",  "Write clat p99 (µs)"),
]

for ax, op, field, title in panels:
    x1, y1 = series(r1, op, field)
    x2, y2 = series(r2, op, field)
    ax.plot(x1, y1, "o-", color="#0067C5", markersize=3.5, label="RUN1")
    ax.plot(x2, y2, "s-", color="#F58220", markersize=3.5, label="RUN2")
    ax.axvline(R1_DONE, color="#0067C5", ls=":", lw=1.2, label="RUN1 complete (+20.5m)")
    ax.axvline(R2_DONE, color="#F58220", ls=":", lw=1.2, label="RUN2 complete (+25.8m)")
    ax.set_title(title)
    ax.set_ylabel(field)
    ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7, loc="upper right")

axes[1][0].set_xlabel("elapsed seconds since upgrade trigger (T0)")
axes[1][1].set_xlabel("elapsed seconds since upgrade trigger (T0)")

# annotate RUN1 write mean 12.3ms spike vs RUN2 absence
axes[0][1].annotate("RUN1 write mean spike\n12.3 ms @ +167 s",
                    xy=(167, 12336), xytext=(300, 9000),
                    arrowprops=dict(arrowstyle="->", color="#0067C5"),
                    fontsize=8, color="#004a8f")
axes[0][1].annotate("RUN2 max only ~1.0 ms",
                    xy=(604, 1038), xytext=(700, 300),
                    arrowprops=dict(arrowstyle="->", color="#F58220"),
                    fontsize=8, color="#B35900")

fig.suptitle("FSxN SINGLE_AZ_2 Throughput Upgrade 1536->3072 MBps — RUN1 vs RUN2 Latency Comparison\n"
             "(fio bs=16k sync direct=1 numjobs=1 iodepth=1, 8s/round) — identical specs both runs",
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig("comparison.png", dpi=110)
print("saved comparison.png")
