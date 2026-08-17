#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCart 优化前后性能对比图 (吞吐 + 延迟)"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import matplotlib.font_manager as fm

for fp in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"]:
    try:
        fm.fontManager.addfont(fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break
    except Exception:
        pass
plt.rcParams["axes.unicode_minus"] = False

pages = ["首页 home", "分类页 category", "商品页 product"]
before_rps = [6.46, 7.03, 9.01]
after_rps  = [1110.81, 1195.60, 1183.96]
before_p95 = [5142, 4578, 3665]
after_p95  = [65, 58, 56]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.5))
x = np.arange(len(pages)); w = 0.36
GREY="#B0BEC5"; ORANGE="#FF9900"; RED="#D13212"; GREEN="#2E9E5B"; DARK="#232F3E"

# --- 左: 吞吐 (对数轴) ---
b1 = ax1.bar(x - w/2, before_rps, w, label="优化前(直连后端)", color=GREY, edgecolor="white")
b2 = ax1.bar(x + w/2, after_rps, w, label="优化后(CloudFront缓存)", color=ORANGE, edgecolor="white")
ax1.set_yscale("log")
ax1.set_ylabel("吞吐 Requests/sec (对数轴)", fontsize=12)
ax1.set_title("吞吐量对比 — 平均提升 ~150×", fontsize=14, fontweight="bold", color=DARK)
ax1.set_xticks(x); ax1.set_xticklabels(pages, fontsize=11)
ax1.legend(fontsize=10.5, loc="upper left")
ax1.grid(axis="y", ls="--", alpha=0.4)
for r in b1:
    ax1.text(r.get_x()+r.get_width()/2, r.get_height()*1.05, f"{r.get_height():.1f}",
             ha="center", va="bottom", fontsize=9.5, color=DARK)
for i, r in enumerate(b2):
    ax1.text(r.get_x()+r.get_width()/2, r.get_height()*1.05, f"{r.get_height():.0f}",
             ha="center", va="bottom", fontsize=10, fontweight="bold", color=RED)
    mult = after_rps[i]/before_rps[i]
    ax1.text(x[i], after_rps[i]*2.3, f"{mult:.0f}×", ha="center", fontsize=13,
             fontweight="bold", color=RED)

# --- 右: 延迟 P95 ---
b3 = ax2.bar(x - w/2, before_p95, w, label="优化前 P95", color=GREY, edgecolor="white")
b4 = ax2.bar(x + w/2, after_p95, w, label="优化后 P95", color=GREEN, edgecolor="white")
ax2.set_ylabel("P95 延迟 (ms)", fontsize=12)
ax2.set_title("P95 延迟对比 — 5秒 → 60毫秒", fontsize=14, fontweight="bold", color=DARK)
ax2.set_xticks(x); ax2.set_xticklabels(pages, fontsize=11)
ax2.legend(fontsize=10.5, loc="upper right")
ax2.grid(axis="y", ls="--", alpha=0.4)
for r in b3:
    ax2.text(r.get_x()+r.get_width()/2, r.get_height()+80, f"{r.get_height():.0f}ms",
             ha="center", va="bottom", fontsize=9.5, color=DARK)
for r in b4:
    ax2.text(r.get_x()+r.get_width()/2, r.get_height()+80, f"{r.get_height():.0f}ms",
             ha="center", va="bottom", fontsize=10, fontweight="bold", color=GREEN)

fig.suptitle("OpenCart 性能优化实测对比  (单台 t3.small, ApacheBench c50)",
             fontsize=16, fontweight="bold", color="#232F3E", y=1.01)
plt.tight_layout()
plt.savefig("opencart_perf_compare.png", dpi=150, bbox_inches="tight", facecolor="white")
print("saved opencart_perf_compare.png")
