#!/usr/bin/env python3
"""Round2 分析: ./analyze_r2.py run1 [run2 ...]
每次运行: 端到端(最早 CreationTime -> 最晚 TerminationDate)、max Active、各 job、目标桶(们) CW 1 分钟
PutRequests/BytesUploaded(D 场景逐分钟求和+单桶)、峰值 MB/s、峰值 PUT/min、数据窗口(首个>1000 PUT/min
分钟 -> 最后一个>1000 PUT/min 分钟,含该分钟)、尾巴(数据窗口结束 -> 最后一个 TerminationDate)。
结果写 runs/<run>/analysis.json 并打印。"""
import json, glob, subprocess, sys, datetime as dt, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
def p(t): return dt.datetime.fromisoformat(t)
def cw(bucket, metric, start, end):
    r = subprocess.run(['aws','cloudwatch','get-metric-statistics','--region','us-west-2','--namespace','AWS/S3',
        '--metric-name',metric,'--dimensions',f'Name=BucketName,Value={bucket}','Name=FilterId,Value=all',
        '--start-time',start,'--end-time',end,'--period','60','--statistics','Sum','--output','json'],capture_output=True,text=True)
    if r.returncode: return {}
    return {d['Timestamp']: d['Sum'] for d in json.loads(r.stdout)['Datapoints']}
def src_failed(start,end):
    """源桶各规则 OperationsFailedReplication Sum 合计"""
    E=open('EPOCH').read().strip(); src=f's3-crr-src-{E}'
    r=subprocess.run(['aws','cloudwatch','list-metrics','--region','us-east-2','--namespace','AWS/S3','--metric-name','OperationsFailedReplication',
        '--dimensions',f'Name=SourceBucket,Value={src}','--output','json'],capture_output=True,text=True)
    tot=0; n=0
    for m in json.loads(r.stdout).get('Metrics',[]):
        r2=subprocess.run(['aws','cloudwatch','get-metric-statistics','--region','us-east-2','--namespace','AWS/S3','--metric-name','OperationsFailedReplication',
            '--dimensions',json.dumps(m['Dimensions']),'--start-time',start,'--end-time',end,'--period','300','--statistics','Sum','--output','json'],capture_output=True,text=True)
        if r2.returncode==0:
            n+=1; tot+=sum(d['Sum'] for d in json.loads(r2.stdout)['Datapoints'])
    return tot,n
out={}
for run in sys.argv[1:]:
    d=f'runs/{run}'
    jobs=[json.load(open(f))['Job'] for f in glob.glob(f'{d}/describe-*.json')]
    jobs.sort(key=lambda j:j['Description'])
    c0=min(p(j['CreationTime']) for j in jobs); t1=max(p(j['TerminationDate']) for j in jobs)
    rows=[]
    for j in jobs:
        ps=j['ProgressSummary']
        rows.append(dict(desc=j['Description'],job=j['JobId'],status=j['Status'],tasks=ps['TotalNumberOfTasks'],ok=ps['NumberOfTasksSucceeded'],
            failed=ps['NumberOfTasksFailed'],active=ps['Timers']['ElapsedTimeInActiveSeconds'],
            wall=(p(j['TerminationDate'])-p(j['CreationTime'])).total_seconds(),created=j['CreationTime'],terminated=j['TerminationDate']))
    st=(c0-dt.timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ'); en=(t1+dt.timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
    buckets=open(f'{d}/dst_buckets.txt').read().split()
    per={}; tot_put={}; tot_by={}
    for b in buckets:
        pu=cw(b,'PutRequests',st,en); by=cw(b,'BytesUploaded',st,en); per[b]={'put':pu,'bytes':by}
        for k,v in pu.items(): tot_put[k]=tot_put.get(k,0)+v
        for k,v in by.items(): tot_by[k]=tot_by.get(k,0)+v
    mins=sorted(set(tot_put)|set(tot_by))
    series=[(m,tot_put.get(m,0),tot_by.get(m,0)) for m in mins]
    big=[m for m,pu,by in series if pu>1000]
    peak_mbps=max((by/60/1e6 for _,_,by in series),default=0); peak_put=max((pu for _,pu,_ in series),default=0)
    if big:
        ws=p(big[0]); we=p(big[-1])+dt.timedelta(minutes=1)
        win=(we-ws).total_seconds(); tail=(t1-we).total_seconds()
    else: ws=we=None; win=tail=None
    per_peak={b:max((v/60/1e6 for v in per[b]['bytes'].values()),default=0) for b in buckets}
    fail,nm=src_failed((c0-dt.timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ'),en)
    a=dict(run=run,e2e=(t1-c0).total_seconds(),max_active=max(r['active'] for r in rows),jobs=rows,
        first_create=str(c0),last_term=str(t1),data_window_s=win,window_start=str(ws),window_end=str(we),tail_s=tail,
        peak_MBps=peak_mbps,peak_put_min=peak_put,per_bucket_peak_MBps=per_peak,failed_tasks=sum(r['failed'] for r in rows),
        tasks=sum(r['tasks'] for r in rows),cw_total_bytes=sum(tot_by.values()),cw_total_put=sum(tot_put.values()),
        src_failed_repl_ops=fail,src_failed_metric_series=nm,
        series=[(m,int(pu),by) for m,pu,by in series],
        per_bucket_series={b:[(m,int(per[b]['put'].get(m,0)),per[b]['bytes'].get(m,0)) for m in mins] for b in buckets})
    json.dump(a,open(f'{d}/analysis.json','w'),indent=1,default=str); out[run]=a
    print(f"== {run}: e2e={a['e2e']:.0f}s max_active={a['max_active']}s window={win}s tail={tail}s peak={peak_mbps:,.0f}MB/s "
          f"peak_put={peak_put:,.0f}/min tasks={a['tasks']} failed={a['failed_tasks']} srcFailedRepl={fail}({nm} series) "
          f"cw_bytes={a['cw_total_bytes']/1e9:.1f}GB cw_put={a['cw_total_put']:.0f}")
    for r in rows: print('   ',r['desc'],r['status'],r['tasks'],r['ok'],r['failed'],'active',r['active'],'wall',r['wall'],r['created'],r['terminated'])
    for m,pu,by in series:
        extra=''
        if len(buckets)>1: extra='  | '+' '.join(f"{per[b]['bytes'].get(m,0)/60/1e6:,.0f}" for b in buckets)
        print(f'    CW {m} {int(pu):>7} PUT {by/1e9:7.1f} GB {by/60/1e6:8,.0f} MB/s{extra}')
