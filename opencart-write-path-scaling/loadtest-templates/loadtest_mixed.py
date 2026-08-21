#!/usr/bin/env python3
# OpenCart 混合负载压测: 浏览/下单/后台录入 按比率, 多线程模拟并发用户
# 用法: BASE=https://cloudfront-domain python3 loadtest_mixed.py <并发线程数> <每线程请求数>
# 注意: Python threading+requests 受 GIL 限制, 单机发压能力弱; 冲高 TPS 用 wrk。
import os, sys, time, random, threading, requests
from collections import defaultdict

BASE = os.environ.get("BASE", "https://your-cloudfront-domain.cloudfront.net")
CONC = int(sys.argv[1]) if len(sys.argv) > 1 else 10
PER  = int(sys.argv[2]) if len(sys.argv) > 2 else 20

# 操作比率: 浏览85%(首页/分类/商品) + 下单10% + 后台录入5%
def pick():
    r = random.random()
    if r < 0.85: return "browse"
    if r < 0.95: return "order"
    return "admin_add"

PRODUCT_IDS = list(range(20, 330))
CATEGORY_PATHS = [20,18,33,28,34,25,27,26,29,57,60]

results = defaultdict(list)
lock = threading.Lock()

def timed(sess, method, url, **kw):
    t0 = time.time()
    try:
        r = sess.request(method, url, timeout=30, **kw)
        return r, (time.time()-t0)*1000
    except Exception:
        return None, (time.time()-t0)*1000

def do_browse(sess):
    ok = True; lat = 0
    for url in [f"{BASE}/",
                f"{BASE}/index.php?route=product/category&language=en-gb&path={random.choice(CATEGORY_PATHS)}",
                f"{BASE}/index.php?route=product/product&language=en-gb&product_id={random.choice(PRODUCT_IDS)}"]:
        r, l = timed(sess, "GET", url); lat += l
        if r is None or r.status_code >= 500: ok = False
    return ok, lat

def do_order(sess):
    ok = True; lat = 0
    pid = random.choice(PRODUCT_IDS)
    r, l = timed(sess, "GET", f"{BASE}/index.php?route=product/product&language=en-gb&product_id={pid}"); lat += l
    if r is None: return False, lat
    r, l = timed(sess, "POST", f"{BASE}/index.php?route=checkout/cart.add&language=en-gb",
                 data={"product_id": pid, "quantity": 1}); lat += l
    if r is None or r.status_code >= 500: ok = False
    r, l = timed(sess, "GET", f"{BASE}/index.php?route=checkout/checkout&language=en-gb"); lat += l
    if r is None or r.status_code >= 500: ok = False
    return ok, lat

def do_admin_add(sess):
    r, l = timed(sess, "GET", f"{BASE}/admin/")
    return (r is not None and r.status_code < 500), l

def worker():
    sess = requests.Session()
    sess.headers.update({"User-Agent":"loadtest/1.0"})
    for _ in range(PER):
        op = pick()
        if op == "browse": ok, lat = do_browse(sess)
        elif op == "order": ok, lat = do_order(sess)
        else: ok, lat = do_admin_add(sess)
        with lock:
            results[op].append((ok, lat))

def main():
    print(f"混合压测: {CONC} 并发 x {PER} 迭代 = {CONC*PER} 会话动作, 目标 {BASE}")
    print("比率: browse 85% / order 10% / admin_add 5%")
    t0 = time.time()
    ths = [threading.Thread(target=worker) for _ in range(CONC)]
    for t in ths: t.start()
    for t in ths: t.join()
    dur = time.time()-t0
    print(f"\n总耗时 {dur:.1f}s")
    total_ops = sum(len(v) for v in results.values())
    print(f"总动作数 {total_ops}, 吞吐 {total_ops/dur:.1f} ops/s\n")
    for op in ["browse","order","admin_add"]:
        v = results[op]
        if not v: continue
        lats = sorted(l for _,l in v)
        oks = sum(1 for ok,_ in v if ok)
        n = len(lats)
        p50 = lats[int(n*0.5)]; p95 = lats[int(n*0.95)]; p99 = lats[min(int(n*0.99),n-1)]
        print(f"[{op:10}] n={n:4} 成功率={oks/n*100:5.1f}% P50={p50:7.0f}ms P95={p95:7.0f}ms P99={p99:7.0f}ms")

if __name__ == "__main__":
    main()
