#!/usr/bin/env python3
import os, sys, time
from multiprocessing import Process, Value

BASE = "/mnt/fsx/<DRA_MOUNT_DIR>/autoexport-test"
NDIRS = 100
FILES_PER_DIR = 10000
SIZE = 10 * 1024
NPROC = 16
PAYLOAD = b"x" * SIZE

def worker(dir_start, dir_end, counter):
    n = 0
    for d in range(dir_start, dir_end):
        dpath = os.path.join(BASE, f"dir{d:04d}")
        os.makedirs(dpath, exist_ok=True)
        for f in range(FILES_PER_DIR):
            with open(os.path.join(dpath, f"file{f:05d}"), "wb") as fh:
                fh.write(PAYLOAD)
            n += 1
            if n % 2000 == 0:
                with counter.get_lock():
                    counter.value += 2000
    with counter.get_lock():
        counter.value += (n % 2000)

def main():
    os.makedirs(BASE, exist_ok=True)
    counter = Value("q", 0)
    total = NDIRS * FILES_PER_DIR
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
    print(f"START create {total} files x {SIZE}B in {BASE} at {time.strftime('%H:%M:%S')} UTC", flush=True)
    while any(p.is_alive() for p in procs):
        time.sleep(15)
        done = counter.value
        el = time.time() - t0
        rate = done / el if el > 0 else 0
        print(f"[{time.strftime('%H:%M:%S')}] created={done}/{total} rate={rate:.0f}/s elapsed={el:.0f}s", flush=True)
    for p in procs: p.join()
    el = time.time() - t0
    print(f"DONE {total} files in {el:.0f}s avg={total/el:.0f}/s at {time.strftime('%H:%M:%S')} UTC", flush=True)

if __name__ == "__main__":
    main()
