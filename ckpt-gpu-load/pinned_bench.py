import os, time, threading, subprocess
import torch
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor

REGION="us-east-2"; BUCKET=os.environ.get("S3_BUCKET","YOUR_BUCKET"); KEY="ckpt-bench/ckpt_20g.safetensors"; DEV="cuda:0"
def s3c(): return boto3.client("s3", config=Config(region_name=REGION, max_pool_connections=64))
def gfree(): torch.cuda.empty_cache(); torch.cuda.synchronize()

def dl_to_pinned(conc=64, part_mb=8):
    s3=s3c(); total=s3.head_object(Bucket=BUCKET,Key=KEY)["ContentLength"]
    part=part_mb*1024*1024; nparts=(total+part-1)//part
    pinned=torch.empty(total, dtype=torch.uint8, pin_memory=True)
    mv=memoryview(pinned.numpy())
    t0=time.time()
    def fetch(i):
        st=i*part; en=min(st+part,total)-1
        d=s3.get_object(Bucket=BUCKET,Key=KEY,Range=f"bytes={st}-{en}")["Body"].read()
        mv[st:st+len(d)]=d
    with ThreadPoolExecutor(max_workers=conc) as ex: list(ex.map(fetch, range(nparts)))
    return pinned, total, time.time()-t0

def dl_to_regular(conc=64, part_mb=8):
    s3=s3c(); total=s3.head_object(Bucket=BUCKET,Key=KEY)["ContentLength"]
    part=part_mb*1024*1024; nparts=(total+part-1)//part
    reg=torch.empty(total, dtype=torch.uint8)  # 普通(非pinned) CPU tensor
    mv=memoryview(reg.numpy())
    def fetch(i):
        st=i*part; en=min(st+part,total)-1
        d=s3.get_object(Bucket=BUCKET,Key=KEY,Range=f"bytes={st}-{en}")["Body"].read()
        mv[st:st+len(d)]=d
    with ThreadPoolExecutor(max_workers=conc) as ex: list(ex.map(fetch, range(nparts)))
    return reg, total

if __name__=="__main__":
    print("=== pinned vs 普通内存 H2D 到显存 (g5.4xlarge A10G, 20GB) ===", flush=True)
    print("下载到 pinned memory...", flush=True)
    pinned,total,dt_dl=dl_to_pinned()
    print(f"(下载到pinned耗时 {dt_dl:.1f}s)", flush=True)
    for _ in range(3):
        gfree(); t0=time.time()
        gpu=torch.empty(total, dtype=torch.uint8, device=DEV)
        gpu.copy_(pinned, non_blocking=True)
        torch.cuda.synchronize()
        print(f"[pinned -> H2D]  {time.time()-t0:5.2f}s  ({total/1e9:.1f}GB, {total/1e9/(time.time()-t0):.1f} GB/s)", flush=True)
        del gpu; gfree()
    print("下载到普通内存...", flush=True)
    reg,total=dl_to_regular()
    for _ in range(3):
        gfree(); t0=time.time()
        gpu=torch.empty(total, dtype=torch.uint8, device=DEV)
        gpu.copy_(reg, non_blocking=True)
        torch.cuda.synchronize()
        print(f"[普通 -> H2D]    {time.time()-t0:5.2f}s  ({total/1e9:.1f}GB, {total/1e9/(time.time()-t0):.1f} GB/s)", flush=True)
        del gpu; gfree()
