#!/usr/bin/env python3
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = [r for r in csv.reader(open("/home/ubuntu/.openclaw/workspace/dra_autoexport_age_merged.csv"))
        if r and r[0] != "wallclock_utc"]
mins = [float(r[1]) for r in rows]
age = [float(r[2]) for r in rows]

fig, ax = plt.subplots(figsize=(12, 5.5))
ax.plot(mins, age, color="#F58220", lw=1.6, label="AgeOfOldestQueuedMessage (Publisher=AutoExport)")

peak = max(age)
peak_x = mins[age.index(peak)]
ax.annotate(f"peak {peak:.0f}s ({peak/60:.1f} min)", xy=(peak_x, peak),
            xytext=(peak_x-18, peak-500), fontsize=9, color="#c0392b",
            arrowprops=dict(arrowstyle="->", color="#c0392b"))

# create window: files created in first ~3.75 min (225s) at 4441/s
ax.axvspan(0, 3.75, color="#2E9E5B", alpha=0.10)
ax.text(1.9, peak*0.15, "Lustre create\n1M x 10KB\n~4441 files/s\n(225s)", ha="center", color="#2E9E5B", fontsize=8)

ax.set_xlabel("Elapsed (minutes)")
ax.set_ylabel("AgeOfOldestQueuedMessage (seconds)")
ax.set_title("FSx Lustre DRA AutoExport queue backlog\n(create 1M x 10KB in Lustre -> export to S3; production 4441/s >> export ~213/s)", fontsize=11)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper right", fontsize=9)
ax.set_ylim(-100, peak*1.1)
plt.tight_layout()
plt.savefig("/home/ubuntu/.openclaw/workspace/dra_autoexport_age_plot.png", dpi=120)
print("saved dra_autoexport_age_plot.png points:", len(mins), "peak:", peak)
