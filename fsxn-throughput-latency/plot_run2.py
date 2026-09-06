#!/usr/bin/env python3
"""Plot FSxN throughput-upgrade latency curve for RUN2 from run2/results_run2.csv."""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = list(csv.DictReader(open("run2/results_run2.csv")))
UPGRADE_COMPLETE_ELAPSED = 1546  # trigger 05:21:42 -> COMPLETED 05:47:28

def series(phase, op):
    xs, mean, p99 = [], [], []
    for r in rows:
        if r["phase"] == phase and r["op"] == op:
            xs.append(float(r["elapsed_sec"]))
            mean.append(float(r["lat_mean_us"]))
            p99.append(float(r["lat_p99_us"]))
    return xs, mean, p99

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

for op, color in [("read", "#0067C5"), ("write", "#F58220")]:
    xb, mb, _ = series("baseline", op)
    xu, mu, _ = series("upgrade", op)
    ax1.plot(xb, mb, "o--", color=color, alpha=0.5, markersize=4,
             label=f"{op} baseline mean")
    ax1.plot(xu, mu, "o-", color=color, markersize=4, label=f"{op} mean")

ax1.axvspan(0, UPGRADE_COMPLETE_ELAPSED, color="#FFE9B0", alpha=0.4,
            label="throughput upgrade window (1536->3072 MBps)")
ax1.axvline(0, color="green", ls=":", lw=1.5)
ax1.axvline(UPGRADE_COMPLETE_ELAPSED, color="red", ls=":", lw=1.5)
ax1.annotate("read mean bump ~0.8 ms\n@ +805 s",
             xy=(805, 808), xytext=(950, 2000),
             arrowprops=dict(arrowstyle="->", color="#0067C5"),
             fontsize=9, color="#004a8f")
ax1.annotate("write mean peak ~1.0 ms\n@ +604 s (no 12ms-class spike this run)",
             xy=(604, 1038), xytext=(650, 4000),
             arrowprops=dict(arrowstyle="->", color="#F58220"),
             fontsize=9, color="#B35900")
ax1.set_ylabel("clat mean (µs)")
ax1.set_title("RUN2 — FSxN SINGLE_AZ_2 Throughput Upgrade 1536->3072 MBps — IO Latency Impact\n"
              "(fio bs=16k sync direct=1 numjobs=1 iodepth=1, runtime=8s/round)")
ax1.legend(fontsize=8, ncol=2, loc="upper right")
ax1.grid(True, alpha=0.3)
ax1.set_yscale("log")

for op, color in [("read", "#0067C5"), ("write", "#F58220")]:
    xu, _, pu = series("upgrade", op)
    ax2.plot(xu, pu, "o-", color=color, markersize=4, label=f"{op} p99")
ax2.axvspan(0, UPGRADE_COMPLETE_ELAPSED, color="#FFE9B0", alpha=0.4)
ax2.axvline(0, color="green", ls=":", lw=1.5, label="T0 upgrade start")
ax2.axvline(UPGRADE_COMPLETE_ELAPSED, color="red", ls=":", lw=1.5,
            label="upgrade COMPLETED (~+25.8 min)")
ax2.set_ylabel("clat p99 (µs)")
ax2.set_xlabel("elapsed seconds since upgrade trigger (T0)")
ax2.legend(fontsize=8, loc="upper right")
ax2.grid(True, alpha=0.3)
ax2.set_yscale("log")

plt.tight_layout()
plt.savefig("run2/latency_curve_run2.png", dpi=110)
print("saved run2/latency_curve_run2.png")
