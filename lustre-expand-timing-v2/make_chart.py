#!/usr/bin/env python3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
fm.fontManager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
plt.rcParams["font.family"] = "Noto Sans CJK SC"
plt.rcParams["axes.unicode_minus"] = False

NETAPP_BLUE="#0067C5"; ORANGE="#F58220"; GREEN="#2E9E5B"; DARK="#1A2B4A"; GREY="#5A6B82"; RED="#C0392B"

fig, (ax1, ax2, ax3) = plt.subplots(3,1, figsize=(12,11),
                                    gridspec_kw={'height_ratios':[1,1,1.1]})
fig.suptitle("FSx for Lustre 扩容耗时对照 v1(900G) vs v2(~1.05TB, 92%满): 1.2\u21922.4 TiB",
             fontsize=15, fontweight="bold", color=DARK)

# --- Top: v2 timeline ---
ax1.set_title("v2 扩容时间线 (灌到 ~92%满 / 从 update-file-system 发起 = 0 分)", fontsize=12, color=DARK, loc="left")
V2_AVAIL=1007; V2_OPT=2763
phases = [
    ("Lifecycle: UPDATING (加 OST / 扩容中)", 0, V2_AVAIL, NETAPP_BLUE),
    ("AVAILABLE + 后台 STORAGE_OPTIMIZATION (数据重分布)", V2_AVAIL, V2_OPT, ORANGE),
]
for label,s,e,c in phases:
    ax1.barh(0, (e-s)/60.0, left=s/60.0, height=0.5, color=c, edgecolor="white")
    ax1.text((s+e)/2/60.0, 0, label, ha="center", va="center", fontsize=9, color="white", fontweight="bold")
ax1.axvline(V2_AVAIL/60.0, color=GREEN, lw=2.5, ls="--")
ax1.text(V2_AVAIL/60.0, 0.42, "  ★ AVAILABLE @ 16.8 min", color=GREEN, fontsize=10, fontweight="bold", va="bottom")
ax1.text(V2_OPT/60.0, -0.42, "重分布完成 @ 46.0 min ", color=ORANGE, fontsize=9, ha="right", va="top", fontweight="bold")
ax1.set_xlim(0, 50); ax1.set_ylim(-0.8, 0.9)
ax1.set_xlabel("分钟", color=GREY); ax1.set_yticks([])
ax1.grid(axis="x", alpha=0.3)

# --- Middle: v1 vs v2 duration comparison ---
ax2.set_title("v1 vs v2 关键耗时对照 (分钟)", fontsize=12, color=DARK, loc="left")
metrics = ["到 AVAILABLE\n(新容量可用)", "STORAGE_OPTIMIZATION\n重分布完成"]
v1 = [15.7, 38.9]; v2 = [16.8, 46.0]
x = range(len(metrics)); w=0.35
b1 = ax2.bar([i-w/2 for i in x], v1, w, label="v1: 灌 900G (79%满)", color=NETAPP_BLUE)
b2 = ax2.bar([i+w/2 for i in x], v2, w, label="v2: 灌 ~1.05TB (92%满)", color=ORANGE)
for bars in (b1,b2):
    for b in bars:
        ax2.text(b.get_x()+b.get_width()/2, b.get_height()+0.6, f"{b.get_height():.1f}", ha="center", fontsize=10, color=DARK, fontweight="bold")
ax2.set_xticks(list(x)); ax2.set_xticklabels(metrics, fontsize=10)
ax2.set_ylabel("分钟", color=GREY); ax2.set_ylim(0, 52)
ax2.legend(loc="upper left", fontsize=9)
ax2.grid(axis="y", alpha=0.3)
ax2.text(1, 49, "数据越满, 重分布耗时明显变长 (+7.1 min); 到 AVAILABLE 仅略增 (+1.1 min)",
         ha="center", fontsize=9, color=RED, style="italic", fontweight="bold")

# --- Bottom: v2 OST distribution before/after ---
ax3.set_title("v2 扩容前后 OST 数据分布 (lfs df, Used GB)", fontsize=12, color=DARK, loc="left")
labels = ["OST0000", "OST0001 (新)"]
before = [1050.0, 0.1]    # right after AVAILABLE (OST0000 93% ~1.0T, OST0001 ~108M)
after  = [570.1, 514.0]   # after optimization complete
x = range(len(labels)); w=0.35
b1 = ax3.bar([i-w/2 for i in x], before, w, label="扩容刚 AVAILABLE 时", color=NETAPP_BLUE)
b2 = ax3.bar([i+w/2 for i in x], after, w, label="STORAGE_OPTIMIZATION 完成后", color=GREEN)
for bars in (b1,b2):
    for b in bars:
        ax3.text(b.get_x()+b.get_width()/2, b.get_height()+10, f"{b.get_height():.0f}G", ha="center", fontsize=9, color=DARK)
ax3.set_xticks(list(x)); ax3.set_xticklabels(labels, fontsize=11)
ax3.set_ylabel("Used (GB)", color=GREY); ax3.set_ylim(0, 1200)
ax3.legend(loc="upper right", fontsize=9)
ax3.grid(axis="y", alpha=0.3)
ax3.text(0.5, 1140, "老数据初始全在 OST0000; 重分布后 570G:514G (比 v1 的 549:361 更接近 50:50)",
         ha="center", fontsize=9, color=GREY, style="italic")

plt.tight_layout(rect=[0,0,1,0.97])
plt.savefig("lustre_expand_timeline_v2.png", dpi=120, bbox_inches="tight")
print("saved lustre_expand_timeline_v2.png")
