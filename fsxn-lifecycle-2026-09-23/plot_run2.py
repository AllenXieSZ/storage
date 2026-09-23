#!/usr/bin/env python3
"""Plot RUN2 fio timeseries (fio full-load throughout shrink)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
matplotlib.rcParams['font.family'] = 'Noto Sans CJK JP'
matplotlib.rcParams['axes.unicode_minus'] = False
import json
from datetime import datetime

data = json.load(open('fio_run2_parsed.json'))
FIO_START = datetime.strptime('Wed Sep 23 13:32:22 2026', '%a %b %d %H:%M:%S %Y')
def w2m(w):
    return (datetime.strptime(w,'%a %b %d %H:%M:%S %Y')-FIO_START).total_seconds()/60.0
x=[w2m(d['wall']) for d in data]
bw=[d['total_mibps'] for d in data]
iops=[d['total_iops'] for d in data]

def mm(hms):
    return (datetime.strptime('Wed Sep 23 '+hms+' 2026','%a %b %d %H:%M:%S %Y')-FIO_START).total_seconds()/60.0
phases=[
 ('fio 满载 baseline',        mm('13:32:22'), '#2E9E5B'),
 ('缩容 4096->2048 触发',      mm('13:37:09'), '#F58220'),
 ('缩容 PAUSED @63%',          mm('13:57:00'), '#C0392B'),
 ('自动 resume @67%',          mm('14:26:43'), '#6A5ACD'),
 ('fio 结束(缩容仍继续)',      mm('14:25:47'), '#000000'),
]
fig,ax1=plt.subplots(figsize=(14,7))
ax1.plot(x,bw,'-',color='#0067C5',lw=1.4,label='Throughput (MiB/s, read+write)')
ax1.set_xlabel('Elapsed minutes from fio start (13:32:22 UTC)',fontsize=12)
ax1.set_ylabel('Throughput MiB/s',color='#0067C5',fontsize=12)
ax1.tick_params(axis='y',labelcolor='#0067C5'); ax1.set_ylim(0,max(bw)*1.15)
ax2=ax1.twinx()
ax2.plot(x,iops,'-',color='#F58220',lw=0.9,alpha=0.6,label='IOPS (read+write)')
ax2.set_ylabel('IOPS',color='#F58220',fontsize=12)
ax2.tick_params(axis='y',labelcolor='#F58220'); ax2.set_ylim(0,max(iops)*1.15)
xmax=max(x)
for i,(name,m,col) in enumerate(phases):
    if m>xmax+2: continue
    ax1.axvline(m,color=col,ls='--',lw=1.5,alpha=0.85)
    ax1.text(m+0.4,ax1.get_ylim()[1]*(0.98-0.09*(i%4)),name,color=col,fontsize=9,fontweight='bold',va='top')
ax1.set_title('FSxN Gen2 缩容 RUN2 — fio 满载全程不停 (真实生产负载)\n'
              '缩容4096→2048在fio满载下靠 PAUSED↔自动retry 自己完成, 无需人工干预',
              fontsize=13,fontweight='bold')
ax1.grid(True,alpha=0.25)
l1,lb1=ax1.get_legend_handles_labels(); l2,lb2=ax2.get_legend_handles_labels()
ax1.legend(l1+l2,lb1+lb2,loc='lower left',fontsize=10)
plt.tight_layout(); plt.savefig('run2_fio_timeseries.png',dpi=130)
print('saved run2_fio_timeseries.png; intervals=%d'%len(data))
