#!/usr/bin/env python3
"""Parse fio --status-interval log (cumulative stats) into per-INTERVAL throughput/IOPS.
fio prints cumulative averages each snapshot; we diff consecutive cumulative
data-transferred + elapsed-msec to recover true instantaneous per-interval values.
Emits JSON list of {t_sec, wall, read_mibps, write_mibps, total_mibps, read_iops, write_iops, total_iops}.
"""
import re, sys, json
from datetime import datetime

def to_mib(v, unit):
    v = float(v)
    if unit.startswith('GiB'): return v*1024
    if unit.startswith('MiB'): return v
    if unit.startswith('KiB'): return v/1024
    if unit.startswith('B'):   return v/1024/1024
    return v

def parse(path):
    snaps = []  # each: {wall, r_bytes_mib, r_msec, r_ios, w_bytes_mib, w_msec, w_ios}
    wall = None
    cur = None
    with open(path) as f:
        for ln in f.readlines():
            h = re.search(r'pid=\d+:\s+(\w{3} \w{3}\s+\d+ \d+:\d+:\d+ \d+)', ln)
            if h:
                if cur and 'r_mib' in cur and 'w_mib' in cur:
                    snaps.append(cur)
                cur = {'wall': h.group(1)}
                continue
            if cur is None:
                continue
            m = re.search(r'read:\s*IOPS=([\d.]+)([kM]?),\s*BW=[\d.]+\w+/s\s*\([^)]+\)\(([\d.]+)(\w+)/(\d+)msec\)', ln)
            if m:
                iops=float(m.group(1)); 
                if m.group(2)=='k': iops*=1e3
                elif m.group(2)=='M': iops*=1e6
                cur['r_mib']=to_mib(m.group(3),m.group(4)); cur['r_msec']=int(m.group(5)); cur['r_iops_cum']=iops
                continue
            m = re.search(r'write:\s*IOPS=([\d.]+)([kM]?),\s*BW=[\d.]+\w+/s\s*\([^)]+\)\(([\d.]+)(\w+)/(\d+)msec\)', ln)
            if m:
                iops=float(m.group(1))
                if m.group(2)=='k': iops*=1e3
                elif m.group(2)=='M': iops*=1e6
                cur['w_mib']=to_mib(m.group(3),m.group(4)); cur['w_msec']=int(m.group(5)); cur['w_iops_cum']=iops
                continue
    if cur and 'r_mib' in cur and 'w_mib' in cur:
        snaps.append(cur)

    out=[]
    prev=None
    for s in snaps:
        if prev is None:
            prev=s; continue
        dt_r=(s['r_msec']-prev['r_msec'])/1000.0
        dt_w=(s['w_msec']-prev['w_msec'])/1000.0
        if dt_r<=0 or dt_w<=0:
            prev=s; continue
        r_mibps=(s['r_mib']-prev['r_mib'])/dt_r
        w_mibps=(s['w_mib']-prev['w_mib'])/dt_w
        # iops per interval: cumulative iops*cum_sec diff
        r_ios=(s['r_iops_cum']*s['r_msec']/1000.0 - prev['r_iops_cum']*prev['r_msec']/1000.0)/dt_r
        w_ios=(s['w_iops_cum']*s['w_msec']/1000.0 - prev['w_iops_cum']*prev['w_msec']/1000.0)/dt_w
        out.append({
            'wall': s['wall'],
            't_sec': round(s['r_msec']/1000.0),
            'read_mibps': round(r_mibps,1), 'write_mibps': round(w_mibps,1),
            'total_mibps': round(r_mibps+w_mibps,1),
            'read_iops': round(r_ios), 'write_iops': round(w_ios),
            'total_iops': round(r_ios+w_ios),
        })
        prev=s
    return out

if __name__=='__main__':
    o=parse(sys.argv[1])
    print(json.dumps(o,indent=2))
    print(f"# {len(o)} intervals", file=sys.stderr)
