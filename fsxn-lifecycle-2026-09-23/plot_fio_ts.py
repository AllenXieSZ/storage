#!/usr/bin/env python3
"""Plot FSxN lifecycle fio timeseries with phase annotations."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
matplotlib.rcParams['font.family'] = 'Noto Sans CJK JP'
matplotlib.rcParams['axes.unicode_minus'] = False
import json
from datetime import datetime

data = json.load(open('fio_ts_parsed.json'))
FIO_START = datetime.strptime('Wed Sep 23 10:14:22 2026', '%a %b %d %H:%M:%S %Y')

def w2m(w):
    dt = datetime.strptime(w, '%a %b %d %H:%M:%S %Y')
    return (dt - FIO_START).total_seconds()/60.0

x = [w2m(d['wall']) for d in data]
bw = [d['total_mibps'] for d in data]
iops = [d['total_iops'] for d in data]

def mins(hms):
    dt = datetime.strptime('Wed Sep 23 '+hms+' 2026', '%a %b %d %H:%M:%S %Y')
    return (dt - FIO_START).total_seconds()/60.0

# phase boundary vertical markers (start of each phase)
phases = [
    ('baseline 1HA/1536',      mins('10:14:22'), '#2E9E5B'),
    ('HA expand 1->2',          mins('10:19:53'), '#C0392B'),
    ('convert->FlexGroup',      mins('10:31:04'), '#6A5ACD'),
    ('expand ->16 constituent', mins('10:33:15'), '#0067C5'),
    ('shrink 4096->2048 start', mins('10:35:30'), '#F58220'),
    ('shrink PAUSED+rebalance', mins('12:44:00'), '#8E44AD'),
    ('fio reduce load',         mins('13:05:03'), '#16A085'),
    ('fio stop (shrink done)',  mins('13:16:59'), '#000000'),
]

fig, ax1 = plt.subplots(figsize=(15,7.5))
ax1.plot(x, bw, '-', color='#0067C5', lw=1.3, label='Throughput (MiB/s, read+write)')
ax1.set_xlabel('Elapsed minutes from fio start (10:14:22 UTC)', fontsize=12)
ax1.set_ylabel('Throughput MiB/s', color='#0067C5', fontsize=12)
ax1.tick_params(axis='y', labelcolor='#0067C5')
ax1.set_ylim(0, max(bw)*1.15)

ax2 = ax1.twinx()
ax2.plot(x, iops, '-', color='#F58220', lw=0.9, alpha=0.6, label='IOPS (read+write)')
ax2.set_ylabel('IOPS', color='#F58220', fontsize=12)
ax2.tick_params(axis='y', labelcolor='#F58220')
ax2.set_ylim(0, max(iops)*1.15)

xmax = max(x)
for i,(name,m,col) in enumerate(phases):
    if m > xmax+2: continue
    ax1.axvline(m, color=col, ls='--', lw=1.5, alpha=0.85)
    ax1.text(m+1, ax1.get_ylim()[1]*(0.98-0.085*(i%4)), name, color=col,
             fontsize=8.5, fontweight='bold', va='top', rotation=0)

ax1.set_title('FSxN Gen2 全生命周期 — fio 1M randrw 时间序列\n'
              'baseline(1HA/1536) -> 扩2HA -> FlexVol转FlexGroup -> expand到16 constituent -> 缩容4096→2048GiB',
              fontsize=13, fontweight='bold')
ax1.grid(True, alpha=0.25)
l1,lb1 = ax1.get_legend_handles_labels(); l2,lb2 = ax2.get_legend_handles_labels()
ax1.legend(l1+l2, lb1+lb2, loc='lower left', fontsize=10)
plt.tight_layout()
plt.savefig('lifecycle_fio_timeseries.png', dpi=130)
print('saved lifecycle_fio_timeseries.png; intervals=%d'%len(data))
