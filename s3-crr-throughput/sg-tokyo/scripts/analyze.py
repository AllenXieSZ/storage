#!/usr/bin/env python3
"""汇总各场景: 作业创建->终止(TerminationDate) 墙钟、ElapsedTimeInActiveSeconds、
目标桶 CloudWatch 1 分钟 PutRequests/BytesUploaded（如已开启 request metrics）。"""
import json, glob, subprocess, sys, datetime as dt
E = open('EPOCH').read().strip()
TOTAL_BYTES = 2199023255552
TOTAL_OBJS = 131072
def p(t): return dt.datetime.fromisoformat(t)
def cw(bucket, start, end):
    out = {}
    for m in ('PutRequests', 'BytesUploaded'):
        r = subprocess.run(['aws','cloudwatch','get-metric-statistics','--region','ap-northeast-1','--namespace','AWS/S3',
            '--metric-name',m,'--dimensions',f'Name=BucketName,Value={bucket}','Name=FilterId,Value=all',
            '--start-time',start,'--end-time',end,'--period','60','--statistics','Sum','--output','json'],capture_output=True,text=True)
        dps = sorted(json.loads(r.stdout)['Datapoints'], key=lambda d: d['Timestamp']) if r.returncode==0 else []
        out[m] = [(d['Timestamp'], d['Sum']) for d in dps]
    return out
res = {}
for s in sys.argv[1:]:
    jobs = [json.load(open(f))['Job'] for f in glob.glob(f'runs/{s}/describe-*.json')]
    jobs.sort(key=lambda j: j['Description'])
    c0 = min(p(j['CreationTime']) for j in jobs); t1 = max(p(j['TerminationDate']) for j in jobs)
    rows = []
    for j in jobs:
        ps = j['ProgressSummary']; wall = (p(j['TerminationDate'])-p(j['CreationTime'])).total_seconds()
        rows.append(dict(job=j['JobId'], desc=j['Description'], tasks=ps['TotalNumberOfTasks'], ok=ps['NumberOfTasksSucceeded'],
                         failed=ps['NumberOfTasksFailed'], active=ps['Timers']['ElapsedTimeInActiveSeconds'], wall=wall,
                         created=j['CreationTime'], terminated=j['TerminationDate']))
    wall = (t1-c0).total_seconds()
    cwd = cw(f's3-crr-dst-{s}-tk-{E}', (c0-dt.timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ'), (t1+dt.timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M:%SZ'))
    res[s] = dict(jobs=rows, wall=wall, max_active=max(r['active'] for r in rows), cw=cwd,
                  MBps_wall=TOTAL_BYTES/1e6/wall, objps_wall=TOTAL_OBJS/wall)
    print(f'== {s}: wall(create->last terminate)={wall:.0f}s  max_active={res[s]["max_active"]}s  '
          f'MB/s(wall)={TOTAL_BYTES/1e6/wall:.0f}  MB/s(active)={TOTAL_BYTES/1e6/res[s]["max_active"]:.0f}  obj/s(wall)={TOTAL_OBJS/wall:.0f}')
    for r in rows: print('   ', r['desc'], r['tasks'], r['ok'], r['failed'], 'active', r['active'], 'wall', r['wall'], r['created'], r['terminated'])
    for (ts,pr),(_,by) in zip(cwd['PutRequests'], cwd['BytesUploaded']):
        print('    CW', ts, int(pr), 'PUT/min', f'{by/1e9:.1f} GB/min', f'{by/60/1e6:.0f} MB/s')
json.dump(res, open('runs/summary.json','w'), indent=1, default=str)
