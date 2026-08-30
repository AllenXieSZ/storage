#!/usr/bin/env python3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm
matplotlib.rcParams["font.sans-serif"]=["Noto Sans CJK SC","Noto Sans CJK JP"]
matplotlib.rcParams["axes.unicode_minus"]=False

NAVY="#1A2B4A"; BLUE="#0067C5"; ORANGE="#F58220"; GREEN="#2E9E5B"; RED="#C0392B"
GREY="#5A6B82"; LIGHT="#F2F6FB"

fig, axes = plt.subplots(1, 2, figsize=(14, 8))
fig.suptitle("FSx ONTAP: 是否开过 FSx 原生 Backup 决定能否就地转 FlexGroup",
             fontsize=17, fontweight="bold", color=NAVY, y=0.97)
fig.text(0.5, 0.925, "同一 FSxN / SVM 内两个 FlexVol 对照 · 唯一变量 = 是否被 FSx 卷级 Backup 备份过一次",
         ha="center", fontsize=11, color=GREY)

def panel(ax, title, tcolor, rows, verdict, vcolor):
    ax.axis("off")
    ax.set_xlim(0,10); ax.set_ylim(0,10)
    ax.add_patch(FancyBboxPatch((0.2,0.3),9.6,9.3,boxstyle="round,pad=0.1",
                 linewidth=2.5, edgecolor=tcolor, facecolor=LIGHT))
    ax.text(5,9.15,title,ha="center",fontsize=14,fontweight="bold",color=tcolor)
    y=8.3
    for label,val,vc in rows:
        ax.text(0.9,y,label,fontsize=10.5,color=NAVY,fontweight="bold")
        ax.text(9.1,y,val,fontsize=10.5,color=vc,ha="right",fontweight="bold")
        y-=0.85
    ax.add_patch(FancyBboxPatch((0.9,0.7),8.2,1.0,boxstyle="round,pad=0.05",
                 linewidth=0, facecolor=vcolor))
    ax.text(5,1.2,verdict,ha="center",fontsize=12.5,fontweight="bold",color="white")

panel(axes[0],"cleanvol（对照 · 从不备份）",BLUE,[
    ("数据量","10 GiB / 100 文件",NAVY),
    ("FSx Backup","从不备份",GREEN),
    ("backup-xxx 参考快照","无",GREEN),
    ("snapmirror show (diag)","空",GREEN),
    ("conversion check-only","仅 Warning，可继续",GREEN),
    ("conversion start","[Job 48] Job succeeded",GREEN),
    ("转换后卷类型","flexgroup (转换成功)",GREEN),
], "结果：成功转 FlexGroup", GREEN)

panel(axes[1],"bkpvol（实验 · 备份过一次）",ORANGE,[
    ("数据量","10 GiB / 100 文件",NAVY),
    ("FSx Backup","卷级备份 1 次(AVAILABLE)",ORANGE),
    ("backup-xxx 参考快照","有(留存60min+稳定)",ORANGE),
    ("snapmirror show (diag)","空(关系隐藏)",ORANGE),
    ("conversion check-only","Error(copy to cloud)",RED),
    ("conversion start","Error，转换未发生",RED),
    ("转换后卷类型","仍 flexvol (未转换)",RED),
], "结果：被 Error 阻塞，无法转", RED)

fig.text(0.5,0.045,
  "裁定：备份过的卷报的是 Error(非 Warning)，Job 未 succeeded，卷仍为 flexvol → 「copy to cloud relationship」确为硬阻塞。\n"
  "删 backup 快照报「used as a reference snapshot by one or more SnapMirror relationships」→ 隐藏的 SnapMirror-to-Cloud 关系坐实。",
  ha="center", fontsize=9.5, color=GREY)
fig.text(0.5,0.008,"仅本次测试环境实测(us-east-2, ONTAP 9.18.1P5, Gen2 SINGLE_AZ_2)，不代表官方结论。",
         ha="center", fontsize=8.5, color=GREY, style="italic")

plt.tight_layout(rect=[0,0.07,1,0.9])
plt.savefig("compare.png", dpi=130, bbox_inches="tight", facecolor="white")
print("saved compare.png")
