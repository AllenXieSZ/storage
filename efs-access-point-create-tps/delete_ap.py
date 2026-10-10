import boto3, botocore, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
FS, C = sys.argv[1], int(sys.argv[2])
cfg = botocore.config.Config(retries={'max_attempts': 1, 'mode': 'standard'}, max_pool_connections=C+10)
efs = boto3.client('efs', region_name='us-east-2', config=cfg)
def list_ids():
    out, tok = [], None
    while True:
        kw = {'FileSystemId': FS, 'MaxResults': 100}
        if tok: kw['NextToken'] = tok
        try: r = efs.describe_access_points(**kw)
        except botocore.exceptions.ClientError: time.sleep(1); continue
        out += [a['AccessPointId'] for a in r['AccessPoints']]; tok = r.get('NextToken')
        if not tok: return out
ids = list_ids(); print('to delete', len(ids), flush=True)
lat, errs, retries = [], {}, [0]; lock = threading.Lock()
def one(i):
    tries = 0
    while True:
        t = time.time()
        try:
            efs.delete_access_point(AccessPointId=i)
            with lock: lat.append(time.time() - t)
            return True
        except botocore.exceptions.ClientError as e:
            code = e.response['Error']['Code']
            with lock: errs[code] = errs.get(code, 0) + 1
            if code == 'AccessPointNotFound': return True
            if code in ('ThrottlingException', 'TooManyRequestsException') and tries < 50:
                tries += 1; retries[0] += 1; time.sleep(min(0.1 * 2 ** tries, 5)); continue
            print('ERR', i, code, flush=True); return False
s = time.time(); ok = done = 0
with ThreadPoolExecutor(C) as ex:
    for r in ex.map(one, ids):
        ok += r; done += 1
        if done % 1000 == 0: print(f'{done} done {time.time()-s:.1f}s tps={done/(time.time()-s):.2f}', flush=True)
el = time.time() - s; lat.sort()
p = lambda q: lat[min(len(lat)-1, int(len(lat)*q))]*1000 if lat else 0
print(f'RESULT n={len(ids)} c={C} ok={ok} fail={len(ids)-ok} elapsed={el:.1f}s tps={ok/el:.2f} p50={p(.5):.0f}ms p99={p(.99):.0f}ms retries={retries[0]} errs={errs}', flush=True)
