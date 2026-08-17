#!/usr/bin/env python3
# OpenCart 阶梯并发压测：逐级提升并发，找拐点。直击 ALB（内网）。
import sys, time, random, threading, requests
from collections import defaultdict

BASE = "http://<YOUR-ALB-DNS>.us-east-2.elb.amazonaws.com"  # 替换为你的 ALB / CloudFront 域名
PER  = int(sys.argv[1]) if len(sys.argv) > 1 else 15
LEVELS = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [20,50,100,200,400]

PRODUCT_IDS = list(range(20, 330))
CATEGORY_PATHS = [20,18,33,28,34,25,27,26,29,57,60]

def pick():
    r = random.random()
    if r < 0.85: return "browse"
    if r < 0.95: return "order"
    return "admin_add"

def timed(sess, method, url, **kw):
    t0 = time.time()
    try:
        r = sess.request(method, url, timeout=30, **kw)
        return r, (time.time()-t0)*1000
    except Exception:
        return None, (time.time()-t0)*1000

def do_browse(sess):
    ok=True; lat=0
    for url in [f"{BASE}/",
                f"{BASE}/index.php?route=product/category&language=en-gb&path={random.choice(CATEGORY_PATHS)}",
                f"{BASE}/index.php?route=product/product&language=en-gb&product_id={random.choice(PRODUCT_IDS)}"]:
        r,l=timed(sess,"GET",url); lat+=l
        if r is None or r.status_code>=500: ok=False
    return ok,lat

def do_order(sess):
    ok=True; lat=0; pid=random.choice(PRODUCT_IDS)
    r,l=timed(sess,"GET",f"{BASE}/index.php?route=product/product&language=en-gb&product_id={pid}"); lat+=l
    if r is None: return False,lat
    r,l=timed(sess,"POST",f"{BASE}/index.php?route=checkout/cart.add&language=en-gb",data={"product_id":pid,"quantity":1}); lat+=l
    if r is None or r.status_code>=500: ok=False
    r,l=timed(sess,"GET",f"{BASE}/index.php?route=checkout/checkout&language=en-gb"); lat+=l
    if r is None or r.status_code>=500: ok=False
    return ok,lat

def do_admin_add(sess):
    r,l=timed(sess,"GET",f"{BASE}/admin/")
    return (r is not None and r.status_code<500), l

def run_level(conc, per):
    results=defaultdict(list); lock=threading.Lock()
    def worker():
        sess=requests.Session(); sess.headers.update({"User-Agent":"loadtest/1.0"})
        for _ in range(per):
            op=pick()
            if op=="browse": ok,lat=do_browse(sess)
            elif op=="order": ok,lat=do_order(sess)
            else: ok,lat=do_admin_add(sess)
            with lock: results[op].append((ok,lat))
    t0=time.time()
    ths=[threading.Thread(target=worker) for _ in range(conc)]
    for t in ths: t.start()
    for t in ths: t.join()
    dur=time.time()-t0
    total=sum(len(v) for v in results.values())
    all_ok=sum(1 for v in results.values() for ok,_ in v if ok)
    all_lat=sorted(l for v in results.values() for _,l in v)
    n=len(all_lat)
    p50=all_lat[int(n*0.5)]; p95=all_lat[int(n*0.95)]; p99=all_lat[min(int(n*0.99),n-1)]
    print(f"并发{conc:4} | 动作{total:5} | 吞吐 {total/dur:6.1f} ops/s | 成功率 {all_ok/total*100:5.1f}% | 总体延迟 P50={p50:6.0f} P95={p95:6.0f} P99={p99:6.0f}ms | 耗时{dur:.1f}s")
    # 每类简报
    for op in ["browse","order","admin_add"]:
        v=results[op]
        if not v: continue
        lats=sorted(l for _,l in v); oks=sum(1 for ok,_ in v if ok); m=len(lats)
        print(f"      [{op:10}] n={m:4} 成功{oks/m*100:5.1f}% P95={lats[int(m*0.95)]:6.0f}ms")
    return all_ok/total*100, p95

def main():
    print(f"=== OpenCart 阶梯压测 (Redis session) 目标 {BASE} ===")
    print(f"每线程 {PER} 迭代, 比率 browse85/order10/admin5, 阶梯 {LEVELS}\n")
    for c in LEVELS:
        sr,p95=run_level(c,PER)
        print()
        if sr < 95 or p95 > 8000:
            print(f">>> 拐点: 并发{c} 成功率{sr:.1f}% P95={p95:.0f}ms — 已超阈值(成功率<95% 或 P95>8s)，停止爬坡")
            break
        time.sleep(3)

if __name__=="__main__": main()
