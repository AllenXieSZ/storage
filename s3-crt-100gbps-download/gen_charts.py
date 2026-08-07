#!/usr/bin/env python3
"""生成 S3 下载吞吐对比图表 (2026-08-07 测试数据)"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))

# --- 图1: Rust 并发度 vs 吞吐 (打满100Gbps的关键) ---
ax = axes[0]
conc = [64, 128, 256]
gbps_8mb = [24.3, 61.4, 94.8]
gbps_16mb = [None, 94.5, 96.3]
ax.plot(conc, gbps_8mb, "o-", lw=2.5, ms=9, color="#0067C5", label="part=8MB")
ax.plot([128, 256], [94.5, 96.3], "s-", lw=2.5, ms=9, color="#F58220", label="part=16MB")
ax.axhline(100, ls="--", color="#888", label="NIC limit 100 Gbps")
ax.set_xlabel("Concurrency (in-flight byte-range GETs)", fontsize=12)
ax.set_ylabel("Throughput (Gbps)", fontsize=12)
ax.set_title("Rust: Concurrency drives throughput\n(single 100GB object, i7i.48xlarge)", fontsize=12, fontweight="bold")
ax.set_xticks(conc)
ax.set_ylim(0, 110)
ax.grid(alpha=0.3); ax.legend(fontsize=10)
for x, y in zip(conc, gbps_8mb):
    ax.annotate(f"{y}", (x, y), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9)
ax.annotate("96.3 Gbps\n(saturates 100G NIC)", (256, 96.3), textcoords="offset points",
            xytext=(-20, -35), ha="center", fontsize=9, color="#F58220", fontweight="bold")

# --- 图2: Python awscrt vs Rust (单对象最佳) ---
ax = axes[1]
methods = ["Python awscrt\n(25G NIC)", "Python awscrt\n(100G NIC)", "Rust sdk-s3\n(100G NIC)"]
best_gbps = [24.4, 53.8, 96.3]
colors = ["#9aa5b1", "#5A6B82", "#2E9E5B"]
bars = ax.bar(methods, best_gbps, color=colors, width=0.6)
ax.axhline(100, ls="--", color="#888")
ax.set_ylabel("Peak Throughput (Gbps)", fontsize=12)
ax.set_title("Best single-object download throughput\nPython awscrt vs Rust", fontsize=12, fontweight="bold")
ax.set_ylim(0, 110)
ax.grid(alpha=0.3, axis="y")
for b, v in zip(bars, best_gbps):
    ax.annotate(f"{v} Gbps\n{v/8:.1f} GB/s", (b.get_x()+b.get_width()/2, v),
                textcoords="offset points", xytext=(0, 6), ha="center", fontsize=10, fontweight="bold")

# --- 图3: part_size 影响 (Python, 25G机型) ---
ax = axes[2]
parts = ["8MB", "16MB", "32MB", "64MB"]
# Python awscrt @100G机型 target=100: 8->50.4(用25G机型8MB25G=24.4更合适? 用100G机型统一), 16->41.7, 32->17.7, 64->17.8
gbps_part = [50.4, 41.7, 17.7, 17.8]
bars = ax.bar(parts, gbps_part, color="#6A5ACD", width=0.6)
ax.set_xlabel("part_size", fontsize=12)
ax.set_ylabel("Throughput (Gbps)", fontsize=12)
ax.set_title("Python awscrt: larger part = slower\n(target=100Gbps, i7i.48xlarge)", fontsize=12, fontweight="bold")
ax.set_ylim(0, 60)
ax.grid(alpha=0.3, axis="y")
for b, v in zip(bars, gbps_part):
    ax.annotate(f"{v}", (b.get_x()+b.get_width()/2, v), textcoords="offset points",
                xytext=(0, 5), ha="center", fontsize=10)

plt.tight_layout()
plt.savefig("s3_download_throughput_charts.png", dpi=110, bbox_inches="tight")
print("saved s3_download_throughput_charts.png")
