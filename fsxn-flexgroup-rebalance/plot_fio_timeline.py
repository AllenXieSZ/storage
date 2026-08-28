#!/usr/bin/env python3
"""Parse fio ETA time-series log and plot BW/IOPS over time with phase shading.
Source: /tmp/storage_repo/fsxn-flexgroup-rebalance/fio_timeseries_raw.txt
fio runtime=13000s; each sample's [pct%] gives elapsed fraction.
"""
import re, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
matplotlib.rcParams["font.sans-serif"]=["Noto Sans CJK SC","Noto Serif CJK SC","DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"]=False

RUNTIME_S = 13000.0
raw = open("/tmp/storage_repo/fsxn-flexgroup-rebalance/fio_timeseries_raw.txt").read()

pat = re.compile(r"\[(\d+\.\d+)%\]\[r=([\d.]+)([KMG]i?B)/s,w=([\d.]+)([KMG]i?B)/s\]\[r=(\d+),w=(\d+)\s*IOPS\]")
def to_mib(v, unit):
    v=float(v)
    if unit.startswith("G"): return v*1024
    if unit.startswith("K"): return v/1024
    return v  # MiB

t=[]; rbw=[]; wbw=[]; riops=[]; wiops=[]
for m in pat.finditer(raw):
    pct=float(m.group(1))
    t.append(pct/100.0*RUNTIME_S/60.0)  # minutes
    rbw.append(to_mib(m.group(2),m.group(3)))
    wbw.append(to_mib(m.group(4),m.group(5)))
    riops.append(int(m.group(6)))
    wiops.append(int(m.group(7)))

print(f"parsed {len(t)} samples, t range {t[0]:.1f}..{t[-1]:.1f} min")

# Phase boundaries in minutes (elapsed from fio restart T0=08:09:30 UTC)
# T0=08:09:30; tput_up 08:18:40->09:03; HA 09:03:38->09:29; volmove 09:43:53; fio stop 10:05:59
def mins(hh,mm,ss): return (hh*3600+mm*60+ss - (8*3600+9*60+30))/60.0
b_tput_start = mins(8,18,40)   # 9.2
b_tput_end   = mins(9,3,0)     # 53.5
b_ha_start   = mins(9,3,38)    # 54.1
b_ha_end     = mins(9,29,0)    # 79.5
b_move_start = mins(9,43,53)   # 94.4
b_end        = mins(10,5,59)   # 116.5

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

# shading phases
phases = [
    (t[0], b_tput_start, "#d9ead3", "基线 1HA/384"),
    (b_tput_start, b_tput_end, "#fff2cc", "吞吐升级 384→1536"),
    (b_ha_start, b_ha_end, "#fce5cd", "HA 扩展 1→2"),
    (b_ha_end, b_move_start, "#d0e0e3", "2HA 稳定(未均衡)"),
    (b_move_start, b_end, "#f4cccc", "volume move aggr1→aggr2"),
]
for ax in (ax1, ax2):
    for x0,x1,c,_ in phases:
        ax.axvspan(x0, x1, color=c, alpha=0.7, zorder=0)
    for xb in [b_tput_start,b_tput_end,b_ha_start,b_ha_end,b_move_start]:
        ax.axvline(xb, color="gray", ls="--", lw=0.8, zorder=1)

# BW plot
ax1.plot(t, rbw, color="#1f77b4", lw=1.6, label="Read BW (MiB/s)")
ax1.plot(t, wbw, color="#d62728", lw=1.6, label="Write BW (MiB/s)")
ax1.set_ylabel("吞吐 Throughput (MiB/s)")
ax1.set_title("FSxN 就地升级(方法二) fio 全程性能: 吞吐 & IOPS 随各阶段变化\n(4K randrw70% iodepth32 numjobs4 + 1M seqrw iodepth16 numjobs2, direct, libaio)")
ax1.legend(loc="upper right"); ax1.grid(alpha=0.3)
ax1.annotate("基线 ~340/335", xy=(3, 340), fontsize=9)
ax1.annotate("升级/扩容谷底 ~90-150", xy=(b_move_start-40, 120), fontsize=9)

# IOPS plot
ax2.plot(t, riops, color="#2ca02c", lw=1.6, label="Read IOPS")
ax2.plot(t, wiops, color="#9467bd", lw=1.6, label="Write IOPS")
ax2.set_ylabel("IOPS"); ax2.set_xlabel("实验时间 elapsed (分钟, T0=fio 启动 08:09:30 UTC)")
ax2.legend(loc="upper right"); ax2.grid(alpha=0.3)

# phase legend
legend_patches=[Patch(color=c, label=lab) for _,_,c,lab in phases]
fig.legend(handles=legend_patches, loc="lower center", ncol=5, fontsize=9, framealpha=0.9)
plt.tight_layout(rect=[0,0.05,1,1])
plt.savefig("/tmp/storage_repo/fsxn-flexgroup-rebalance/fio_inplace_upgrade_timeline.png", dpi=110)
print("saved fio_inplace_upgrade_timeline.png")
