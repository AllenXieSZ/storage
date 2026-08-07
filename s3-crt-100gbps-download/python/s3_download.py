#!/usr/bin/env python3
"""S3 100GB 下载测试 - Python 多线程(GIL) + 多进程(绕GIL) + awscrt 三种方式。
bucket/key 从环境变量读取，避免硬编码：
  export S3_BUCKET=your-bucket S3_KEY=ckpt-bench/ckpt_100g.bin
"""
import os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool

BUCKET = os.environ.get("S3_BUCKET", "YOUR_BUCKET")
KEY    = os.environ.get("S3_KEY", "ckpt-bench/ckpt_100g.bin")
REGION = os.environ.get("AWS_REGION", "us-east-2")


# ---------- 方式1: boto3 多线程 (受 GIL 限制) ----------
def run_threads(part_mb, conc):
    import boto3
    from botocore.config import Config
    cfg = Config(region_name=REGION, max_pool_connections=conc + 16,
                 retries={"max_attempts": 3, "mode": "standard"})
    s3 = boto3.client("s3", config=cfg)
    total = s3.head_object(Bucket=BUCKET, Key=KEY)["ContentLength"]
    part = part_mb * 1024 * 1024
    nparts = (total + part - 1) // part
    ranges = [(i * part, min(i * part + part, total) - 1) for i in range(nparts)]
    counter = [0]; lock = threading.Lock()

    def fetch(r):
        st, en = r
        resp = s3.get_object(Bucket=BUCKET, Key=KEY, Range=f"bytes={st}-{en}")
        n = 0
        for chunk in resp["Body"].iter_chunks(chunk_size=1024 * 1024):
            n += len(chunk)
        with lock:
            counter[0] += n

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(fetch, ranges))
    dt = time.time() - t0
    gb = counter[0] / 1e9
    print(f"[threads] part={part_mb}MB conc={conc} | {dt:6.1f}s | {gb:6.1f}GB | {gb/dt:5.2f} GB/s ({gb*8/dt:5.1f} Gbps)", flush=True)


# ---------- 方式2: multiprocessing 多进程 (绕 GIL) ----------
def _mp_worker(args):
    import boto3
    from botocore.config import Config
    st, en = args
    s3 = boto3.client("s3", config=Config(region_name=REGION, max_pool_connections=8))
    resp = s3.get_object(Bucket=BUCKET, Key=KEY, Range=f"bytes={st}-{en}")
    n = 0
    for chunk in resp["Body"].iter_chunks(chunk_size=1024 * 1024):
        n += len(chunk)
    return n

def run_procs(part_mb, nproc):
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", config=Config(region_name=REGION))
    total = s3.head_object(Bucket=BUCKET, Key=KEY)["ContentLength"]
    part = part_mb * 1024 * 1024
    nparts = (total + part - 1) // part
    ranges = [(i * part, min(i * part + part, total) - 1) for i in range(nparts)]
    t0 = time.time()
    with Pool(processes=nproc) as p:
        res = p.map(_mp_worker, ranges, chunksize=1)
    dt = time.time() - t0
    gb = sum(res) / 1e9
    print(f"[procs] part={part_mb}MB nproc={nproc} | {dt:6.1f}s | {gb:6.1f}GB | {gb/dt:5.2f} GB/s ({gb*8/dt:5.1f} Gbps)", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "threads"
    if mode == "threads":
        print("=== Python boto3 多线程 (受 GIL 限制) ===", flush=True)
        for pm, c in [(8, 128), (8, 256), (16, 256), (8, 512)]:
            run_threads(pm, c)
    elif mode == "procs":
        print("=== Python boto3 多进程 (绕 GIL) ===", flush=True)
        for pm, n in [(8, 64), (8, 128), (16, 128), (8, 192)]:
            run_procs(pm, n)
