#!/usr/bin/env python3
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = [r for r in csv.reader(open("/home/ubuntu/.openclaw/workspace/dra_autoimport_age.csv"))
        if r and r[0] != "wallclock_utc"]
el = []
age = []
for r in rows:
    if r[3] == "":
        continue
    el.append(int(r[1]) / 60.0)   # minutes
    age.append(float(r[3]))

fig, ax = plt.subplots(figsize=(11, 5.5))
ax.plot(el, age, color="#0067C5", lw=1.8, marker="o", ms=2.5, label="AgeOfOldestQueuedMessage (Publisher=AutoImport)")
ax.axhline(60, color="#F58220", ls="--", lw=1, alpha=0.7)
ax.text(0.5, 62, "steady-state plateau ~60s", color="#F58220", fontsize=9)

# upload window: start ~ elapsed 0 (07:48:05 start), DONE at 08:18:26.
# collector t0 = 07:48:05. upload DONE 08:18:26 -> ~30.3 min
ax.axvspan(0, 30.3, color="#2E9E5B", alpha=0.08)
ax.text(15, 50, "upload running (1M x 10KB, ~542 obj/s)", ha="center", color="#2E9E5B", fontsize=9)
ax.axvline(30.3, color="#888", ls=":", lw=1)
ax.text(30.5, 40, "upload stops\n08:18:26", color="#555", fontsize=8, va="top")

ax.set_xlabel("Elapsed (minutes)")
ax.set_ylabel("AgeOfOldestQueuedMessage (seconds)")
ax.set_title("FSx Lustre DRA AutoImport queue backlog\n(S3 PUT 1M x 10KB objects -> AutoImport event queue, 10s sampling)", fontsize=11)
ax.set_ylim(-3, 70)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper right", fontsize=8)
plt.tight_layout()
plt.savefig("/home/ubuntu/.openclaw/workspace/dra_autoimport_age_plot.png", dpi=120)
print("saved dra_autoimport_age_plot.png; points:", len(el), "max_age:", max(age))
