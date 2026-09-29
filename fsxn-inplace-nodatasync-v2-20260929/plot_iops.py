#!/usr/bin/env python3
"""Plot fio IOPS timeseries with vertical operation-start markers (no baseline).
X axis = elapsed minutes from fio start; single Total IOPS curve; annotated event lines.
v2 order: expand HA -> convert FlexGroup -> expand constituent x16 -> volume move -> resize."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json, sys
from datetime import datetime

data=json.load(open(sys.argv[1]))
def wdt(w): return datetime.strptime(w,'%a %b %d %H:%M:%S %Y')

FIO_START=datetime.strptime('Tue Sep 29 02:04:03 2026','%a %b %d %H:%M:%S %Y')
def mins_from(w): return (wdt(w)-FIO_START).total_seconds()/60.0
def m(hms): return (datetime.strptime('Tue Sep 29 '+hms+' 2026','%a %b %d %H:%M:%S %Y')-FIO_START).total_seconds()/60.0

x=[mins_from(d['wall']) for d in data]
iops=[d['total_iops'] for d in data]

# events (UTC) -> label, color, text_slot
events=[
    ('HA expand 1\u21922\nstart', m('02:06:33'), '#C0392B'),
    ('HA expand end', m('02:17:46'), '#C0392B'),
    ('FlexVol\u2192FlexGroup\nconvert', m('02:18:10'), '#6A5ACD'),
    ('expand constituent\n\u00d716 start', m('02:19:47'), '#2E9E5B'),
    ('expand end', m('02:21:25'), '#2E9E5B'),
    ('volume move\nstart (aggr1\u2192aggr2)', m('02:22:01'), '#0067C5'),
    ('volume move\nend (cutover)', m('02:42:27'), '#0067C5'),
    ('resize \u2192 1TB', m('02:43:16'), '#F58220'),
]

fig, ax=plt.subplots(figsize=(15,7.5))
ax.plot(x, iops, '-', color='#0067C5', lw=1.6, label='Total IOPS (4K randrw + 1M seqrw, 6 procs)')
ax.set_xlabel('Elapsed time (minutes from fio start @ 02:04:03 UTC)', fontsize=12)
ax.set_ylabel('IOPS (read + write)', fontsize=12)
ymax=max(iops)*1.20 if iops else 1000
ax.set_ylim(0, ymax)
ax.set_xlim(0, max(x)*1.02 if x else 200)

for i,(name,mm,col) in enumerate(events):
    if mm<0: continue
    ax.axvline(mm, color=col, ls='--', lw=1.5, alpha=0.85)
    ax.text(mm+0.3, ymax*(0.985-0.115*(i%4)), name, color=col, fontsize=8.5, fontweight='bold', va='top')

ax.set_title('FSxN in-place upgrade (no DataSync) v2 \u2014 IOPS over time\n'
             '1536 MB/s\u00b71HA / 2TB Gen2 \u2192 expand HA 2 \u2192 convert FlexGroup \u2192 expand constituent \u00d716 \u2192 volume move \u2192 resize back 1TB',
             fontsize=12.5, fontweight='bold')
ax.grid(True, alpha=0.25)
ax.legend(loc='upper right', fontsize=10)
plt.tight_layout()
plt.savefig('iops_timeseries.png', dpi=135)
print('saved iops_timeseries.png ; intervals=%d ; max_iops=%d'%(len(data),max(iops)))
