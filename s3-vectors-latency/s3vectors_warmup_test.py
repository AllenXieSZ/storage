#!/usr/bin/env python3
"""
干净对照：每次运行只测一个 index，是"进程内首次插入"。
用法：
  python3 s3vectors_warmup_test.py baseline <bucket>   # 不 warmup，直接插5批
  python3 s3vectors_warmup_test.py warmup   <bucket>   # 先warmup再插5批
  python3 s3vectors_warmup_test.py --mkbucket          # 建bucket并打印名字
  python3 s3vectors_warmup_test.py --cleanup <bucket>
"""
import time, uuid, sys
import numpy as np
import boto3

REGION="us-east-2"; DIM=1024; BATCH=500; BATCHES=5
CATS=["tech","finance","sports","music","travel"]
s3v=boto3.client("s3vectors", region_name=REGION)

def ms(dt): return round(dt*1000,2)
def rv():
    v=np.random.randn(DIM).astype(np.float32); return (v/np.linalg.norm(v)).tolist()
def mkbatch(off):
    return [{"key":f"v-{off+j}","data":{"float32":rv()},"metadata":{"category":CATS[(off+j)%5]}} for j in range(BATCH)]

def run(mode, bucket):
    idx=f"idx-{mode}-"+uuid.uuid4().hex[:6]
    s3v.create_index(vectorBucketName=bucket,indexName=idx,dataType="float32",dimension=DIM,distanceMetric="cosine")
    time.sleep(3)
    if mode=="warmup":
        t0=time.perf_counter()
        try: s3v.query_vectors(vectorBucketName=bucket,indexName=idx,topK=1,queryVector={"float32":rv()})
        except Exception as e: pass
        print(f"[{mode}] warmup query: {ms(time.perf_counter()-t0)} ms  (走完 TCP/TLS+botocore懒加载)")
    lat=[]
    for b in range(BATCHES):
        vs=mkbatch(b*BATCH)
        t0=time.perf_counter(); s3v.put_vectors(vectorBucketName=bucket,indexName=idx,vectors=vs)
        dt=ms(time.perf_counter()-t0); lat.append(dt)
        print(f"[{mode}] batch {b+1}/{BATCHES}: {dt:>8} ms")
    print(f"[{mode}] FIRST={lat[0]}  warm_avg(2-5)={round(sum(lat[1:])/4,2)}  FIRST-warm={round(lat[0]-sum(lat[1:])/4,2)} ms")

if __name__=="__main__":
    a=sys.argv
    if a[1]=="--mkbucket":
        b="weiwei-s3v-warmup-"+uuid.uuid4().hex[:8]; s3v.create_vector_bucket(vectorBucketName=b); time.sleep(2); print(b)
    elif a[1]=="--cleanup":
        for ix in s3v.list_indexes(vectorBucketName=a[2]).get("indexes",[]):
            s3v.delete_index(vectorBucketName=a[2],indexName=ix["indexName"]); print("del idx",ix["indexName"])
        time.sleep(2); s3v.delete_vector_bucket(vectorBucketName=a[2]); print("del bucket",a[2])
    else:
        run(a[1], a[2])
