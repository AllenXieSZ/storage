#!/usr/bin/env python3
"""DCP checkpoint write/read benchmark on Lustre (CPU / gloo).
Each rank holds a ZeRO-like shard dict: param(bf16) + master(fp32) + exp_avg(fp32) + exp_avg_sq(fp32)
= 14 bytes/param. --gib-per-rank sets total bytes per rank.
Modes:
  save        : dcp.save (sync)               -> blocking time == total time
  async       : dcp.async_save (default stager / pinned mem) -> blocking time = staging, total = until future done
  torchsave   : one torch.save file per NODE (rank local 0 gathers via in-node? no -> each node writes its local ranks' shards into ONE file sequentially by local rank 0 after gather by file concat) -> simplified: local_rank 0 writes node-total-size tensor
  load        : dcp.load with same world size (same topology)
  load_reshard: dcp.load where world size differs from save (needs --saved-world); each rank loads 1/W of the global tensors
Results: rank0 prints a JSON line.
"""
import os, sys, time, json, argparse, socket
import torch, torch.distributed as dist
import torch.distributed.checkpoint as dcp
from torch.distributed.checkpoint import FileSystemWriter, FileSystemReader

p = argparse.ArgumentParser()
p.add_argument('--mode', required=True)
p.add_argument('--dir', required=True)
p.add_argument('--gib-per-rank', type=float, default=1.0)
p.add_argument('--saved-world', type=int, default=0)
p.add_argument('--threads', type=int, default=1, help='FileSystemWriter thread_count')
p.add_argument('--tag', default='')
p.add_argument('--stager', default='default', help='default|shm  (shm = DefaultStager(use_shared_memory,use_async_staging))')
p.add_argument('--proc', action='store_true', help='AsyncCheckpointerType.PROCESS')
a = p.parse_args()

dist.init_process_group('gloo', timeout=__import__('datetime').timedelta(minutes=60))
R, W = dist.get_rank(), dist.get_world_size()
LR = int(os.environ.get('LOCAL_RANK', 0)); LW = int(os.environ.get('LOCAL_WORLD_SIZE', 1))
torch.set_num_threads(1)

nbytes = int(a.gib_per_rank * (1 << 30))
nparam = nbytes // 14

def make_state(rank, n, fill=True):
    g = torch.Generator().manual_seed(rank)
    if fill:
        mk = lambda dt: (torch.rand(n, generator=g) if dt == torch.float32 else torch.rand(n, generator=g).to(dt))
    else:
        mk = lambda dt: torch.empty(n, dtype=dt)
    return {f'r{rank}.param': mk(torch.bfloat16), f'r{rank}.master': mk(torch.float32),
            f'r{rank}.exp_avg': mk(torch.float32), f'r{rank}.exp_avg_sq': mk(torch.float32)}

def bar(): dist.barrier()
res = {'mode': a.mode, 'world': W, 'local_world': LW, 'gib_per_rank': a.gib_per_rank, 'dir': a.dir, 'tag': a.tag}

if a.mode in ('save', 'async'):
    st = make_state(R, nparam)
    total = sum(t.numel() * t.element_size() for t in st.values())
    bar(); t0 = time.time()
    if a.mode == 'save':
        dcp.save(st, storage_writer=FileSystemWriter(a.dir, thread_count=a.threads, sync_files=True))
        tb = time.time() - t0; td = tb
    else:
        from torch.distributed.checkpoint.staging import DefaultStager, StagingOptions
        from torch.distributed.checkpoint.state_dict_saver import AsyncCheckpointerType
        kw = {}
        if a.stager == 'shm':
            kw['async_stager'] = DefaultStager(StagingOptions(use_pinned_memory=False, use_shared_memory=True, use_async_staging=True, use_non_blocking_copy=False))
        if a.proc:
            kw['async_checkpointer_type'] = AsyncCheckpointerType.PROCESS
        fut = dcp.async_save(st, storage_writer=FileSystemWriter(a.dir, thread_count=a.threads, sync_files=True), **kw)
        tb = time.time() - t0      # training-blocking time (staging: copy to (pinned) CPU buffer)
        if hasattr(fut, 'upload_completion'):
            fut.staging_completion.result(); tb = time.time() - t0; fut.upload_completion.result()
        else:
            fut.result()
        td = time.time() - t0
        if 'async_stager' in kw: kw['async_stager'].close()
        res['async_ret'] = type(fut).__name__
    t_local = torch.tensor([tb, td, total], dtype=torch.float64)
    bar(); tall = time.time() - t0
    mx = t_local.clone(); dist.all_reduce(mx, op=dist.ReduceOp.MAX)
    sm = t_local.clone(); dist.all_reduce(sm, op=dist.ReduceOp.SUM)
    res.update(block_max_s=mx[0].item(), done_max_s=mx[1].item(), wall_s=tall, total_gib=sm[2].item()/2**30,
               gbps=sm[2].item()/1e9/tall)
elif a.mode == 'torchsave':
    # few-shard mode: one big file per node. Every local rank contributes its shard; simulate "gathered to node then 1 file"
    # by having local_rank0 write a tensor of LW * per-rank bytes (same bytes per node as many-shard mode).
    os.makedirs(a.dir, exist_ok=True)
    node = R // LW
    if LR == 0:
        n = nparam * 14 * LW // 4
        big = torch.rand(n)
    bar(); t0 = time.time()
    if LR == 0:
        fn = os.path.join(a.dir, f'node{node}.pt')
        with open(fn, 'wb') as f:
            torch.save({'flat': big}, f); f.flush(); os.fsync(f.fileno())
        total = n * 4
    else:
        total = 0
    bar(); tall = time.time() - t0
    sm = torch.tensor([float(total)], dtype=torch.float64); dist.all_reduce(sm)
    res.update(wall_s=tall, total_gib=sm[0].item()/2**30, gbps=sm[0].item()/1e9/tall)
elif a.mode == 'torchload':
    node = R // LW
    bar(); t0 = time.time()
    total = 0
    if LR == 0:
        fn = os.path.join(a.dir, f'node{node}.pt')
        d = torch.load(fn, mmap=False); total = d['flat'].numel()*4
    bar(); tall = time.time() - t0
    sm = torch.tensor([float(total)], dtype=torch.float64); dist.all_reduce(sm)
    res.update(wall_s=tall, total_gib=sm[0].item()/2**30, gbps=sm[0].item()/1e9/tall)
elif a.mode == 'load':
    st = make_state(R, nparam, fill=False)
    total = sum(t.numel() * t.element_size() for t in st.values())
    bar(); t0 = time.time()
    dcp.load(st, storage_reader=FileSystemReader(a.dir))
    bar(); tall = time.time() - t0
    sm = torch.tensor([float(total)], dtype=torch.float64); dist.all_reduce(sm)
    res.update(wall_s=tall, total_gib=sm[0].item()/2**30, gbps=sm[0].item()/1e9/tall)
elif a.mode == 'load_reshard':
    # saved with world S; now world W. Global tensor set = S ranks x 4 keys. Assign keys round-robin to new ranks
    # (each new rank loads ~ S*4/W whole tensors) => reshard by ownership change.
    S = a.saved_world
    keys = [(r, k) for r in range(S) for k in ('param', 'master', 'exp_avg', 'exp_avg_sq')]
    mine = keys[R::W]
    dt = {'param': torch.bfloat16}
    st = {f'r{r}.{k}': torch.empty(nparam, dtype=dt.get(k, torch.float32)) for r, k in mine}
    total = sum(t.numel() * t.element_size() for t in st.values())
    bar(); t0 = time.time()
    dcp.load(st, storage_reader=FileSystemReader(a.dir))
    bar(); tall = time.time() - t0
    sm = torch.tensor([float(total)], dtype=torch.float64); dist.all_reduce(sm)
    res.update(saved_world=S, wall_s=tall, total_gib=sm[0].item()/2**30, gbps=sm[0].item()/1e9/tall)
elif a.mode in ('dp_readall', 'dp_bcast'):
    # Megatron fully-parallel-load simulation: DP group = all ranks on node? Here: groups of size G=LW (one node).
    # Replicated weights: every DP replica needs the same "model shard" (shard id = LR, saved by rank LR of saved world).
    # dp_readall : every rank reads the shard it needs itself (no fully-parallel-load -> each DP rank reads full shard)
    # dp_bcast   : fully-parallel: within DP group (same LR across nodes) each rank reads 1/N of the keys then all-gather/broadcast.
    nodes = W // LW
    shard = LR  # model-parallel index
    keys = ['param', 'master', 'exp_avg', 'exp_avg_sq']
    dt = {'param': torch.bfloat16}
    bar(); t0 = time.time()
    if a.mode == 'dp_readall':
        st = {f'r{shard}.{k}': torch.empty(nparam, dtype=dt.get(k, torch.float32)) for k in keys}
        dcp.load(st, storage_reader=FileSystemReader(a.dir), no_dist=True)
        total = sum(t.numel()*t.element_size() for t in st.values())
    else:
        # DP group = ranks with same LR across nodes; split 4 keys over group members; then broadcast each key from its reader
        grp_ranks = [n*LW + LR for n in range(nodes)]
        groups = [dist.new_group([n*LW + l for n in range(nodes)]) for l in range(LW)]
        g = groups[LR]
        node = R // LW
        mykeys = [k for i, k in enumerate(keys) if i % nodes == node]
        st = {f'r{shard}.{k}': torch.empty(nparam, dtype=dt.get(k, torch.float32)) for k in mykeys}
        if st: dcp.load(st, storage_reader=FileSystemReader(a.dir), no_dist=True)
        total = sum(t.numel()*t.element_size() for t in st.values())
        full = {}
        for i, k in enumerate(keys):
            src = grp_ranks[i % nodes]
            t = st.get(f'r{shard}.{k}')
            if t is None: t = torch.empty(nparam, dtype=dt.get(k, torch.float32))
            if t.dtype == torch.bfloat16:
                tv = t.view(torch.uint8); dist.broadcast(tv, src=src, group=g)
            else:
                dist.broadcast(t, src=src, group=g)
            full[k] = t
    bar(); tall = time.time() - t0
    sm = torch.tensor([float(total)], dtype=torch.float64); dist.all_reduce(sm)
    res.update(wall_s=tall, read_gib=sm[0].item()/2**30, gbps=sm[0].item()/1e9/tall)

elif a.mode in ('dsave', 'dload'):
    # true DCP resharding: 4 global 1-D tensors (param bf16, master/m/v fp32) sharded Shard(0) over a CPU DeviceMesh of world W.
    # dsave with W1, dload with W2 != W1 -> DCP load-time resharding (each new shard may overlap 1..k saved chunks).
    from torch.distributed.device_mesh import init_device_mesh
    from torch.distributed.tensor import DTensor, Shard
    S = a.saved_world if a.mode == 'dload' else W
    base = nparam - nparam % 3
    G = base * S                          # global numel per key (fixed by save world)
    assert G % W == 0, (G, W)
    n_local = G // W
    mesh = init_device_mesh('cpu', (W,))
    keys = {'param': torch.bfloat16, 'master': torch.float32, 'exp_avg': torch.float32, 'exp_avg_sq': torch.float32}
    if a.mode == 'dsave':
        gen = torch.Generator().manual_seed(R)
        loc = {k: torch.rand(n_local, generator=gen).to(dt) for k, dt in keys.items()}
    else:
        loc = {k: torch.empty(n_local, dtype=dt) for k, dt in keys.items()}
    st = {k: DTensor.from_local(v, mesh, [Shard(0)], run_check=False, shape=torch.Size([G]), stride=(1,)) for k, v in loc.items()}
    total = sum(v.numel() * v.element_size() for v in loc.values())
    bar(); t0 = time.time()
    if a.mode == 'dsave':
        dcp.save(st, storage_writer=FileSystemWriter(a.dir, thread_count=a.threads, sync_files=True))
    else:
        dcp.load(st, storage_reader=FileSystemReader(a.dir))
    bar(); tall = time.time() - t0
    sm = torch.tensor([float(total)], dtype=torch.float64); dist.all_reduce(sm)
    res.update(saved_world=S, wall_s=tall, total_gib=sm[0].item()/2**30, gbps=sm[0].item()/1e9/tall)

res['host0'] = socket.gethostname()
if R == 0:
    print('RESULT ' + json.dumps(res), flush=True)
dist.destroy_process_group()
