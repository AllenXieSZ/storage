#!/usr/bin/env python3
"""Rate-controlled 1 MiB file writer for EFS.
usage: writer.py --root /efs --rate R --duration S --t0 EPOCH --host-index h --hosts H --procs P --out /tmp/w.csv
File k (0..R-1) of second s goes to <root>/rate<R>/<t0+s>/h<h>of<H>/f_<k>, target time t0+s+k/R.
Host h handles k%H==h; inside host, process p handles (k//H)%P==p.
CSV: rel_path,target_ts,start_ts,done_ts  (done_ts = after close())
"""
import argparse, os, time, multiprocessing as mp

def worker(a, p, outfile):
    buf = bytearray(os.urandom(1 << 20))
    base = os.path.join(a.root, f"rate{a.rate}")
    made = set()
    f = open(outfile, "w", buffering=1 << 16)
    try:
      if True:
        for s in range(a.duration):
            sec = a.t0 + s
            d = os.path.join(base, str(sec), f"h{a.host_index}of{a.hosts}")
            for k in range(a.host_index, a.rate, a.hosts):
                if (k // a.hosts) % a.procs != p:
                    continue
                tgt = sec + k / a.rate
                now = time.time()
                if now > a.t0 + a.duration + a.grace:
                    return  # hard stop: cannot keep up, stop at deadline

                if tgt > now:
                    time.sleep(tgt - now)
                st = time.time()
                name = f"f_{k}"
                hdr = f"{sec}/h{a.host_index}/{name}".encode()
                buf[:len(hdr)] = hdr
                fd = os.open(os.path.join(d, name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
                os.write(fd, buf)
                os.close(fd)
                dn = time.time()
                f.write(f"rate{a.rate}/{sec}/h{a.host_index}of{a.hosts}/{name},{tgt:.6f},{st:.6f},{dn:.6f}\n")
    finally:
        f.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/efs"); ap.add_argument("--rate", type=int, required=True)
    ap.add_argument("--duration", type=int, required=True); ap.add_argument("--t0", type=int, required=True)
    ap.add_argument("--host-index", type=int, default=0); ap.add_argument("--hosts", type=int, default=1)
    ap.add_argument("--procs", type=int, default=64)
    ap.add_argument("--grace", type=float, default=5.0, help="stop writing grace seconds after t0+duration even if behind schedule"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    # pre-create <rate>/<sec>/h<h>of<H> for every second before t0 (multi-client mkdir race safe)
    base = os.path.join(a.root, f"rate{a.rate}")
    for s in range(a.duration):
        d = os.path.join(base, str(a.t0 + s), f"h{a.host_index}of{a.hosts}")
        for attempt in range(50):
            try:
                os.makedirs(d, exist_ok=True); break
            except (FileNotFoundError, FileExistsError):
                time.sleep(0.05); os.listdir(a.root)
        else:
            raise SystemExit(f"mkdir failed {d}")
    print("dirs ready", time.time(), flush=True)
    ps = [mp.Process(target=worker, args=(a, p, f"{a.out}.{p}")) for p in range(a.procs)]
    [x.start() for x in ps]; [x.join() for x in ps]
    with open(a.out, "w") as o:
        o.write("path,target_ts,start_ts,done_ts\n")
        for p in range(a.procs):
            with open(f"{a.out}.{p}") as i: o.write(i.read())
            os.remove(f"{a.out}.{p}")
    print("done", a.out)
