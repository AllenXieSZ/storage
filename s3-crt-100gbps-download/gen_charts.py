#!/usr/bin/env python3
"""生成 S3 100GB 下载 五方案对比图表 (2026-08-07, i7i.48xlarge 100Gbps)"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig, axes = plt.subplots(1, 3, figsize=(19, 5.5))

# --- 图1: 五方案 峰值吞吐排名 ---
ax = axes[0]
methods = ["Rust\n(tokio 256)", "Java\n(SDK v2 256)", "Go\n(512 goroutine)",
           "Python\nawscrt", "Python\nMP 128", "Python\nthreads 256"]
gbps = [96.3, 95.1, 84.2, 53.8, 50.8, 4.8]
colors = ["#2E9E5B", "#2E9E5B", "#5FB878", "#F58220", "#F58220", "#C0392B"]
bars = ax.barh(range(len(methods)), gbps, color=colors)
ax.set_yticks(range(len(methods))); ax.set_yticklabels(methods, fontsize=10)
ax.invert_yaxis()
ax.axvline(100, ls="--", color="#888", label="NIC 100 Gbps")
ax.set_xlabel("Peak Throughput (Gbps)", fontsize=12)
ax.set_title("Single-machine 100GB S3 download\nthroughput ranking (i7i.48xlarge)", fontsize=12, fontweight="bold")
ax.set_xlim(0, 110); ax.legend(fontsize=9)
for i, v in enumerate(gbps):
    ax.annotate(f"{v} Gbps", (v, i), textcoords="offset points", xytext=(5, 0), va="center", fontsize=9, fontweight="bold")

# --- 图2: 并发度 vs 吞吐 (三个无GIL语言 + Python threads) ---
ax = axes[1]
conc = [64, 128, 256, 512]
rust = [None, None, 94.8, None]   # rust 8MB: 256=94.8
go   = [None, 73.5, 76.0, 84.2]
java = [None, 49.0, 85.2, 88.2]
pyth = [None, 4.7, 4.8, 4.6]
ax.plot([256], [94.8], "D", ms=11, color="#2E9E5B", label="Rust (8MB)")
ax.plot([128,256,512], go[1:], "o-", lw=2, ms=8, color="#5FB878", label="Go (8MB)")
ax.plot([128,256,512], java[1:], "s-", lw=2, ms=8, color="#0067C5", label="Java (8MB)")
ax.plot([128,256,512], pyth[1:], "^-", lw=2, ms=8, color="#C0392B", label="Python threads (8MB)")
ax.axhline(100, ls="--", color="#888")
ax.set_xlabel("Concurrency", fontsize=12); ax.set_ylabel("Throughput (Gbps)", fontsize=12)
ax.set_title("Concurrency vs throughput\n(no-GIL langs scale, Python GIL flat)", fontsize=12, fontweight="bold")
ax.set_xticks(conc); ax.set_ylim(0, 110); ax.grid(alpha=0.3); ax.legend(fontsize=9)
ax.annotate("Python GIL:\nflat ~5 Gbps", (350, 15), fontsize=9, color="#C0392B", fontweight="bold")

# --- 图3: Python 多线程 vs 多进程 vs awscrt ---
ax = axes[2]
pym = ["threads\n256 (GIL)", "multiproc\n128", "awscrt\n(best)"]
pyg = [4.8, 50.8, 53.8]
bars = ax.bar(pym, pyg, color=["#C0392B", "#F58220", "#6A5ACD"], width=0.6)
ax.axhline(100, ls="--", color="#888", label="NIC 100 Gbps")
ax.set_ylabel("Throughput (Gbps)", fontsize=12)
ax.set_title("Python: why it can't saturate 100G\n(GIL caps threads; MP/awscrt ~50G)", fontsize=12, fontweight="bold")
ax.set_ylim(0, 110); ax.grid(alpha=0.3, axis="y"); ax.legend(fontsize=9)
for b, v in zip(bars, pyg):
    ax.annotate(f"{v} Gbps", (b.get_x()+b.get_width()/2, v), textcoords="offset points",
                xytext=(0, 5), ha="center", fontsize=10, fontweight="bold")

plt.tight_layout()
plt.savefig("s3_download_throughput_charts.png", dpi=110, bbox_inches="tight")
print("saved s3_download_throughput_charts.png")
