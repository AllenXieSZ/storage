#!/usr/bin/env python3
import boto3, os, sys, time
from multiprocessing import Process, Value
from botocore.config import Config

BUCKET = "<YOUR_DRA_S3_BUCKET>"
PREFIX = "autoimport-test"
NDIRS = 100          # dir0000..dir0099
FILES_PER_DIR = 10000
SIZE = 10 * 1024     # 10KB
NPROC = 16
REGION = "us-east-2"

PAYLOAD = b"x" * SIZE

def worker(dir_start, dir_end, counter):
    cfg = Config(region_name=REGION, max_pool_connections=64,
                 retries={"max_attempts": 5, "mode": "adaptive"})
    s3 = boto3.client("s3", config=cfg)
    n = 0
    for d in range(dir_start, dir_end):
        dname = f"dir{d:04d}"
        for f in range(FILES_PER_DIR):
            key = f"{PREFIX}/{dname}/file{f:05d}"
            s3.put_object(Bucket=BUCKET, Key=key, Body=PAYLOAD)
            n += 1
            if n % 2000 == 0:
                with counter.get_lock():
                    counter.value += 2000
    with counter.get_lock():
        counter.value += (n % 2000)

def main():
    counter = Value("q", 0)
    total = NDIRS * FILES_PER_DIR
    # split dirs across procs
    per = NDIRS // NPROC
    procs = []
    start = 0
    for i in range(NPROC):
        end = start + per + (1 if i < (NDIRS % NPROC) else 0)
        if end > start:
            p = Process(target=worker, args=(start, end, counter))
            p.start(); procs.append(p)
        start = end
    t0 = time.time()
    print(f"START upload {total} objects x {SIZE}B to s3://{BUCKET}/{PREFIX}/ at {time.strftime('%H:%M:%S')} UTC", flush=True)
    while any(p.is_alive() for p in procs):
        time.sleep(15)
        done = counter.value
        el = time.time() - t0
        rate = done / el if el > 0 else 0
        print(f"[{time.strftime('%H:%M:%S')}] uploaded={done}/{total} rate={rate:.0f}/s elapsed={el:.0f}s", flush=True)
    for p in procs: p.join()
    el = time.time() - t0
    print(f"DONE {total} objects in {el:.0f}s avg={total/el:.0f}/s at {time.strftime('%H:%M:%S')} UTC", flush=True)

if __name__ == "__main__":
    main()
