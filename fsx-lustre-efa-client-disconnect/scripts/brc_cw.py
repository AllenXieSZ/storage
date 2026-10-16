import boto3,sys,datetime as dt
cw=boto3.client('cloudwatch',region_name='us-east-2'); FS=sys.argv[1]; t0=dt.datetime.fromisoformat(sys.argv[2]); t1=dt.datetime.fromisoformat(sys.argv[3])
ms=cw.list_metrics(Namespace='AWS/FSx',Dimensions=[{'Name':'FileSystemId','Value':FS}])['Metrics']
want={'DataWriteBytes':'Sum','FileServerDiskThroughputUtilization':'Maximum','CPUUtilization':'Maximum','NetworkThroughputUtilization':'Maximum','NetworkReceivedBytes':'Sum','ClientConnections':'Maximum'}
q=[];lab={}
for i,m in enumerate(ms):
  if m['MetricName'] not in want: continue
  d={x['Name']:x['Value'] for x in m['Dimensions']}
  if m['MetricName']=='DataWriteBytes' and len(d)>1: continue
  if m['MetricName'] in('CPUUtilization','NetworkThroughputUtilization','NetworkReceivedBytes') and 'FileServer' not in d: continue
  id='m%d'%i; lab[id]=(m['MetricName'],d.get('FileServer',d.get('StorageTargetId','fs')))
  q.append({'Id':id,'MetricStat':{'Metric':m,'Period':60,'Stat':want[m['MetricName']]}})
res=[]
for k in range(0,len(q),400):
  r=cw.get_metric_data(MetricDataQueries=q[k:k+400],StartTime=t0,EndTime=t1); res+=r['MetricDataResults']
rows={}
for r in res:
  n,s=lab[r['Id']]
  for t,v in zip(r['Timestamps'],r['Values']): rows.setdefault((n,t.strftime('%H:%M')),[]).append((s,v))
for (n,t) in sorted(rows):
  vs=rows[(n,t)]
  if n in('DataWriteBytes','NetworkReceivedBytes'): print(n,t,'sum_GBps=%.2f'%(sum(v for s,v in vs)/60/1e9),'n=%d'%len(vs), 'max_server_GBps=%.2f'%(max(v for s,v in vs)/60/1e9))
  else: print(n,t,'max=%.1f'%max(v for s,v in vs),'min=%.1f'%min(v for s,v in vs),'n=%d'%len(vs), 'top=%s'%max(vs,key=lambda x:x[1])[0])
