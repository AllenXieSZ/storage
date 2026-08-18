#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenCart 生产级架构图 (ASG + CloudFront + Aurora读写分离 + Redis)"""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D
import matplotlib.font_manager as fm
for fp in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc","/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc","/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"]:
    try: fm.fontManager.addfont(fp); plt.rcParams["font.family"]=fm.FontProperties(fname=fp).get_name(); break
    except: pass
plt.rcParams["axes.unicode_minus"]=False
ORANGE="#FF9900";BLUE="#0067C5";GREEN="#2E9E5B";RED="#D13212";PURPLE="#8C4FFF";DARK="#232F3E";LIGHT="#F2F6FB";GREY="#5A6B82"
fig,ax=plt.subplots(figsize=(17,10.5));ax.set_xlim(0,17);ax.set_ylim(0,10.5);ax.axis("off")
def box(x,y,w,h,t,fc,tc="white",fs=10,bold=True,r=0.1):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle=f"round,pad=0.02,rounding_size={r}",fc=fc,ec=fc,lw=1.5,zorder=2))
    ax.text(x+w/2,y+h/2,t,ha="center",va="center",color=tc,fontsize=fs,fontweight="bold" if bold else "normal",zorder=3)
def arrow(x1,y1,x2,y2,c=GREY,lw=2,ls="-",rad=0):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",color=c,lw=lw,linestyle=ls,mutation_scale=16,connectionstyle=f"arc3,rad={rad}",zorder=1))
def lab(x,y,t,c=GREY,fs=8.5,bg=None,bold=False):
    kw=dict(ha="center",va="center",color=c,fontsize=fs,fontweight="bold" if bold else "normal",zorder=4)
    if bg: kw["bbox"]=dict(boxstyle="round,pad=0.25",fc=bg,ec="none",alpha=0.95)
    ax.text(x,y,t,**kw)

ax.text(8.5,10.0,"OpenCart 生产级弹性架构 (AWS us-east-2)",ha="center",fontsize=20,fontweight="bold",color=DARK)
ax.text(8.5,9.55,"读路径→CloudFront缓存(实测7.6万QPS) · 写路径→ASG弹性+读写分离 · 全链路优化",ha="center",fontsize=11,color=GREY)

# 用户
box(0.3,5.2,1.5,0.9,"用户\n浏览器",BLUE,fs=10)
# CloudFront
box(2.3,4.8,2.6,1.7,"",ORANGE)
ax.text(3.6,5.95,"CloudFront CDN",ha="center",fontsize=12,fontweight="bold",color="white",zorder=3)
ax.text(3.6,5.5,"匿名页整页缓存",ha="center",fontsize=9,color="white",zorder=3)
ax.text(3.6,5.2,"忽略Cookie+剥离SetCookie",ha="center",fontsize=8,color="#FFE9C7",zorder=3)
ax.text(3.6,4.95,"读路径 7.6万 QPS",ha="center",fontsize=9,color="white",fontweight="bold",zorder=3)
# ALB
box(5.6,5.2,1.8,0.9,"ALB\n×3 AZ",BLUE,fs=10)
# ASG 框
ax.add_patch(FancyBboxPatch((8.1,2.4),3.4,4.6,boxstyle="round,pad=0.05,rounding_size=0.1",fc="none",ec=GREEN,lw=2,ls="--",zorder=1))
ax.text(9.8,6.75,"Auto Scaling Group",ha="center",fontsize=11,fontweight="bold",color=GREEN,zorder=3)
ax.text(9.8,6.45,"min3 / max24 · c7i.xlarge",ha="center",fontsize=8.5,color=GREEN,zorder=3)
ax.text(9.8,6.2,"CPU50%+ReqCount目标追踪 · warmup180s",ha="center",fontsize=7.5,color=GREY,zorder=3)
for i,yy in enumerate([4.9,3.9,2.9]):
    box(8.4,yy,2.8,0.8,f"EC2 app #{i+1}\nApache+PHP8.5+OpenCart\nfpm200/httpd800 · hc.html",GREEN,fs=7.5)
ax.text(9.8,2.5,"每台≈200-230 TPS(写)",ha="center",fontsize=8,color=RED,fontweight="bold",zorder=3)
# Aurora
box(12.6,5.6,4.0,1.0,"Aurora MySQL 8.0 (db.r6g.xlarge×2)",DARK,fs=9.5)
box(12.6,4.55,1.9,0.8,"Writer\n(写)",RED,fs=9)
box(14.7,4.55,1.9,0.8,"Reader\n(读,读写分离)",GREEN,fs=9)
# Redis
box(12.6,3.0,4.0,1.0,"ElastiCache Redis\nSession + 购物车 + 商品/配置缓存",PURPLE,fs=9)
# S3
box(2.3,2.8,2.6,0.8,"S3 商品图片 + OAC",PURPLE,fs=9)

# 连线
arrow(1.8,5.65,2.25,5.65,BLUE,2.2); lab(2.05,5.95,"HTTPS",BLUE,8)
arrow(3.6,4.75,3.0,3.62,PURPLE,1.6,"--",-0.15); lab(2.6,4.2,"/image→S3",PURPLE,8)
arrow(4.95,5.65,5.55,5.65,ORANGE,2.2); lab(5.25,5.95,"回源\nMiss",RED,8,bold=True)
for yy in [5.3,4.3,3.3]:
    arrow(7.45,5.65,8.35,yy+0.4,GREEN,1.4,rad=0.05)
arrow(11.55,4.9,12.55,5.0,RED,1.4,rad=0.1); lab(12.0,5.4,"写→Writer",RED,7.5,bg=LIGHT)
arrow(11.55,4.5,12.55,4.9,GREEN,1.4,rad=-0.05); lab(12.0,4.2,"SELECT→Reader",GREEN,7.5,bg=LIGHT)
arrow(11.55,3.8,12.55,3.5,PURPLE,1.4,rad=-0.1); lab(11.9,3.15,"Session/Cart/Cache",PURPLE,7.5,bg=LIGHT)

leg=[Line2D([0],[0],color=ORANGE,lw=3,label="CloudFront 缓存(读)"),
     Line2D([0],[0],color=GREEN,lw=2,label="ASG弹性 / Reader读"),
     Line2D([0],[0],color=RED,lw=2,label="Writer写"),
     Line2D([0],[0],color=PURPLE,lw=2,ls="--",label="Redis/S3")]
ax.legend(handles=leg,loc="lower left",bbox_to_anchor=(0.01,0.01),fontsize=9,framealpha=0.95)

ax.text(8.5,0.45,"关键结论：OpenCart 动态请求是延迟型(每页100+SQL/几十次往返)，打不满CPU；生产必须靠CDN挡读流量+写路径优化+ASG水平扩展",
        ha="center",fontsize=10.5,fontweight="bold",color=RED,bbox=dict(boxstyle="round,pad=0.5",fc="#FFF3E0",ec=ORANGE,lw=1.5))
plt.tight_layout();plt.savefig("opencart_prod_architecture.png",dpi=150,bbox_inches="tight",facecolor="white")
print("saved opencart_prod_architecture.png")
