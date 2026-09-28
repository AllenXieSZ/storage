#!/usr/bin/env python3
"""Plot fio IOPS timeseries with vertical operation-start markers (no baseline concept).
X axis = elapsed minutes from fio start; single IOPS curve; annotated event lines."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json, sys
from datetime import datetime

data=json.load(open(sys.argv[1]))
def wdt(w): return datetime.strptime(w,'%a %b %d %H:%M:%S %Y')

FIO_START=datetime.strptime('Mon Sep 28 16:56:32 2026','%a %b %d %H:%M:%S %Y')
def mins_from(w): return (wdt(w)-FIO_START).total_seconds()/60.0

x=[mins_from(d['wall']) for d in data]
iops=[d['total_iops'] for d in data]

# events (UTC) -> label, color
def m(hms): return (datetime.strptime('Mon Sep 28 '+hms+' 2026','%a %b %d %H:%M:%S %Y')-FIO_START).total_seconds()/60.0
events=[
    ('FlexVol\u2192FlexGroup\nconvert start', m('16:58:36'), '#6A5ACD'),
    ('HA expand 1\u21922\nstart', m('16:59:33'), '#C0392B'),
    ('HA expand end', m('17:11:24'), '#C0392B'),
    ('volume move\nstart (aggr1\u2192aggr2)', m('17:12:13'), '#0067C5'),
    ('volume move\nend', m('17:27:47'), '#0067C5'),
    ('expand constituent\n\u00d716 start', m('17:34:37'), '#2E9E5B'),
    ('expand end', m('17:42:34'), '#2E9E5B'),
    ('resize \u2192 1TB\nstart', m('17:43:37'), '#F58220'),
]

fig, ax=plt.subplots(figsize=(15,7.5))
ax.plot(x, iops, '-', color='#0067C5', lw=1.7, label='Total IOPS (4K randrw + 1M seqrw, 6 procs)')
ax.set_xlabel('Elapsed time (minutes from fio start @ 16:56:32 UTC)', fontsize=12)
ax.set_ylabel('IOPS (read + write)', fontsize=12)
ymax=max(iops)*1.18 if iops else 1000
ax.set_ylim(0, ymax)
ax.set_xlim(0, max(x)*1.02 if x else 200)

for i,(name,mm,col) in enumerate(events):
    if mm<0: continue
    ax.axvline(mm, color=col, ls='--', lw=1.5, alpha=0.85)
    ax.text(mm+0.4, ymax*(0.97-0.115*(i%4)), name, color=col, fontsize=9, fontweight='bold', va='top')

ax.set_title('FSxN in-place upgrade (no DataSync) \u2014 IOPS over time\n'
             '1536 MB/s\u00b7HA / 2TB Gen2 \u2192 convert FlexGroup \u2192 expand HA \u2192 volume move \u2192 expand constituent \u00d716 \u2192 resize back',
             fontsize=13, fontweight='bold')
ax.grid(True, alpha=0.25)
ax.legend(loc='upper right', fontsize=10)
plt.tight_layout()
plt.savefig('iops_timeseries.png', dpi=135)
print('saved iops_timeseries.png ; intervals=%d'%len(data))
