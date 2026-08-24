#!/usr/bin/env python3
"""
S3 Vectors demo (方案B): 5 轮循环，每轮新建一个不同的 vector index，
batch 插入 100 条 1024-dim 随机向量（带 category 元数据），
再用 filter + 相似性查询，记录每轮 insert / query latency。
"""
import time, uuid, json, sys
import numpy as np
import boto3

REGION = "us-east-2"
DIM = 1024
N = 100          # 每轮插入 100 条
TOPK = 10        # 查询返回 top10
ROUNDS = 5       # 5 轮，每轮不同 index
CATEGORIES = ["tech", "finance", "sports", "music", "travel"]

s3v = boto3.client("s3vectors", region_name=REGION)

BUCKET = "weiwei-s3vectors-demo-" + uuid.uuid4().hex[:8]

def ms(dt):
    return round(dt * 1000, 2)

def rand_vec():
    v = np.random.randn(DIM).astype(np.float32)
    v = v / np.linalg.norm(v)          # 归一化，cosine 更规范，且避免零向量
    return v.tolist()

def main():
    print(f"[setup] creating vector bucket: {BUCKET}")
    s3v.create_vector_bucket(vectorBucketName=BUCKET)
    time.sleep(2)

    results = []
    for r in range(1, ROUNDS + 1):
        index_name = f"idx-round-{r}-{uuid.uuid4().hex[:6]}"
        print(f"\n===== Round {r}/{ROUNDS}  index={index_name} =====")

        # 1) create index
        t0 = time.perf_counter()
        s3v.create_index(
            vectorBucketName=BUCKET,
            indexName=index_name,
            dataType="float32",
            dimension=DIM,
            distanceMetric="cosine",
        )
        t_create = time.perf_counter() - t0
        # index 需要短暂就绪
        time.sleep(3)

        # 2) prepare 100 vectors with metadata
        vectors = []
        for i in range(N):
            cat = CATEGORIES[i % len(CATEGORIES)]
            vectors.append({
                "key": f"vec-{i}",
                "data": {"float32": rand_vec()},
                "metadata": {"category": cat, "idx": i},
            })

        # 3) batch insert (put_vectors 一次提交全部 100 条)
        t0 = time.perf_counter()
        s3v.put_vectors(vectorBucketName=BUCKET, indexName=index_name, vectors=vectors)
        t_insert = time.perf_counter() - t0

        # 4) query: filter category=tech + 相似性搜索
        query_vec = rand_vec()
        target_cat = "tech"
        t0 = time.perf_counter()
        resp = s3v.query_vectors(
            vectorBucketName=BUCKET,
            indexName=index_name,
            topK=TOPK,
            queryVector={"float32": query_vec},
            filter={"category": {"$eq": target_cat}},
            returnMetadata=True,
            returnDistance=True,
        )
        t_query = time.perf_counter() - t0
        hits = resp.get("vectors", [])

        print(f"  create_index : {ms(t_create):>8} ms")
        print(f"  batch insert : {ms(t_insert):>8} ms  ({N} vectors)")
        print(f"  filter query : {ms(t_query):>8} ms  (filter category={target_cat}, topK={TOPK}, hits={len(hits)})")
        if hits:
            print(f"    top1: key={hits[0]['key']} distance={hits[0].get('distance')} meta={hits[0].get('metadata')}")

        results.append({
            "round": r,
            "index": index_name,
            "create_index_ms": ms(t_create),
            "insert_ms": ms(t_insert),
            "query_ms": ms(t_query),
            "query_hits": len(hits),
        })

    # 汇总
    print("\n\n========== SUMMARY (5 rounds, different index each) ==========")
    print(f"{'Round':<6}{'CreateIdx(ms)':<15}{'Insert 100(ms)':<16}{'Query(ms)':<12}{'Hits':<6}")
    for x in results:
        print(f"{x['round']:<6}{x['create_index_ms']:<15}{x['insert_ms']:<16}{x['query_ms']:<12}{x['query_hits']:<6}")

    ins = [x["insert_ms"] for x in results]
    qry = [x["query_ms"] for x in results]
    print(f"\n  insert: first(cold)={ins[0]}ms  min={min(ins)}  max={max(ins)}  avg={round(sum(ins)/len(ins),2)}")
    print(f"  query : first(cold)={qry[0]}ms  min={min(qry)}  max={max(qry)}  avg={round(sum(qry)/len(qry),2)}")
    print(f"  (首轮 vs 后续均值)  insert 冷启动开销={round(ins[0]-sum(ins[1:])/len(ins[1:]),2)}ms  query={round(qry[0]-sum(qry[1:])/len(qry[1:]),2)}ms")

    with open("s3vectors_demo_result.json", "w") as f:
        json.dump({"bucket": BUCKET, "region": REGION, "dim": DIM, "n": N, "results": results}, f, indent=2)
    print(f"\n  saved -> s3vectors_demo_result.json")
    print(f"  vector bucket = {BUCKET}  (含 5 个 index，清理见脚本末尾提示)")
    print(f"  cleanup: python3 s3vectors_demo.py --cleanup {BUCKET}")

def cleanup(bucket):
    print(f"[cleanup] deleting all indexes + bucket: {bucket}")
    idxs = s3v.list_indexes(vectorBucketName=bucket).get("indexes", [])
    for ix in idxs:
        name = ix["indexName"]
        s3v.delete_index(vectorBucketName=bucket, indexName=name)
        print(f"  deleted index {name}")
    time.sleep(2)
    s3v.delete_vector_bucket(vectorBucketName=bucket)
    print(f"  deleted bucket {bucket}")

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--cleanup":
        cleanup(sys.argv[2])
    else:
        main()
