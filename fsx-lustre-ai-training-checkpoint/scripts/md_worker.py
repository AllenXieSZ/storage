# one "training process startup": import torch+transformers, read configs, mmap .npy indexes. prints elapsed json
import time, sys, os
t0 = time.time()
ENV = sys.argv[1]   # data dir (configs + npy)
import torch, transformers, numpy as np
t_imp = time.time() - t0
import json, glob
cfgs = sorted(glob.glob(os.path.join(ENV, 'cfg', '*.json')))
for c in cfgs:
    with open(c) as f: json.load(f)
from tokenizers import Tokenizer
tok = Tokenizer.from_file(os.path.join(ENV, 'tokenizer.json'))
arrs = [np.load(p, mmap_mode='r') for p in sorted(glob.glob(os.path.join(ENV, 'idx', '*.npy')))]
s = sum(int(a[len(a)//2]) for a in arrs)
print(json.dumps({'host': os.uname()[1], 'pid': os.getpid(), 'start': t0, 'imp': t_imp, 'total': time.time() - t0}), flush=True)
