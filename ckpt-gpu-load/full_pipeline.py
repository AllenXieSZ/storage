#!/usr/bin/env python3
"""S3 -> GPU 显存 全链路最优路径实测 (带教学注释)

结论(g5.4xlarge A10G, 20GB safetensors ckpt):
  最优路径 = 多进程下载(绕GIL) -> NVMe -> safetensors.load_file(cuda) = 28s
  对比 naive 路径(S3->RAM->torch.load(BytesIO)->GPU) = 130s, 快 4.6 倍。

bucket/key 从环境变量读取:
  export S3_BUCKET=your-bucket S3_KEY=ckpt-bench/ckpt_20g.safetensors
"""
import os, time, subprocess, multiprocessing as mp
import torch
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor
from safetensors.torch import load_file as st_load_file

REGION = os.environ.get("AWS_REGION", "us-east-2")
BUCKET = os.environ.get("S3_BUCKET", "YOUR_BUCKET")
KEY    = os.environ.get("S3_KEY", "ckpt-bench/ckpt_20g.safetensors")
DEV    = "cuda:0"


def drop():
    # 清 page cache（仅用于冷启动公平对比；最优路径靠下载刚写完的热缓存，不清）
    subprocess.run(["sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true"])


def gfree():
    torch.cuda.empty_cache(); torch.cuda.synchronize()


# ============ 关键1: 多进程下载 worker (绕过 Python GIL) ============
def _dl_worker(args):
    st, en, dest = args
    # ⚠️ 每个进程各建自己的 s3 client（boto3 client 不能跨进程共享）
    s3 = boto3.client("s3", config=Config(region_name=REGION, max_pool_connections=8))
    d = s3.get_object(Bucket=BUCKET, Key=KEY, Range=f"bytes={st}-{en}")["Body"].read()
    # 写到目标文件的对应 offset（各进程写各自不重叠区段，无冲突）
    with open(dest, "r+b") as f:
        f.seek(st); f.write(d)
    return len(d)


def mp_download(dest, nproc=64, part_mb=16):
    """多进程 byte-range 并行下载。每个进程独立解释器/GIL -> 真并行。"""
    s3 = boto3.client("s3", config=Config(region_name=REGION))
    total = s3.head_object(Bucket=BUCKET, Key=KEY)["ContentLength"]
    part = part_mb * 1024 * 1024
    nparts = (total + part - 1) // part
    with open(dest, "wb") as f:
        f.truncate(total)  # 预分配文件到完整大小，各 worker 才能安全 seek 写
    args = [(i * part, min(i * part + part, total) - 1, dest) for i in range(nparts)]
    with mp.Pool(nproc) as p:
        p.map(_dl_worker, args, chunksize=1)
    return total


# ============ 对照: 多线程下载 (受 GIL 限制, 约慢 3.5 倍) ============
def thread_download(dest, conc=64, part_mb=16):
    s3 = boto3.client("s3", config=Config(region_name=REGION, max_pool_connections=conc + 16))
    total = s3.head_object(Bucket=BUCKET, Key=KEY)["ContentLength"]
    part = part_mb * 1024 * 1024
    nparts = (total + part - 1) // part
    with open(dest, "wb") as f:
        f.truncate(total)
    def fetch(i):
        st = i * part; en = min(st + part, total) - 1
        d = s3.get_object(Bucket=BUCKET, Key=KEY, Range=f"bytes={st}-{en}")["Body"].read()
        with open(dest, "r+b") as f:
            f.seek(st); f.write(d)
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(fetch, range(nparts)))
    return total


# ============ 关键2: 加载到显存 (safetensors mmap 零拷贝直上 GPU) ============
def load_to_gpu(path):
    # device=cuda: safetensors mmap 文件, 数据直接 DMA 到显存 (不经 Python 反序列化/CPU tensor 中转)
    # 下载刚写完的文件数据还在 page cache (热的), 所以这步只需 ~3s, 不用真读盘
    sd = st_load_file(path, device=DEV)
    torch.cuda.synchronize()  # 等 GPU 真正就绪才计时
    n = sum(v.numel() * v.element_size() for v in sd.values())
    del sd; gfree()
    return n


def bench(name, dl_fn, dest):
    try: os.remove(dest)
    except: pass
    drop(); gfree()
    t0 = time.time()
    dl_fn(dest); t_dl = time.time()
    load_to_gpu(dest); t_gpu = time.time()
    print(f"[{name}]  下载={t_dl-t0:5.1f}s  加载显存={t_gpu-t_dl:5.1f}s  【总={t_gpu-t0:5.1f}s】", flush=True)
    try: os.remove(dest)
    except: pass


if __name__ == "__main__":
    print("=== S3->显存 全链路最优路径实测 (20GB) ===")
    bench("1 多线程DL -> NVMe -> load_file",  lambda d: thread_download(d), "/nvme/p1.st")
    bench("2 多进程DL -> NVMe -> load_file",  lambda d: mp_download(d),     "/nvme/p2.st")   # ← 最优 28s
    bench("3 多进程DL -> tmpfs -> load_file", lambda d: mp_download(d),     "/dev/shm/p3.st")
    bench("4 多线程DL -> tmpfs -> load_file", lambda d: thread_download(d), "/dev/shm/p4.st")
