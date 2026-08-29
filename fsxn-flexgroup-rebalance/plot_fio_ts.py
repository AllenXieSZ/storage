#!/usr/bin/env python3
"""Plot fio timeseries (per-interval throughput MB/s + IOPS) with phase annotations.
Reads parsed JSON from parse_fio_ts.py output on stdin or arg."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json, sys
from datetime import datetime

data = json.load(open(sys.argv[1]))
# x = elapsed minutes
x = [d['t_sec']/60.0 for d in data]
tot_bw = [d['total_mibps'] for d in data]
tot_iops = [d['total_iops'] for d in data]

# fio started 01:19:19 (first snapshot pid line ~01:20:19 is t=60). Use wall clock to map phases.
# Convert wall strings to elapsed-from-start.
def wall_to_dt(w):
    # "Sat Aug 29 01:20:19 2026"
    return datetime.strptime(w, '%a %b %d %H:%M:%S %Y')
start = None
for d in data:
    try:
        dt = wall_to_dt(d['wall']); 
        if start is None: start = dt
    except: pass

# phase boundaries in UTC wall clock -> minutes from fio start (~01:19:19)
FIO_START = datetime.strptime('Sat Aug 29 01:19:19 2026', '%a %b %d %H:%M:%S %Y')
def mins(hms):
    dt = datetime.strptime('Sat Aug 29 '+hms+' 2026', '%a %b %d %H:%M:%S %Y')
    return (dt-FIO_START).total_seconds()/60.0

phases = [
    ('baseline\n1HA FlexVol', mins('01:19:19'), '#2E9E5B'),
    ('throughput\n384→1536', mins('01:22:03'), '#F58220'),
    ('HA expand\n1→2 +storage', mins('01:58:44'), '#C0392B'),
    ('convert→FlexGroup\n+expand', mins('02:08:39'), '#6A5ACD'),
    ('write 100/300/500\n1GiB files', mins('02:12:04'), '#0067C5'),
    ('idle (post-write)', mins('02:21:00'), '#5A6B82'),
]

fig, ax1 = plt.subplots(figsize=(14,7))
ax1.plot(x, tot_bw, '-', color='#0067C5', lw=1.6, label='Throughput (MiB/s)')
ax1.set_xlabel('Elapsed time (minutes from fio start ~01:19 UTC)', fontsize=12)
ax1.set_ylabel('Throughput MiB/s (read+write)', color='#0067C5', fontsize=12)
ax1.tick_params(axis='y', labelcolor='#0067C5')
ax1.set_ylim(0, max(tot_bw)*1.15 if tot_bw else 100)

ax2 = ax1.twinx()
ax2.plot(x, tot_iops, '-', color='#F58220', lw=1.2, alpha=0.75, label='IOPS (read+write)')
ax2.set_ylabel('IOPS (read+write)', color='#F58220', fontsize=12)
ax2.tick_params(axis='y', labelcolor='#F58220')
ax2.set_ylim(0, max(tot_iops)*1.15 if tot_iops else 1000)

xmax = max(x) if x else 200
for i,(name, m, col) in enumerate(phases):
    if m > xmax: continue
    ax1.axvline(m, color=col, ls='--', lw=1.4, alpha=0.8)
    ax1.text(m+0.5, ax1.get_ylim()[1]*(0.97-0.11*(i%3)), name, color=col, fontsize=8.5, fontweight='bold', va='top')

ax1.set_title('FSxN FlexGroup Direction B — fio timeseries (4K randrw + 1M seqrw)\nfull chain: baseline → throughput upgrade → HA expand → FlexVol→FlexGroup convert+expand → multi-file write',
              fontsize=12.5, fontweight='bold')
ax1.grid(True, alpha=0.25)
l1,lb1 = ax1.get_legend_handles_labels(); l2,lb2 = ax2.get_legend_handles_labels()
ax1.legend(l1+l2, lb1+lb2, loc='upper right', fontsize=10)
plt.tight_layout()
plt.savefig('flexgroup_fio_timeseries.png', dpi=130)
print('saved flexgroup_fio_timeseries.png ; intervals=%d'%len(data))
