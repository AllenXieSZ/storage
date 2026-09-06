#!/usr/bin/env python3
"""Plot FSxN 384->768 throughput upgrade latency curve."""
import csv, datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

T0 = datetime.datetime(2026,9,6,6,34,13, tzinfo=datetime.timezone.utc)  # upgrade fired
T_DONE = datetime.datetime(2026,9,6,7,0,22, tzinfo=datetime.timezone.utc)  # COMPLETED

rows=[]
with open("tp384_results.csv") as f:
    for r in csv.DictReader(f):
        ts=datetime.datetime.strptime(r["timestamp"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        rows.append({
            "t":(ts-T0).total_seconds(),
            "op":r["op"],
            "mean":float(r["lat_mean_us"]),
            "p99":float(r["lat_p99_us"]),
            "phase":r["phase"],
        })

def series(op):
    d=[x for x in rows if x["op"]==op]
    d.sort(key=lambda x:x["t"])
    return [x["t"] for x in d],[x["mean"] for x in d],[x["p99"] for x in d]

rt,rmean,rp99=series("read")
wt,wmean,wp99=series("write")

# baseline means (phase==baseline)
def base(op):
    d=[x for x in rows if x["op"]==op and x["phase"]=="baseline"]
    return sum(x["mean"] for x in d)/len(d), sum(x["p99"] for x in d)/len(d)
rb_mean,rb_p99=base("read")
wb_mean,wb_p99=base("write")

t_done=(T_DONE-T0).total_seconds()
rp_peak=max(rp99); rp_t=rt[rp99.index(rp_peak)]
wp_peak=max(wp99); wp_t=wt[wp99.index(wp_peak)]

fig,(ax,ax2)=plt.subplots(2,1,figsize=(14,11),sharex=True,
                          gridspec_kw={"height_ratios":[1,1]})

for a in (ax,ax2):
    a.axvspan(0, t_done, color="#F58220", alpha=0.10)
    a.axvline(0, color="#F58220", ls="--", lw=1.5)
    a.axvline(t_done, color="#2E9E5B", ls="--", lw=1.5)
    a.plot(rt,rmean,color="#0067C5",lw=1.8,marker="o",ms=3,label="read clat mean")
    a.plot(rt,rp99,color="#0067C5",lw=1.2,ls=":",marker="^",ms=3,alpha=0.8,label="read clat p99")
    a.plot(wt,wmean,color="#C0392B",lw=1.8,marker="s",ms=3,label="write clat mean")
    a.plot(wt,wp99,color="#C0392B",lw=1.2,ls=":",marker="v",ms=3,alpha=0.8,label="write clat p99")
    a.axhline(rb_mean,color="#0067C5",lw=1,ls="-.",alpha=0.5)
    a.axhline(wb_mean,color="#C0392B",lw=1,ls="-.",alpha=0.5)
    a.grid(True,alpha=0.3)

# --- top panel: full range (shows spikes) ---
ax.annotate(f"read p99 peak {rp_peak:.0f}us (@t={rp_t:.0f}s, ~4min in)",(rp_t,rp_peak),
            textcoords="offset points",xytext=(30,-6),color="#0067C5",fontsize=9,
            arrowprops=dict(arrowstyle="->",color="#0067C5"))
ax.annotate(f"write mean spike {max(wmean):.0f}us (@t=178s, ~3min in)",(wt[wmean.index(max(wmean))],max(wmean)),
            textcoords="offset points",xytext=(40,10),color="#C0392B",fontsize=9,
            arrowprops=dict(arrowstyle="->",color="#C0392B"))
ax.text(t_done/2, 0.96*ax.get_ylim()[1] if ax.get_ylim()[1]>0 else 20000,
        "THROUGHPUT UPGRADE 384→768 IN PROGRESS", ha="center", va="top",
        fontsize=10, color="#8a4500", weight="bold")
ax.set_ylabel("Latency (us, clat) — full range")
ax.set_title("FSxN Gen2 SINGLE_AZ_2 (1 HA pair) — Throughput 384→768 MBps: NFSv3 IO latency\n"
             "fio bs=16k sync direct=1 numjobs=1 iodepth=1 runtime=8s (randread+randwrite). "
             f"Upgrade window 0–{int(t_done)}s (~{t_done/60:.1f} min)")
ax.legend(loc="upper right",fontsize=8,ncol=2)

# --- bottom panel: zoomed (0-1500us) to show steady-state elevation ---
ax2.set_ylim(0,1500)
ax2.set_ylabel("Latency (us, clat) — zoom 0–1500us")
ax2.set_xlabel("Time relative to upgrade start T0 (seconds)  —  baseline shown at t<0")
ax2.text(rb_mean and -120, rb_mean+15, f"read baseline mean {rb_mean:.0f}us", color="#0067C5", fontsize=7)
ax2.text(-120, wb_mean+15, f"write baseline mean {wb_mean:.0f}us", color="#C0392B", fontsize=7)
ax2.legend(loc="upper right",fontsize=8,ncol=2)

fig.tight_layout()
fig.savefig("latency_curve_384to768.png",dpi=130)
print("saved latency_curve_384to768.png")
print(f"read baseline mean={rb_mean:.1f}us p99={rb_p99:.1f}us | read p99 peak={rp_peak:.0f}us @ t={rp_t:.0f}s")
print(f"write baseline mean={wb_mean:.1f}us p99={wb_p99:.1f}us | write p99 peak={wp_peak:.0f}us @ t={wp_t:.0f}s")
print(f"read mean peak={max(rmean):.0f}us  write mean peak={max(wmean):.0f}us")
print(f"upgrade duration={t_done:.0f}s ({t_done/60:.1f} min)")
