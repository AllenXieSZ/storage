#!/usr/bin/env python3
"""限速混合文件负载：每台客户端固定 ops/s，2MB 文件，写/读/改/rename/删。
每次操作写一行 ops 日志（CSV）：start_epoch,end_epoch,client,type,path,new_path,latency_ms,ok

用法:
  python3 lustre_load.py --root /mnt/lustre/work --client c1 --rate 40 --threads 8 \
      --duration 1800 --log /root/ops_c1.csv
操作比例（默认）: write 40 / read 30 / overwrite 10 / trunc_rewrite 10 / rename 5 / delete 5
  write         新建文件并写 2MB（O_CREAT）
  read          整个读一个已有文件
  overwrite     打开已有文件原地覆盖写 2MB（r+，不截断）
  trunc_rewrite 以 O_TRUNC 打开已有文件重写 2MB
  rename        同目录改名
  delete        删除一个已有文件
"""
import argparse, os, random, threading, time

p = argparse.ArgumentParser()
p.add_argument("--root", required=True)
p.add_argument("--client", required=True)
p.add_argument("--rate", type=float, default=40)     # 本机总 ops/s
p.add_argument("--threads", type=int, default=8)
p.add_argument("--duration", type=int, default=1800)
p.add_argument("--size", type=int, default=2 * 1024 * 1024)
p.add_argument("--log", required=True)
p.add_argument("--mix", default="write:40,read:30,overwrite:10,trunc_rewrite:10,rename:5,delete:5")
a = p.parse_args()

MIX = [(k, int(v)) for k, v in (x.split(":") for x in a.mix.split(","))]
BUF = os.urandom(a.size)
lock = threading.Lock()
logf = open(a.log, "w", buffering=1)
logf.write("start,end,client,type,path,new_path,latency_ms,ok\n")
T0 = time.time()

def pick(rng):
    r = rng.uniform(0, sum(w for _, w in MIX))
    for k, w in MIX:
        r -= w
        if r <= 0:
            return k
    return MIX[-1][0]

def worker(tid):
    rng = random.Random(f"{a.client}-{tid}")
    d = f"{a.root}/{a.client}/t{tid}"
    os.makedirs(d, exist_ok=True)
    files, seq = [], 0
    interval = a.threads / a.rate
    k = 0
    while True:
        due = T0 + tid * interval / a.threads + k * interval
        if due - T0 >= a.duration:
            break
        now = time.time()
        if due > now:
            time.sleep(due - now)
        k += 1
        op = pick(rng)
        if op != "write" and len(files) < 20:      # 文件池太小先写
            op = "write"
        path, newp, ok = "", "", 1
        s = time.time()
        try:
            if op == "write":
                seq += 1
                path = f"{d}/{a.client}_t{tid}_{seq:06d}.dat"
                with open(path, "wb") as f: f.write(BUF)
                files.append(path)
            elif op == "read":
                path = rng.choice(files)
                with open(path, "rb") as f:
                    while f.read(1 << 20): pass
            elif op == "overwrite":
                path = rng.choice(files)
                with open(path, "r+b") as f: f.write(BUF)
            elif op == "trunc_rewrite":
                path = rng.choice(files)
                with open(path, "wb") as f: f.write(BUF)
            elif op == "rename":
                i = rng.randrange(len(files)); path = files[i]
                newp = path[:-4] + "_r.dat"
                os.rename(path, newp); files[i] = newp
            elif op == "delete":
                i = rng.randrange(len(files)); path = files.pop(i)
                os.unlink(path)
        except Exception as e:
            ok = 0
        e = time.time()
        with lock:
            logf.write(f"{s:.6f},{e:.6f},{a.client},{op},{path},{newp},{(e-s)*1000:.2f},{ok}\n")

ts = [threading.Thread(target=worker, args=(i,)) for i in range(a.threads)]
[t.start() for t in ts]; [t.join() for t in ts]
logf.close()
