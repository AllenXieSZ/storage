#!/usr/bin/env python3
"""Every second write <root>/hb/<epoch_sec> containing the timestamp. Runs until killed."""
import os, sys, time
root = sys.argv[1] if len(sys.argv) > 1 else "/efs"
d = os.path.join(root, "hb"); os.makedirs(d, exist_ok=True)
log = open("/tmp/hb.csv", "a", buffering=1)
nxt = int(time.time()) + 1
while True:
    time.sleep(max(0, nxt - time.time()))
    with open(os.path.join(d, str(nxt)), "w") as f: f.write(f"{time.time():.6f}\n")
    log.write(f"{nxt},{time.time():.6f}\n"); nxt += 1
