#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCart on AWS 架构图 + CloudFront 缓存优化路径图"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D
import matplotlib.font_manager as fm

# 中文字体
for fp in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]:
    try:
        fm.fontManager.addfont(fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break
    except Exception:
        pass
plt.rcParams["axes.unicode_minus"] = False

# 颜色（AWS 风）
AWS_ORANGE = "#FF9900"
AWS_BLUE   = "#232F3E"
BLUE       = "#0067C5"
GREEN      = "#2E9E5B"
RED        = "#D13212"
PURPLE     = "#8C4FFF"
LIGHT      = "#F2F6FB"
GREY       = "#5A6B82"

fig, ax = plt.subplots(figsize=(16, 10))
ax.set_xlim(0, 16); ax.set_ylim(0, 10); ax.axis("off")

def box(x, y, w, h, text, fc, ec=None, tc="white", fs=11, bold=True, radius=0.12):
    ec = ec or fc
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.02,rounding_size={radius}",
                       fc=fc, ec=ec, lw=1.5, zorder=2)
    ax.add_patch(p)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            color=tc, fontsize=fs, fontweight="bold" if bold else "normal", zorder=3)

def arrow(x1, y1, x2, y2, color=GREY, style="-|>", lw=2, ls="-", rad=0.0):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, color=color,
                        lw=lw, linestyle=ls, mutation_scale=18,
                        connectionstyle=f"arc3,rad={rad}", zorder=1)
    ax.add_patch(a)

def label(x, y, text, color=GREY, fs=9, bg=None, bold=False):
    kw = dict(ha="center", va="center", color=color, fontsize=fs,
              fontweight="bold" if bold else "normal", zorder=4)
    if bg:
        kw["bbox"] = dict(boxstyle="round,pad=0.25", fc=bg, ec="none", alpha=0.95)
    ax.text(x, y, text, **kw)

# ===== 标题 =====
ax.text(8, 9.6, "OpenCart on AWS — 三层架构 + CloudFront 整页缓存优化",
        ha="center", fontsize=19, fontweight="bold", color=AWS_BLUE)
ax.text(8, 9.15, "us-east-2 (Ohio)  |  VPC 10.20.0.0/16  |  3-AZ 高可用",
        ha="center", fontsize=11, color=GREY)

# ===== 用户 =====
box(0.4, 5.0, 1.7, 0.9, "用户\n(浏览器)", BLUE, fs=11)

# ===== CloudFront =====
box(2.9, 4.6, 2.9, 1.8, "", AWS_ORANGE, ec=AWS_ORANGE, tc="white")
ax.text(4.35, 6.05, "CloudFront (CDN)", ha="center", fontsize=12.5, fontweight="bold", color="white", zorder=3)
ax.text(4.35, 5.62, "边缘缓存匿名 GET 页面", ha="center", fontsize=9.5, color="white", zorder=3)
ax.text(4.35, 5.28, "Cache Policy: TTL 30-300s", ha="center", fontsize=8.5, color="white", zorder=3)
ax.text(4.35, 4.98, "忽略 Cookie · 按 querystring", ha="center", fontsize=8.5, color="white", zorder=3)
ax.text(4.35, 4.72, "CF Function: 剥离 Set-Cookie", ha="center", fontsize=8.5, color="#FFE9C7", zorder=3, fontweight="bold")

# ===== ALB =====
box(6.7, 5.0, 2.0, 0.9, "ALB\n(公有子网×3AZ)", BLUE, fs=10.5)

# ===== EC2 三台 =====
ec2_y = [7.0, 5.0, 3.0]
for i, y in enumerate(ec2_y):
    box(9.6, y, 2.5, 0.95,
        f"EC2 t3.small #{i+1}\nApache+PHP8.5+OpenCart\n(私有子网 AZ{i+1})",
        GREEN, fs=8.5)

# ===== Aurora =====
box(13.0, 5.7, 2.6, 1.1, "Aurora MySQL 8.0\n(db.t4g.medium)\n私有子网", AWS_BLUE, fs=9)
# ===== ElastiCache =====
box(13.0, 3.3, 2.6, 1.1, "ElastiCache Redis\n(cache.t4g.micro)\nSession + Cache", RED, fs=9)

# ===== S3 图片 origin =====
box(9.6, 1.2, 2.5, 0.85, "S3 (商品图片)\n+ OAC", PURPLE, fs=9)

# ===== 连线 =====
arrow(2.1, 5.45, 2.85, 5.45, color=BLUE, lw=2.5)                       # user -> CF
label(2.5, 5.75, "HTTPS", BLUE, 8)

arrow(5.85, 5.45, 6.65, 5.45, color=AWS_ORANGE, lw=2.5)                # CF -> ALB (miss回源)
label(6.28, 5.78, "回源\n(Miss)", RED, 8, bold=True)

# CF -> S3 图片
arrow(4.35, 4.55, 9.6, 1.7, color=PURPLE, lw=1.8, ls="--", rad=-0.15)
label(6.6, 2.6, "/image/* → S3", PURPLE, 8.5)

# ALB -> EC2
for y in ec2_y:
    arrow(8.75, 5.45, 9.55, y+0.47, color=GREEN, lw=1.6, rad=0.05 if y!=5.0 else 0)

# EC2 -> Aurora / Redis
for y in ec2_y:
    arrow(12.15, y+0.47, 12.95, 6.2, color=AWS_BLUE, lw=1.2, ls=":", rad=0.12)
    arrow(12.15, y+0.47, 12.95, 3.85, color=RED, lw=1.2, ls=":", rad=-0.12)
label(12.9, 6.95, "SQL 读写", AWS_BLUE, 8, bg=LIGHT)
label(12.9, 2.55, "Session/Cache", RED, 8, bg=LIGHT)

# ===== 缓存命中路径高亮 =====
arrow(2.85, 5.05, 2.1, 5.05, color=GREEN, lw=2.5, rad=0.0)
label(2.5, 4.75, "命中\n(Hit 65ms)", GREEN, 8, bold=True)

# ===== 图例 =====
legend = [
    Line2D([0],[0], color=AWS_ORANGE, lw=3, label="CloudFront 边缘缓存"),
    Line2D([0],[0], color=RED, lw=2, label="Miss 回源 / Redis"),
    Line2D([0],[0], color=GREEN, lw=2, label="Hit 命中(不回源)"),
    Line2D([0],[0], color=AWS_BLUE, lw=2, ls=":", label="Aurora SQL"),
    Line2D([0],[0], color=PURPLE, lw=2, ls="--", label="S3 图片"),
]
ax.legend(handles=legend, loc="lower left", bbox_to_anchor=(0.01, 0.01),
          fontsize=9, framealpha=0.95, ncol=1)

# ===== 优化效果标注 =====
ax.text(8, 0.55,
        "优化效果：整页缓存命中后  吞吐 6→1110 req/s (172×)   延迟 5142ms→65ms   后端 SQL 122→0",
        ha="center", fontsize=11.5, fontweight="bold", color=RED,
        bbox=dict(boxstyle="round,pad=0.5", fc="#FFF3E0", ec=AWS_ORANGE, lw=1.5))

plt.tight_layout()
plt.savefig("opencart_architecture.png", dpi=150, bbox_inches="tight", facecolor="white")
print("saved opencart_architecture.png")
