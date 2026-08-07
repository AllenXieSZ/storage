#!/usr/bin/env python3
"""Generate charts for FSx Lustre DRA AutoExport performance test."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

groups = ["G1\n4.8TiB / 125\n(600 MB/s)",
          "G2\n4.8TiB / 250\n(1200 MB/s)",
          "G3\n9.6TiB / 125\n(1200 MB/s)"]
export_time = [349, 117, 111]       # seconds
export_tput = [293, 875, 922]       # MB/s
nominal_tput = [600, 1200, 1200]    # MB/s
colors = ["#F58220", "#0067C5", "#2E9E5B"]

fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
fig.suptitle("FSx Lustre DRA AutoExport: 100GB (102,400 x 1MB files) Export Performance",
             fontsize=15, fontweight="bold", color="#1A2B4A")

# Chart 1: export time
ax = axes[0]
bars = ax.bar(groups, export_time, color=colors, width=0.6)
ax.set_ylabel("Export Time (seconds)", fontsize=11)
ax.set_title("(1) Export Duration to S3", fontsize=12, fontweight="bold")
for b, v in zip(bars, export_time):
    ax.text(b.get_x()+b.get_width()/2, v+6, f"{v}s", ha="center", fontweight="bold")
ax.set_ylim(0, max(export_time)*1.18)
ax.annotate("~3x faster", xy=(0.5, 200), fontsize=11, color="#C0392B", fontweight="bold", ha="center")
ax.grid(axis="y", alpha=0.3)

# Chart 2: export throughput vs nominal
ax = axes[1]
x = np.arange(len(groups))
w = 0.38
b1 = ax.bar(x-w/2, nominal_tput, w, label="Nominal total throughput", color="#B0BEC5")
b2 = ax.bar(x+w/2, export_tput, w, label="Measured export throughput", color=colors)
ax.set_ylabel("Throughput (MB/s)", fontsize=11)
ax.set_title("(2) Measured Export vs Nominal Throughput", fontsize=12, fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(groups)
for b, v in zip(b1, nominal_tput):
    ax.text(b.get_x()+b.get_width()/2, v+12, f"{v}", ha="center", fontsize=9, color="#546E7A")
for b, v in zip(b2, export_tput):
    ax.text(b.get_x()+b.get_width()/2, v+12, f"{v}", ha="center", fontsize=9, fontweight="bold")
ax.legend(fontsize=9)
ax.set_ylim(0, 1400)
ax.grid(axis="y", alpha=0.3)

# Chart 3: two comparisons
ax = axes[2]
comp_labels = ["G1 -> G2\n(throughput tier x2)", "G2 vs G3\n(same 1200MB/s:\ntier vs capacity)"]
comp_vals = [349/117, 117/111]  # speedup ratios
cb = ax.bar(comp_labels, comp_vals, color=["#0067C5", "#2E9E5B"], width=0.5)
ax.axhline(1.0, color="grey", ls="--", lw=1)
ax.set_ylabel("Export speed ratio (x)", fontsize=11)
ax.set_title("(3) Key Comparisons", fontsize=12, fontweight="bold")
for b, v in zip(cb, comp_vals):
    ax.text(b.get_x()+b.get_width()/2, v+0.05, f"{v:.2f}x", ha="center", fontweight="bold")
ax.set_ylim(0, 3.4)
ax.grid(axis="y", alpha=0.3)

plt.tight_layout(rect=[0, 0, 1, 0.94])
out = "storage/fsx-dra-export-test/fsx_dra_export_charts.png"
import os
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=130, bbox_inches="tight")
print("saved", out)
