#!/usr/bin/env python3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 尝试用中文字体
for fp in ["/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
           "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]:
    try:
        font_manager.fontManager.addfont(fp)
        matplotlib.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False

# (elapsed_s, df_size_bytes, df_used_bytes) 全新卷 volc, autosize grow max18g
raw = [
(0,12240683008,327680),(6,12240683008,12713984),(7,12240683008,205455360),(8,12240683008,383647744),
(10,12240683008,556335104),(11,12240683008,674234368),(12,12240683008,1278869504),(16,12240683008,1575419904),
(18,12240683008,1943666688),(22,12240683008,2246443008),(23,12240683008,2610954240),(27,12240683008,2919497728),
(28,12240683008,3276734464),(32,12240683008,3580952576),(33,12240683008,3945725952),(37,12240683008,4251844608),
(39,12240683008,4618846208),(42,12240683008,4911923200),(44,12240683008,5391974400),(49,12240683008,5455151104),
(50,12240683008,5581504512),(52,12240683008,5771100160),(53,12240683008,6313541632),(56,12240683008,6439829504),
(58,12240683008,7079788544),(61,12240683008,7153451008),(64,12240683008,7774404608),(68,12240683008,7895711744),
(69,12240683008,8502050816),(74,12240683008,8880455680),(76,12240683008,9173860352),(79,12240683008,9457631232),
(80,12240683008,9848553472),(84,12240683008,10119413760),(86,12377784320,10575806464),(88,12782534656,10783752192),
(92,12782534656,10851123200),(93,12782534656,10985930752),(95,13614186496,11556814848),(98,13831045120,11667439616),
(100,14636810240,12318474240),(103,14636810240,12348096512),(105,14934212608,12615614464),(106,15397224448,13020823552),
(110,15726411776,13316128768),(111,16219111424,13700562944),(115,16522936320,13985316864),(117,16958685184,14380695552),
(120,17322344448,14649393152),(122,17798856704,15043723264),(126,18123063296,15326183424),(127,18361024512,15715074048),
(129,18361024512,16056713216),(132,18361024512,16175923200),(140,18361024512,16175923200),(150,18361024512,16175988736),
(160,18361024512,16175988736),(170,18361024512,16175988736),
]

GB = 1024**3
t = [r[0] for r in raw]
size = [r[1]/GB for r in raw]
used = [r[2]/GB for r in raw]

fig, ax = plt.subplots(figsize=(12,6.5))
ax.plot(t, size, color="#0067C5", lw=2.4, marker="o", ms=3.5, label="Volume size (卷容量)")
ax.plot(t, used, color="#F58220", lw=2.0, marker="s", ms=2.5, label="Used (已写入数据)")

trig = 12*0.85
ax.axhline(trig, color="#888", ls="--", lw=1.2)
ax.text(2, trig-0.5, f"85% grow-threshold ≈ {trig:.1f} GB", color="#555", fontsize=9)
ax.axhline(18, color="#2E9E5B", ls=":", lw=1.5)
ax.text(2, 18.15, "max-autosize = 18 GB", color="#2E9E5B", fontsize=9)
ax.axhline(12, color="#bbb", ls="-", lw=0.8)
ax.text(2, 11.5, "initial size = 12 GB", color="#999", fontsize=9)

ax.annotate("扩容开始\n(used越过85%, t≈86s)", xy=(86,12.13), xytext=(45,14.2),
            arrowprops=dict(arrowstyle="->", color="#0067C5"), fontsize=9, color="#0067C5")
ax.annotate("到达上限 18GB\n(t≈127s)", xy=(127,18), xytext=(134,15.5),
            arrowprops=dict(arrowstyle="->", color="#2E9E5B"), fontsize=9, color="#2E9E5B")

ax.set_xlabel("时间 (秒)", fontsize=11)
ax.set_ylabel("容量 (GB)", fontsize=11)
ax.set_title("FSx for ONTAP Volume Autosize 扩容曲线 (实测)\n初始12GB · mode=grow · threshold=85% · max=18GB · 全新卷 volc",
             fontsize=13)
ax.set_ylim(0, 19.5); ax.set_xlim(0, 172)
ax.grid(True, alpha=0.3)
ax.legend(loc="lower right", fontsize=10)
plt.tight_layout()
plt.savefig("/home/ubuntu/.openclaw/workspace/autosize_curve.png", dpi=130)
print("saved")
