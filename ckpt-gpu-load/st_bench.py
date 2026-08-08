import io, os, time, threading, subprocess
import torch
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor

REGION="us-east-2"; BUCKET=os.environ.get("S3_BUCKET","YOUR_BUCKET")
KEY_PT="ckpt-bench/ckpt_20g.pt"
KEY_ST="ckpt-bench/ckpt_20g.safetensors"
DEV="cuda:0"

def drop(): subprocess.run(["sh","-c","sync; echo 3 > /proc/sys/vm/drop_caches"])
def s3c(): return boto3.client("s3", config=Config(region_name=REGION, max_pool_connections=64))
def gfree(): torch.cuda.empty_cache(); torch.cuda.synchronize()

def download_to_file(key, local, conc=64, part_mb=8):
    s3=s3c(); total=s3.head_object(Bucket=BUCKET,Key=key)["ContentLength"]
    part=part_mb*1024*1024; nparts=(total+part-1)//part
    try: os.remove(local)
    except: pass
    with open(local,"wb") as f: f.truncate(total)
    def fetch(i):
        st=i*part; en=min(st+part,total)-1
        r=s3.get_object(Bucket=BUCKET,Key=key,Range=f"bytes={st}-{en}")
        d=r["Body"].read()
        with open(local,"r+b") as f: f.seek(st); f.write(d)
    with ThreadPoolExecutor(max_workers=conc) as ex: list(ex.map(fetch, range(nparts)))
    os.sync(); return total

# --- C1: safetensors mmap 直载 (从已在本地的文件, 只测加载到显存这步) ---
def st_load_only():
    from safetensors.torch import load_file
    drop(); gfree()
    t0=time.time()
    sd=load_file("/nvme/ckpt_20g.safetensors", device=DEV)  # mmap零拷贝直接到GPU
    torch.cuda.synchronize(); t1=time.time()
    nb=sum(v.numel()*v.element_size() for v in sd.values())
    print(f"[C1 safetensors mmap 直载(本地已有)] 加载到显存={t1-t0:5.1f}s  {nb/1e9:.1f}GB", flush=True)
    del sd; gfree()

# --- C2: torch.load 从本地文件 (对照, 只测加载这步) ---
def pt_load_only():
    drop(); gfree()
    t0=time.time()
    sd=torch.load("/nvme/ckpt_20g.pt", map_location=DEV, weights_only=True)
    torch.cuda.synchronize(); t1=time.time()
    nb=sum(v.numel()*v.element_size() for v in sd.values())
    print(f"[C2 torch.load 从本地文件]        加载到显存={t1-t0:5.1f}s  {nb/1e9:.1f}GB", flush=True)
    del sd; gfree()

# --- 全链路: S3 -> NVMe -> safetensors mmap -> 显存 ---
def full_st():
    from safetensors.torch import load_file
    drop(); gfree()
    t0=time.time()
    download_to_file(KEY_ST, "/nvme/dl.safetensors")
    t_dl=time.time()
    drop()
    sd=load_file("/nvme/dl.safetensors", device=DEV)
    torch.cuda.synchronize(); t1=time.time()
    print(f"[全链路 S3->NVMe->safetensors->GPU] 下载={t_dl-t0:5.1f}s 加载显存={t1-t_dl:5.1f}s 【总={t1-t0:5.1f}s】", flush=True)
    del sd; gfree()

if __name__=="__main__":
    print("=== safetensors mmap vs torch.load 加载到显存 (g5.4xlarge A10G, 20GB) ===", flush=True)
    print("--- 纯加载对比(文件已在本地NVMe, drop_caches后, 各2轮) ---", flush=True)
    for _ in range(2):
        st_load_only()
        pt_load_only()
    print("--- 全链路 S3->NVMe->safetensors mmap->显存 ---", flush=True)
    full_st()
