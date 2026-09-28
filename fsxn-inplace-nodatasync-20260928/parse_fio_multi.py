#!/usr/bin/env python3
"""Parse fio --status-interval log with multiple jobs (numjobs>1, group_reporting=0).
Each interval emits one block per job pid, each with cumulative read/write stats.
Approach:
  1. Split into (pid, wall, r_iops_cum, r_msec, w_iops_cum, w_msec) records.
  2. For each pid, sort by elapsed and diff consecutive cumulative counters to get
     per-interval instantaneous IOPS/BW.
  3. Bucket per-interval results by wall-clock second and SUM across pids.
Emits JSON list of {wall, t_sec, total_iops, total_mibps, read_iops, write_iops, read_mibps, write_mibps}.
"""
import re, sys, json
from datetime import datetime
from collections import defaultdict

def to_mib(v, unit):
    v=float(v)
    if unit.startswith('GiB'): return v*1024
    if unit.startswith('MiB'): return v
    if unit.startswith('KiB'): return v/1024
    if unit.startswith('B'):   return v/1024/1024
    return v

def iops_val(num, suf):
    v=float(num)
    if suf=='k': v*=1e3
    elif suf=='M': v*=1e6
    return v

# per pid: list of snapshots
snaps=defaultdict(list)  # pid -> [ {wall, r_iops_cum, r_mib, r_msec, w_iops_cum, w_mib, w_msec} ]
cur=None; cur_pid=None
hdr=re.compile(r'pid=(\d+):\s+(\w{3} \w{3}\s+\d+ \d+:\d+:\d+ \d+)')
re_read=re.compile(r'read:\s*IOPS=([\d.]+)([kM]?),\s*BW=[\d.]+\w+/s\s*\([^)]+\)\(([\d.]+)(\w+)/(\d+)msec\)')
re_write=re.compile(r'write:\s*IOPS=([\d.]+)([kM]?),\s*BW=[\d.]+\w+/s\s*\([^)]+\)\(([\d.]+)(\w+)/(\d+)msec\)')

def flush():
    global cur,cur_pid
    if cur is not None and cur_pid is not None and 'r_msec' in cur and 'w_msec' in cur:
        snaps[cur_pid].append(cur)
    cur=None; cur_pid=None

for ln in open(sys.argv[1]):
    h=hdr.search(ln)
    if h:
        flush()
        cur_pid=h.group(1); cur={'wall':h.group(2)}
        continue
    if cur is None: continue
    m=re_read.search(ln)
    if m and 'r_msec' not in cur:
        cur['r_iops_cum']=iops_val(m.group(1),m.group(2))
        cur['r_mib']=to_mib(m.group(3),m.group(4)); cur['r_msec']=int(m.group(5)); continue
    m=re_write.search(ln)
    if m and 'w_msec' not in cur:
        cur['w_iops_cum']=iops_val(m.group(1),m.group(2))
        cur['w_mib']=to_mib(m.group(3),m.group(4)); cur['w_msec']=int(m.group(5)); continue
flush()

# per-pid diff -> per interval instantaneous, keyed by wall
buckets=defaultdict(lambda: {'r_iops':0.0,'w_iops':0.0,'r_mib':0.0,'w_mib':0.0,'t_sec':0})
for pid, arr in snaps.items():
    arr.sort(key=lambda s: s['r_msec'])
    prev=None
    for s in arr:
        if prev is None: prev=s; continue
        dt_r=(s['r_msec']-prev['r_msec'])/1000.0
        dt_w=(s['w_msec']-prev['w_msec'])/1000.0
        if dt_r<=0 or dt_w<=0: prev=s; continue
        r_ios=(s['r_iops_cum']*s['r_msec']/1000.0 - prev['r_iops_cum']*prev['r_msec']/1000.0)/dt_r
        w_ios=(s['w_iops_cum']*s['w_msec']/1000.0 - prev['w_iops_cum']*prev['w_msec']/1000.0)/dt_w
        r_mibps=(s['r_mib']-prev['r_mib'])/dt_r
        w_mibps=(s['w_mib']-prev['w_mib'])/dt_w
        # clamp tiny negatives (rounding) to 0
        r_ios=max(r_ios,0); w_ios=max(w_ios,0); r_mibps=max(r_mibps,0); w_mibps=max(w_mibps,0)
        b=buckets[s['wall']]
        b['r_iops']+=r_ios; b['w_iops']+=w_ios; b['r_mib']+=r_mibps; b['w_mib']+=w_mibps
        b['t_sec']=max(b['t_sec'], round(s['r_msec']/1000.0))
        prev=s

def wdt(w): return datetime.strptime(w,'%a %b %d %H:%M:%S %Y')
out=[]
for wall in sorted(buckets.keys(), key=wdt):
    b=buckets[wall]
    out.append({
        'wall':wall,'t_sec':b['t_sec'],
        'read_iops':round(b['r_iops']),'write_iops':round(b['w_iops']),
        'total_iops':round(b['r_iops']+b['w_iops']),
        'read_mibps':round(b['r_mib'],1),'write_mibps':round(b['w_mib'],1),
        'total_mibps':round(b['r_mib']+b['w_mib'],1),
    })
print(json.dumps(out,indent=2))
print(f"# {len(out)} intervals, {len(snaps)} pids", file=sys.stderr)
