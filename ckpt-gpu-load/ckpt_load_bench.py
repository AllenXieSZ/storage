import io, os, time, threading, subprocess
import torch
import boto3
from botocore.config import Config

REGION="us-east-2"; BUCKET=os.environ.get("S3_BUCKET","YOUR_BUCKET"); KEY="ckpt-bench/ckpt_20g.pt"
LOCAL="/nvme/ckpt_dl.pt"
DEV="cuda:0"

def drop_caches():
    subprocess.run(["sh","-c","sync; echo 3 > /proc/sys/vm/drop_caches"])

def s3_client():
    return boto3.client("s3", config=Config(region_name=REGION, max_pool_connections=64))

def gpu_free():
    torch.cuda.empty_cache(); torch.cuda.synchronize()

# ---------- 路径A: S3 -> RAM -> 直接反序列化进显存 ----------
def path_a_mem_to_gpu(conc=64, part_mb=8):
    s3=s3_client()
    total=s3.head_object(Bucket=BUCKET,Key=KEY)["ContentLength"]
    part=part_mb*1024*1024
    nparts=(total+part-1)//part
    buf=bytearray(total)                       # 预分配整块内存
    from concurrent.futures import ThreadPoolExecutor
    def fetch(i):
        st=i*part; en=min(st+part,total)-1
        r=s3.get_object(Bucket=BUCKET,Key=KEY,Range=f"bytes={st}-{en}")
        data=r["Body"].read()
        buf[st:st+len(data)]=data              # 写进内存对应位置
    drop_caches(); gpu_free()
    t0=time.time()
    # 1) S3 并发下载到 RAM
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(fetch, range(nparts)))
    t_dl=time.time()
    # 2) 从内存 BytesIO 反序列化, map_location 直接到 GPU
    sd=torch.load(io.BytesIO(bytes(buf)), map_location=DEV, weights_only=True)
    torch.cuda.synchronize()                   # 等显存真正就绪
    t_gpu=time.time()
    nbytes=sum(v.numel()*v.element_size() for v in sd.values())
    print(f"[A: S3->RAM->GPU]  下载={t_dl-t0:5.1f}s  反序列化+送显存={t_gpu-t_dl:5.1f}s  【到显存总计={t_gpu-t0:5.1f}s】  显存张量={nbytes/1e9:.1f}GB", flush=True)
    del sd; gpu_free()
    return t_gpu-t0

# ---------- 路径B: S3 -> NVMe落盘 -> torch.load读盘 -> 显存 ----------
def path_b_disk_to_gpu(conc=64, part_mb=8):
    s3=s3_client()
    total=s3.head_object(Bucket=BUCKET,Key=KEY)["ContentLength"]
    part=part_mb*1024*1024
    nparts=(total+part-1)//part
    try: os.remove(LOCAL)
    except: pass
    # 预分配文件
    with open(LOCAL,"wb") as f: f.truncate(total)
    from concurrent.futures import ThreadPoolExecutor
    lock=threading.Lock()
    def fetch(i):
        st=i*part; en=min(st+part,total)-1
        r=s3.get_object(Bucket=BUCKET,Key=KEY,Range=f"bytes={st}-{en}")
        data=r["Body"].read()
        with open(LOCAL,"r+b") as f:           # 各线程写各自 offset
            f.seek(st); f.write(data)
    drop_caches(); gpu_free()
    t0=time.time()
    # 1) S3 并发下载落 NVMe
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(fetch, range(nparts)))
    os.sync()
    t_dl=time.time()
    # 2) loader 从磁盘读 + 送显存
    drop_caches()                              # 清 page cache, 保证真从盘读
    t_dl2=time.time()
    sd=torch.load(LOCAL, map_location=DEV, weights_only=True)
    torch.cuda.synchronize()
    t_gpu=time.time()
    nbytes=sum(v.numel()*v.element_size() for v in sd.values())
    print(f"[B: S3->NVMe->GPU] 下载落盘={t_dl-t0:5.1f}s  读盘+送显存={t_gpu-t_dl2:5.1f}s  【到显存总计={t_gpu-t0:5.1f}s】  显存张量={nbytes/1e9:.1f}GB", flush=True)
    del sd; gpu_free()
    return t_gpu-t0

if __name__=="__main__":
    print("=== Checkpoint 加载到显存对比 (g5.4xlarge A10G, 20GB ckpt) ===", flush=True)
    print("--- 各跑2轮 ---", flush=True)
    for _ in range(2):
        path_a_mem_to_gpu()
        path_b_disk_to_gpu()
