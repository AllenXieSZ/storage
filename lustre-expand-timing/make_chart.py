#!/usr/bin/env python3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
plt.rcParams["font.family"] = "Noto Sans CJK SC"
plt.rcParams["axes.unicode_minus"] = False

NETAPP_BLUE="#0067C5"; ORANGE="#F58220"; GREEN="#2E9E5B"; DARK="#1A2B4A"; GREY="#5A6B82"

fig, (ax1, ax2) = plt.subplots(2,1, figsize=(12,8), gridspec_kw={'height_ratios':[1,1.1]})
fig.suptitle("FSx for Lustre 容量扩容实测: 1.2 TiB \u2192 2.4 TiB (PERSISTENT_2 / 500 MB/s/TiB)",
             fontsize=15, fontweight="bold", color=DARK)

# --- Top: timeline (Gantt-ish) ---
# phases relative to expand submit (t=0)
ax1.set_title("扩容时间线 (从 update-file-system 发起 = 0 分)", fontsize=12, color=DARK, loc="left")
phases = [
    ("Lifecycle: UPDATING (加 OST / 扩容中)", 0, 943, NETAPP_BLUE),
    ("Lifecycle: AVAILABLE + 后台 STORAGE_OPTIMIZATION (数据重分布)", 943, 2336, ORANGE),
]
for i,(label,s,e,c) in enumerate(phases):
    ax1.barh(0, (e-s)/60.0, left=s/60.0, height=0.5, color=c, edgecolor="white")
    ax1.text((s+e)/2/60.0, 0, label, ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax1.axvline(943/60.0, color=GREEN, lw=2.5, ls="--")
ax1.text(943/60.0, 0.42, "  ★ AVAILABLE @ 15.7 min\n  (新容量 2400 GiB 可用)", color=GREEN, fontsize=10, fontweight="bold", va="bottom")
ax1.text(2336/60.0, -0.42, "重分布完成 @ 38.9 min ", color=ORANGE, fontsize=9, ha="right", va="top", fontweight="bold")
ax1.set_xlim(0, 42); ax1.set_ylim(-0.8, 0.9)
ax1.set_xlabel("分钟", color=GREY); ax1.set_yticks([])
ax1.grid(axis="x", alpha=0.3)

# --- Bottom: OST capacity/used before vs after optimization ---
ax2.set_title("扩容前后 OST 数据分布 (lfs df, Used GB)", fontsize=12, color=DARK, loc="left")
labels = ["OST0000", "OST0001 (新)"]
before = [910.2, 20.8]   # right after AVAILABLE
after  = [549.1, 360.8]  # after optimization complete
x = range(len(labels)); w=0.35
b1 = ax2.bar([i-w/2 for i in x], before, w, label="扩容刚 AVAILABLE 时", color=NETAPP_BLUE)
b2 = ax2.bar([i+w/2 for i in x], after, w, label="STORAGE_OPTIMIZATION 完成后", color=GREEN)
for bars in (b1,b2):
    for b in bars:
        ax2.text(b.get_x()+b.get_width()/2, b.get_height()+8, f"{b.get_height():.0f}G", ha="center", fontsize=9, color=DARK)
ax2.set_xticks(list(x)); ax2.set_xticklabels(labels, fontsize=11)
ax2.set_ylabel("Used (GB)", color=GREY); ax2.set_ylim(0, 1050)
ax2.legend(loc="upper right", fontsize=9)
ax2.grid(axis="y", alpha=0.3)
ax2.text(0.5, 1000, "新容量靠新增 OST0001 实现; 老数据初始全在 OST0000, 后台重分布 ~350G 到新 OST",
         ha="center", fontsize=9, color=GREY, style="italic")

plt.tight_layout(rect=[0,0,1,0.96])
plt.savefig("lustre_expand_timeline.png", dpi=120, bbox_inches="tight")
print("saved lustre_expand_timeline.png")
