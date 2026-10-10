import boto3, botocore, sys, time, threading, csv, statistics
from concurrent.futures import ThreadPoolExecutor
FS, N, C, PREFIX = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
cfg = botocore.config.Config(retries={'max_attempts': 1, 'mode': 'standard'}, max_pool_connections=C+10)
efs = boto3.client('efs', region_name='us-east-2', config=cfg)
lat, errs, retries = [], {}, [0]; lock = threading.Lock()
def one(i):
    tries = 0
    while True:
        t = time.time()
        try:
            efs.create_access_point(FileSystemId=FS, ClientToken=f'{PREFIX}-{i}',
                PosixUser={'Uid': 1000, 'Gid': 1000},
                RootDirectory={'Path': f'/{PREFIX}/s{i:05d}', 'CreationInfo': {'OwnerUid': 1000, 'OwnerGid': 1000, 'Permissions': '755'}},
                Tags=[{'Key': 'Name', 'Value': f'{PREFIX}-{i}'}])
            with lock: lat.append(time.time() - t)
            return True
        except botocore.exceptions.ClientError as e:
            code = e.response['Error']['Code']
            with lock: errs[code] = errs.get(code, 0) + 1
            if code in ('ThrottlingException', 'TooManyRequestsException', 'ThrottledException') and tries < 20:
                tries += 1; retries[0] += 1; time.sleep(min(0.1 * 2 ** tries, 5)); continue
            print('ERR', i, code, e.response['Error'].get('Message', '')[:120], flush=True); return False
s = time.time(); ok = 0; done = 0
with ThreadPoolExecutor(C) as ex:
    for r in ex.map(one, range(N)):
        ok += r; done += 1
        if done % 1000 == 0: print(f'{done} done {time.time()-s:.1f}s tps={done/(time.time()-s):.1f}', flush=True)
el = time.time() - s; lat.sort()
p = lambda q: lat[min(len(lat)-1, int(len(lat)*q))]*1000 if lat else 0
print(f'RESULT n={N} c={C} ok={ok} fail={N-ok} elapsed={el:.1f}s tps={ok/el:.1f} p50={p(.5):.0f}ms p99={p(.99):.0f}ms max={p(1):.0f}ms retries={retries[0]} errs={errs}', flush=True)
