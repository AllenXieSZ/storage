#!/usr/bin/env python3
"""生成 Kafka 电商下单流程图 PNG：展示 Kafka 四大作用"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.font_manager import FontProperties

# 中文字体
import matplotlib.font_manager as fm
zh = None
for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
          "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
          "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"]:
    import os
    if os.path.exists(p):
        zh = fm.FontProperties(fname=p); break
if zh is None:
    zh = fm.FontProperties()  # fallback

BLUE="#0067C5"; ORANGE="#F58220"; GREEN="#2E9E5B"; DARK="#1A2B4A"
GREY="#5A6B82"; LIGHT="#F2F6FB"; RED="#C0392B"; PURPLE="#6A5ACD"

fig, ax = plt.subplots(figsize=(15, 9))
ax.set_xlim(0, 15); ax.set_ylim(0, 9); ax.axis("off")

def box(x,y,w,h,text,fc,tc="white",fs=11,bold=True):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.05,rounding_size=0.12",
                 fc=fc,ec="white",lw=1.5))
    ax.text(x+w/2,y+h/2,text,ha="center",va="center",color=tc,
            fontsize=fs,fontproperties=zh,weight="bold" if bold else "normal")

def arrow(x1,y1,x2,y2,color=DARK,lw=2,style="-|>"):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle=style,
                 mutation_scale=18,color=color,lw=lw))

# 标题
ax.text(7.5,8.6,"Kafka 电商下单流程 —— 四大作用",ha="center",fontproperties=zh,
        fontsize=20,weight="bold",color=DARK)
ax.text(7.5,8.15,"异步 · 削峰填谷 · 解耦广播 · 事件驱动",ha="center",fontproperties=zh,
        fontsize=12,color=ORANGE,weight="bold")

# 用户 + 订单服务
box(0.4,6.6,2.2,0.9,"用户\n点击「提交订单」",GREEN,fs=11)
box(0.4,5.1,2.2,0.9,"订单服务\n(生产者 Producer)",BLUE,fs=11)
arrow(1.5,6.6,1.5,6.0,GREEN)
ax.text(3.0,6.05,"①几十ms\n立即返回成功",ha="left",va="center",fontproperties=zh,
        fontsize=9,color=GREEN,weight="bold")
arrow(2.6,5.55,4.0,5.55,BLUE)
ax.text(3.3,5.8,"发消息",ha="center",fontproperties=zh,fontsize=9,color=BLUE)

# Kafka topic (蓄水池)
ax.add_patch(FancyBboxPatch((4.0,4.7),7.0,1.6,boxstyle="round,pad=0.05,rounding_size=0.15",
             fc=DARK,ec=ORANGE,lw=3))
ax.text(7.5,6.05,"Kafka Topic: order-created  (蓄水池·持久化)",ha="center",
        fontproperties=zh,fontsize=12,color="white",weight="bold")
# 消息块
for i in range(9):
    box(4.3+i*0.72,4.95,0.62,0.55,"msg",ORANGE,fs=8,bold=False)
ax.text(11.15,5.5,"②削峰填谷\n洪峰先蓄住\n下游匀速消费",ha="left",va="center",
        fontproperties=zh,fontsize=9,color=ORANGE,weight="bold")

# 消费者组
consumers = [
    ("库存服务\n扣减库存",BLUE,"核心"),
    ("支付服务\n发起扣款",BLUE,"核心"),
    ("通知服务\n短信/邮件",GREY,"非核心"),
    ("积分服务\n加积分",GREY,"非核心"),
    ("数仓/推荐\n用户画像",PURPLE,"旁路"),
]
n=len(consumers); x0=1.0; gap=2.7
for i,(t,c,tag) in enumerate(consumers):
    x=x0+i*gap
    box(x,2.4,2.2,1.0,t,c,fs=10)
    arrow(min(max(x+1.1,4.3),10.7),4.7,x+1.1,3.4,c,lw=1.8)
    ax.text(x+1.1,2.2,tag,ha="center",va="top",fontproperties=zh,fontsize=8,color=c)

ax.text(7.5,1.75,"③解耦 + 一对多广播：同一条消息被多个消费者组各读一份；加新消费者上游零改动；某服务挂了不影响其他",
        ha="center",fontproperties=zh,fontsize=9.5,color=GREEN,weight="bold")

# 事件驱动链
ax.add_patch(FancyBboxPatch((0.4,0.35),14.2,1.0,boxstyle="round,pad=0.05,rounding_size=0.1",
             fc=LIGHT,ec=BLUE,lw=1.5))
ax.text(7.5,1.05,"④事件驱动状态流转（事件链）",ha="center",fontproperties=zh,
        fontsize=10,color=BLUE,weight="bold")
ax.text(7.5,0.6,"order-created → stock-reserved → payment-completed → order-paid → 物流发货/通知   "
        "（消息持久保留，可回放排查）",
        ha="center",fontproperties=zh,fontsize=9,color=DARK)

plt.tight_layout()
plt.savefig("kafka_ecommerce_flow.png",dpi=130,bbox_inches="tight",facecolor="white")
print("saved kafka_ecommerce_flow.png")
