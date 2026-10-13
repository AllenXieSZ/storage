#!/bin/bash
# t1check.sh <bucket> <tag> <done_epoch> : 在管理机运行（需当前目录有 t1_<tag>.md5）。每 10 秒列 S3 work/<tag>/，直到对象集合、size、抽样 md5(ETag) 全部对上
B=$1; T=$2; DONE=$3
python3 - "$B" "$T" "$DONE" <<'PY'
import sys,time,subprocess,json,hashlib
B,T,DONE=sys.argv[1],sys.argv[2],float(sys.argv[3])
exp=set(f"f{i:04d}" for i in range(1,5001))-set(f"f{i:04d}" for i in range(1001,1201))-set(f"f{i:04d}" for i in range(2001,2201))
exp|=set(f"r{i:04d}" for i in range(1001,1201))
md5=dict(l.split()[::-1] for l in open(f"t1_{T}.md5"))
import boto3; s3=boto3.client("s3",region_name="us-east-2")
while True:
    keys={}
    for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B,Prefix=f"work/{T}/"):
        for o in pg.get("Contents",[]):
            if o["Key"].endswith("/"): continue          # 目录标记对象 work/<tag>/
            keys[o["Key"].split("/")[-1]]=(o["Size"],o["ETag"].strip('"'))
    names=set(keys); miss=exp-names; extra=names-exp
    okmd5=sum(1 for n,h in md5.items() if n in keys and keys[n][1]==h)
    badsize=sum(1 for n in names&exp if keys[n][0]!=1048576)
    el=time.time()-DONE
    print(f"t+{el:6.0f}s objs={len(keys)} missing={len(miss)} extra={len(extra)} md5ok={okmd5}/{len(md5)} badsize={badsize}",flush=True)
    if not miss and not extra and okmd5==len(md5) and not badsize:
        print(f"MATCH after {el:.0f}s from ops done"); break
    if el>3600: print("TIMEOUT", sorted(miss)[:5], sorted(extra)[:5]); break
    time.sleep(10)
PY
