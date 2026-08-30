#!/usr/bin/env python3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm

# fonts
plt.rcParams["font.family"] = "DejaVu Sans"
NAVY="#1A2B4A"; BLUE="#0067C5"; ORANGE="#F58220"; GREEN="#2E9E5B"; RED="#C0392B"; GREY="#5A6B82"; LIGHT="#F2F6FB"

fig, ax = plt.subplots(figsize=(13, 6.2), dpi=140)
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

# Title
ax.text(50, 96, "DataSync -> FlexVol->FlexGroup Conversion: Root-Cause Experiment",
        ha="center", va="top", fontsize=17, fontweight="bold", color=NAVY)
ax.text(50, 90.5, "Does DataSync (NFS mode) leave a hidden SnapMirror / copy-to-cloud relationship that blocks conversion?",
        ha="center", va="top", fontsize=10.5, color=GREY)

# Timeline steps
steps = [
    ("1. Load data\n100 files / 10 GiB", "52 s", BLUE),
    ("2. PRE-check\nsnapmirror/snapshot", "EMPTY", GREY),
    ("3. DataSync\ntransfer (NFS)", "156 s\n(102 files,10GiB)", BLUE),
    ("4. POST-check\nsnapmirror/snapshot", "STILL EMPTY", GREEN),
    ("5. Expand 1->2 HA pair", "670 s (~11 min)\nstill EMPTY", ORANGE),
    ("6. volume conversion\nstart (diag)", "JOB SUCCEEDED\n<1 min", GREEN),
]
n=len(steps)
x0=4; x1=96; box_w=13; gap=(x1-x0-box_w)/(n-1)
y=58
for i,(label,val,col) in enumerate(steps):
    x=x0+i*gap
    box=FancyBboxPatch((x, y), box_w, 20, boxstyle="round,pad=0.4,rounding_size=1.5",
                       linewidth=2, edgecolor=col, facecolor=LIGHT)
    ax.add_patch(box)
    ax.text(x+box_w/2, y+15, label, ha="center", va="center", fontsize=9, fontweight="bold", color=NAVY)
    ax.text(x+box_w/2, y+5.5, val, ha="center", va="center", fontsize=8.5, color=col, fontweight="bold")
    if i < n-1:
        ax.annotate("", xy=(x+box_w+gap-box_w+0.5+box_w, y+10) if False else (x+box_w+ (gap-box_w) , y+10),
                    xytext=(x+box_w, y+10),
                    arrowprops=dict(arrowstyle="->", color=GREY, lw=1.6))

# Comparison callout: step2 vs step4 vs step5
ax.text(50, 47, "Key comparison (source volume, diagnostic level):", ha="center", fontsize=11, fontweight="bold", color=NAVY)
rows=[
    ("Before DataSync (step 2)", "snapmirror show: EMPTY  |  list-destinations: EMPTY  |  snapshot: 0", GREY),
    ("After DataSync (step 4)", "snapmirror show: EMPTY  |  list-destinations: EMPTY  |  snapshot: 0   -> NO CHANGE", GREEN),
    ("After 2HA expand (step 5)", "snapmirror show: EMPTY  |  list-destinations: EMPTY  |  snapshot: 0   -> NO CHANGE", GREEN),
]
yy=41
for title,txt,col in rows:
    ax.text(8, yy, title+":", ha="left", fontsize=9.5, fontweight="bold", color=col)
    ax.text(38, yy, txt, ha="left", fontsize=9, color=NAVY, family="DejaVu Sans Mono")
    yy-=5

# Conclusion band
conc=FancyBboxPatch((4, 6), 92, 15, boxstyle="round,pad=0.5,rounding_size=2",
                    linewidth=2.5, edgecolor=GREEN, facecolor="#E8F6EE")
ax.add_patch(conc)
ax.text(50, 17.5, "CONCLUSION", ha="center", fontsize=12, fontweight="bold", color=GREEN)
ax.text(50, 11.5, "DataSync (NFS mode) creates NO SnapMirror / copy-to-cloud relationship and NO backup snapshot on the source.",
        ha="center", fontsize=10, color=NAVY)
ax.text(50, 7.5, "This DataSync'd volume, after 2HA expansion, converted to FlexGroup successfully ([Job] succeeded). Blocking NOT reproduced here.",
        ha="center", fontsize=10, color=NAVY, fontweight="bold")

ax.text(99, 1.5, "Test env only, not an official statement.  us-east-2  ONTAP 9.18.1P5  Gen2 SINGLE_AZ_2",
        ha="right", fontsize=7.5, color=GREY, style="italic")

plt.tight_layout()
plt.savefig("timeline.png", bbox_inches="tight", facecolor="white")
print("saved timeline.png")
