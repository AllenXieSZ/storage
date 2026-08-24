#!/usr/bin/env python3
"""
S3 Vectors demo v2: 单个 index，插入 10000 条 1024-dim 向量（每批 500，共 20 批），
然后同一 index 连续跑 5 轮相似性查询，记录每轮 query latency，
观察首次查询是否比后续更慢（冷查询 vs 热查询）。
"""
import time, uuid, json, sys
import numpy as np
import boto3

REGION = "us-east-2"
DIM = 1024
TOTAL = 10000
BATCH = 500
QUERY_ROUNDS = 5
TOPK = 10
CATEGORIES = ["tech", "finance", "sports", "music", "travel"]

s3v = boto3.client("s3vectors", region_name=REGION)
BUCKET = "weiwei-s3vectors-demo-" + uuid.uuid4().hex[:8]
INDEX = "idx-10k-" + uuid.uuid4().hex[:6]

def ms(dt): return round(dt * 1000, 2)

def rand_vec():
    v = np.random.randn(DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()

def main():
    print(f"[setup] bucket={BUCKET} index={INDEX}")
    s3v.create_vector_bucket(vectorBucketName=BUCKET)
    time.sleep(2)

    t0 = time.perf_counter()
    s3v.create_index(vectorBucketName=BUCKET, indexName=INDEX,
                     dataType="float32", dimension=DIM, distanceMetric="cosine")
    print(f"  create_index: {ms(time.perf_counter()-t0)} ms")
    time.sleep(3)

    # ---- 分批插入 10000 条 ----
    print(f"\n[insert] {TOTAL} vectors, batch={BATCH} ({TOTAL//BATCH} batches)")
    batch_lat = []
    t_ins_all = time.perf_counter()
    for b in range(TOTAL // BATCH):
        vectors = []
        for j in range(BATCH):
            i = b * BATCH + j
            vectors.append({
                "key": f"vec-{i}",
                "data": {"float32": rand_vec()},
                "metadata": {"category": CATEGORIES[i % len(CATEGORIES)], "idx": i},
            })
        t0 = time.perf_counter()
        s3v.put_vectors(vectorBucketName=BUCKET, indexName=INDEX, vectors=vectors)
        dt = ms(time.perf_counter() - t0)
        batch_lat.append(dt)
        print(f"  batch {b+1:>2}/{TOTAL//BATCH}: {dt:>8} ms")
    total_ins = ms(time.perf_counter() - t_ins_all)
    print(f"  total insert: {total_ins} ms ({TOTAL} vectors), avg/batch={round(sum(batch_lat)/len(batch_lat),2)} ms")

    # 稍等，确保索引就绪
    time.sleep(3)

    # ---- 同一 index 跑 5 轮 query ----
    print(f"\n[query] same index, {QUERY_ROUNDS} rounds, filter category=tech, topK={TOPK}")
    q_lat = []
    for r in range(1, QUERY_ROUNDS + 1):
        qv = rand_vec()
        t0 = time.perf_counter()
        resp = s3v.query_vectors(
            vectorBucketName=BUCKET, indexName=INDEX, topK=TOPK,
            queryVector={"float32": qv},
            filter={"category": {"$eq": "tech"}},
            returnMetadata=True, returnDistance=True,
        )
        dt = ms(time.perf_counter() - t0)
        q_lat.append(dt)
        hits = resp.get("vectors", [])
        top1 = hits[0] if hits else None
        print(f"  query round {r}: {dt:>8} ms  hits={len(hits)}"
              + (f"  top1_dist={round(top1['distance'],4)}" if top1 else ""))

    # ---- 汇总 ----
    print("\n========== QUERY SUMMARY (same index, 5 rounds) ==========")
    for r, dt in enumerate(q_lat, 1):
        tag = "  <- 首次(cold)" if r == 1 else ""
        print(f"  round {r}: {dt} ms{tag}")
    warm = q_lat[1:]
    print(f"\n  first(cold) = {q_lat[0]} ms")
    print(f"  warm avg    = {round(sum(warm)/len(warm),2)} ms  (rounds 2-5)")
    print(f"  cold - warm = {round(q_lat[0]-sum(warm)/len(warm),2)} ms  "
          f"({'首次更慢' if q_lat[0]>sum(warm)/len(warm) else '首次不慢'})")
    print(f"  min={min(q_lat)}  max={max(q_lat)}  avg={round(sum(q_lat)/len(q_lat),2)}")

    with open("s3vectors_demo_v2_result.json", "w") as f:
        json.dump({"bucket": BUCKET, "index": INDEX, "total": TOTAL, "batch": BATCH,
                   "insert_batches_ms": batch_lat, "total_insert_ms": total_ins,
                   "query_rounds_ms": q_lat}, f, indent=2)
    print(f"\n  saved -> s3vectors_demo_v2_result.json")
    print(f"  cleanup: python3 s3vectors_demo_v2.py --cleanup {BUCKET}")

def cleanup(bucket):
    for ix in s3v.list_indexes(vectorBucketName=bucket).get("indexes", []):
        s3v.delete_index(vectorBucketName=bucket, indexName=ix["indexName"])
        print(f"  deleted index {ix['indexName']}")
    time.sleep(2)
    s3v.delete_vector_bucket(vectorBucketName=bucket)
    print(f"  deleted bucket {bucket}")

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--cleanup":
        cleanup(sys.argv[2])
    else:
        main()
