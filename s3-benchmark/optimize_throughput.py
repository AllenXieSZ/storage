#!/usr/bin/env python3
"""
S3 Throughput Optimization Test
Tests multiple strategies to maximize S3 throughput:
1. Larger chunk sizes (16MB, 32MB, 64MB)
2. Multiprocessing to bypass GIL
3. Multiple concurrent files (4 files in parallel)

Finds the best configuration and reports results.
"""

import boto3
import time
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count
import multiprocessing

REGION = os.environ.get("BENCH_REGION", "us-east-2")
BUCKET_STD = os.environ.get("BENCH_BUCKET_STD", "")
BUCKET_EXPRESS = os.environ.get("BENCH_BUCKET_EXPRESS", "")
FILE_SIZE = 1024 * 1024 * 1024  # 1GB

# Test configurations
CHUNK_SIZES = [8, 16, 32, 64]  # MB
CONCURRENCIES = [32, 64, 128]
MULTI_FILE_COUNT = 4


def create_s3_client():
    return boto3.client("s3", region_name=REGION)


def generate_data(size):
    return os.urandom(size)


# === Thread-based upload (baseline) ===
def thread_multipart_upload(bucket, key, total_size, chunk_size_mb, concurrency):
    s3 = create_s3_client()
    chunk_size = chunk_size_mb * 1024 * 1024
    data = generate_data(total_size)
    num_parts = (total_size + chunk_size - 1) // chunk_size

    mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
    upload_id = mpu["UploadId"]

    start = time.perf_counter()

    def upload_part(part_num):
        # Each thread gets its own client to avoid connection contention
        thread_s3 = boto3.client("s3", region_name=REGION)
        offset = (part_num - 1) * chunk_size
        end = min(offset + chunk_size, total_size)
        part_data = data[offset:end]
        resp = thread_s3.upload_part(
            Bucket=bucket, Key=key, UploadId=upload_id,
            PartNumber=part_num, Body=part_data
        )
        return {"PartNumber": part_num, "ETag": resp["ETag"]}

    parts = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(upload_part, i) for i in range(1, num_parts + 1)]
        for f in as_completed(futures):
            parts.append(f.result())

    parts.sort(key=lambda x: x["PartNumber"])
    s3.complete_multipart_upload(
        Bucket=bucket, Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": parts}
    )

    elapsed = time.perf_counter() - start
    throughput = (total_size / (1024 * 1024)) / elapsed
    # Cleanup
    s3.delete_object(Bucket=bucket, Key=key)
    return throughput


# === Thread-based range GET ===
def thread_range_get(bucket, key, total_size, chunk_size_mb, concurrency):
    s3 = create_s3_client()
    chunk_size = chunk_size_mb * 1024 * 1024
    num_ranges = (total_size + chunk_size - 1) // chunk_size

    start = time.perf_counter()

    def get_range(range_num):
        thread_s3 = boto3.client("s3", region_name=REGION)
        offset = range_num * chunk_size
        end = min(offset + chunk_size - 1, total_size - 1)
        resp = thread_s3.get_object(Bucket=bucket, Key=key, Range=f"bytes={offset}-{end}")
        resp["Body"].read()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(get_range, i) for i in range(num_ranges)]
        for f in as_completed(futures):
            f.result()

    elapsed = time.perf_counter() - start
    throughput = (total_size / (1024 * 1024)) / elapsed
    return throughput


# === Process-based upload (bypass GIL) ===
def _process_upload_worker(args):
    """Worker function for multiprocessing upload."""
    bucket, key, upload_id, part_num, chunk_size, total_size, region = args
    s3 = boto3.client("s3", region_name=region)
    offset = (part_num - 1) * chunk_size
    end = min(offset + chunk_size, total_size)
    data = os.urandom(end - offset)  # Generate per-process to avoid IPC
    resp = s3.upload_part(
        Bucket=bucket, Key=key, UploadId=upload_id,
        PartNumber=part_num, Body=data
    )
    return {"PartNumber": part_num, "ETag": resp["ETag"]}


def process_multipart_upload(bucket, key, total_size, chunk_size_mb, concurrency):
    s3 = create_s3_client()
    chunk_size = chunk_size_mb * 1024 * 1024
    num_parts = (total_size + chunk_size - 1) // chunk_size

    mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
    upload_id = mpu["UploadId"]

    start = time.perf_counter()

    worker_args = [
        (bucket, key, upload_id, i, chunk_size, total_size, REGION)
        for i in range(1, num_parts + 1)
    ]

    num_workers = min(concurrency, num_parts, cpu_count() * 2)
    with Pool(processes=num_workers) as pool:
        parts = pool.map(_process_upload_worker, worker_args)

    parts.sort(key=lambda x: x["PartNumber"])
    s3.complete_multipart_upload(
        Bucket=bucket, Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": parts}
    )

    elapsed = time.perf_counter() - start
    throughput = (total_size / (1024 * 1024)) / elapsed
    s3.delete_object(Bucket=bucket, Key=key)
    return throughput


# === Process-based range GET ===
def _process_get_worker(args):
    """Worker function for multiprocessing GET."""
    bucket, key, offset, end, region = args
    s3 = boto3.client("s3", region_name=region)
    resp = s3.get_object(Bucket=bucket, Key=key, Range=f"bytes={offset}-{end}")
    resp["Body"].read()
    return True


def process_range_get(bucket, key, total_size, chunk_size_mb, concurrency):
    s3 = create_s3_client()
    chunk_size = chunk_size_mb * 1024 * 1024
    num_ranges = (total_size + chunk_size - 1) // chunk_size

    worker_args = []
    for i in range(num_ranges):
        offset = i * chunk_size
        end = min(offset + chunk_size - 1, total_size - 1)
        worker_args.append((bucket, key, offset, end, REGION))

    start = time.perf_counter()

    num_workers = min(concurrency, num_ranges, cpu_count() * 2)
    with Pool(processes=num_workers) as pool:
        pool.map(_process_get_worker, worker_args)

    elapsed = time.perf_counter() - start
    throughput = (total_size / (1024 * 1024)) / elapsed
    return throughput


# === Multi-file parallel transfer ===
def multi_file_upload(bucket, prefix, total_size, chunk_size_mb, concurrency, num_files):
    """Upload multiple files in parallel using threads of processes."""
    per_file_size = total_size // num_files
    s3 = create_s3_client()

    start = time.perf_counter()

    def upload_one_file(file_idx):
        key = f"{prefix}/file-{file_idx}"
        thread_s3 = boto3.client("s3", region_name=REGION)
        chunk_size = chunk_size_mb * 1024 * 1024
        data = os.urandom(per_file_size)
        num_parts = (per_file_size + chunk_size - 1) // chunk_size

        mpu = thread_s3.create_multipart_upload(Bucket=bucket, Key=key)
        upload_id = mpu["UploadId"]

        def up_part(pn):
            ps3 = boto3.client("s3", region_name=REGION)
            off = (pn - 1) * chunk_size
            e = min(off + chunk_size, per_file_size)
            r = ps3.upload_part(Bucket=bucket, Key=key, UploadId=upload_id,
                                PartNumber=pn, Body=data[off:e])
            return {"PartNumber": pn, "ETag": r["ETag"]}

        parts = []
        per_file_conc = max(4, concurrency // num_files)
        with ThreadPoolExecutor(max_workers=per_file_conc) as ex:
            futs = [ex.submit(up_part, i) for i in range(1, num_parts + 1)]
            for f in as_completed(futs):
                parts.append(f.result())

        parts.sort(key=lambda x: x["PartNumber"])
        thread_s3.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": parts}
        )

    with ThreadPoolExecutor(max_workers=num_files) as executor:
        list(executor.map(upload_one_file, range(num_files)))

    elapsed = time.perf_counter() - start
    throughput = (total_size / (1024 * 1024)) / elapsed

    # Cleanup
    for i in range(num_files):
        s3.delete_object(Bucket=bucket, Key=f"{prefix}/file-{i}")

    return throughput


def multi_file_range_get(bucket, prefix, total_size, chunk_size_mb, concurrency, num_files):
    """Download multiple files in parallel."""
    per_file_size = total_size // num_files
    s3 = create_s3_client()

    # First upload the files
    for i in range(num_files):
        key = f"{prefix}/file-{i}"
        chunk_size = chunk_size_mb * 1024 * 1024
        data = os.urandom(per_file_size)
        num_parts = (per_file_size + chunk_size - 1) // chunk_size
        mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
        upload_id = mpu["UploadId"]

        def up_part(pn, k=key, uid=upload_id, d=data):
            ps3 = boto3.client("s3", region_name=REGION)
            off = (pn - 1) * chunk_size
            e = min(off + chunk_size, per_file_size)
            r = ps3.upload_part(Bucket=bucket, Key=k, UploadId=uid, PartNumber=pn, Body=d[off:e])
            return {"PartNumber": pn, "ETag": r["ETag"]}

        parts = []
        with ThreadPoolExecutor(max_workers=32) as ex:
            futs = [ex.submit(up_part, p) for p in range(1, num_parts + 1)]
            for f in as_completed(futs):
                parts.append(f.result())
        parts.sort(key=lambda x: x["PartNumber"])
        s3.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id,
                                     MultipartUpload={"Parts": parts})

    # Now test range GET
    start = time.perf_counter()

    def get_one_file(file_idx):
        key = f"{prefix}/file-{file_idx}"
        chunk_size = chunk_size_mb * 1024 * 1024
        num_ranges = (per_file_size + chunk_size - 1) // chunk_size
        per_file_conc = max(4, concurrency // num_files)

        def get_range(rn):
            gs3 = boto3.client("s3", region_name=REGION)
            off = rn * chunk_size
            end = min(off + chunk_size - 1, per_file_size - 1)
            resp = gs3.get_object(Bucket=bucket, Key=key, Range=f"bytes={off}-{end}")
            resp["Body"].read()

        with ThreadPoolExecutor(max_workers=per_file_conc) as ex:
            list(ex.map(get_range, range(num_ranges)))

    with ThreadPoolExecutor(max_workers=num_files) as executor:
        list(executor.map(get_one_file, range(num_files)))

    elapsed = time.perf_counter() - start
    throughput = (total_size / (1024 * 1024)) / elapsed

    # Cleanup
    for i in range(num_files):
        s3.delete_object(Bucket=bucket, Key=f"{prefix}/file-{i}")

    return throughput


def run_optimization_tests(bucket, bucket_type):
    """Run all optimization strategies and find the best."""
    s3 = create_s3_client()
    results = []

    print(f"\n{'='*70}")
    print(f"  THROUGHPUT OPTIMIZATION: {bucket_type}")
    print(f"  Bucket: {bucket}")
    print(f"  File Size: {FILE_SIZE//(1024*1024)} MB")
    print(f"{'='*70}")

    # --- Strategy 1: Thread-based, vary chunk size and concurrency ---
    print(f"\n  [Strategy 1] Thread-based, varying chunk & concurrency")
    print(f"  {'-'*60}")

    # First upload a 1GB object for GET tests
    print(f"    Preparing 1GB test object...", end=" ", flush=True)
    key = "bench/opt-test-object"
    chunk = 32 * 1024 * 1024
    data = generate_data(FILE_SIZE)
    num_parts = (FILE_SIZE + chunk - 1) // chunk
    mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
    uid = mpu["UploadId"]
    parts = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        def _up(pn):
            ps3 = boto3.client("s3", region_name=REGION)
            off = (pn-1)*chunk
            e = min(off+chunk, FILE_SIZE)
            r = ps3.upload_part(Bucket=bucket, Key=key, UploadId=uid, PartNumber=pn, Body=data[off:e])
            return {"PartNumber": pn, "ETag": r["ETag"]}
        futs = [ex.submit(_up, i) for i in range(1, num_parts+1)]
        for f in as_completed(futs):
            parts.append(f.result())
    parts.sort(key=lambda x: x["PartNumber"])
    s3.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=uid, MultipartUpload={"Parts": parts})
    del data
    print("done")

    for chunk_mb in CHUNK_SIZES:
        for conc in CONCURRENCIES:
            # Upload test
            label = f"thread/upload/chunk={chunk_mb}MB/conc={conc}"
            print(f"    {label}...", end=" ", flush=True)
            try:
                tp = thread_multipart_upload(bucket, "bench/opt-upload", FILE_SIZE, chunk_mb, conc)
                print(f"{tp:.1f} MB/s")
                results.append({"strategy": label, "type": "upload", "method": "thread",
                               "chunk_mb": chunk_mb, "concurrency": conc, "throughput_mbps": round(tp, 1)})
            except Exception as e:
                print(f"ERROR: {e}")

            # GET test
            label = f"thread/get/chunk={chunk_mb}MB/conc={conc}"
            print(f"    {label}...", end=" ", flush=True)
            try:
                tp = thread_range_get(bucket, key, FILE_SIZE, chunk_mb, conc)
                print(f"{tp:.1f} MB/s")
                results.append({"strategy": label, "type": "get", "method": "thread",
                               "chunk_mb": chunk_mb, "concurrency": conc, "throughput_mbps": round(tp, 1)})
            except Exception as e:
                print(f"ERROR: {e}")

    # --- Strategy 2: Process-based (bypass GIL) ---
    print(f"\n  [Strategy 2] Process-based (multiprocessing, bypass GIL)")
    print(f"  {'-'*60}")

    for chunk_mb in [16, 32, 64]:
        conc = 32  # Processes are heavier, use fewer

        label = f"process/upload/chunk={chunk_mb}MB/workers={conc}"
        print(f"    {label}...", end=" ", flush=True)
        try:
            tp = process_multipart_upload(bucket, "bench/opt-proc-upload", FILE_SIZE, chunk_mb, conc)
            print(f"{tp:.1f} MB/s")
            results.append({"strategy": label, "type": "upload", "method": "process",
                           "chunk_mb": chunk_mb, "concurrency": conc, "throughput_mbps": round(tp, 1)})
        except Exception as e:
            print(f"ERROR: {e}")

        label = f"process/get/chunk={chunk_mb}MB/workers={conc}"
        print(f"    {label}...", end=" ", flush=True)
        try:
            tp = process_range_get(bucket, key, FILE_SIZE, chunk_mb, conc)
            print(f"{tp:.1f} MB/s")
            results.append({"strategy": label, "type": "get", "method": "process",
                           "chunk_mb": chunk_mb, "concurrency": conc, "throughput_mbps": round(tp, 1)})
        except Exception as e:
            print(f"ERROR: {e}")

    # --- Strategy 3: Multi-file parallel ---
    print(f"\n  [Strategy 3] Multi-file parallel ({MULTI_FILE_COUNT} files x {FILE_SIZE//(MULTI_FILE_COUNT*1024*1024)}MB)")
    print(f"  {'-'*60}")

    for chunk_mb in [16, 32]:
        conc = 64
        label = f"multi-file/upload/{MULTI_FILE_COUNT}files/chunk={chunk_mb}MB/conc={conc}"
        print(f"    {label}...", end=" ", flush=True)
        try:
            tp = multi_file_upload(bucket, "bench/opt-multi", FILE_SIZE, chunk_mb, conc, MULTI_FILE_COUNT)
            print(f"{tp:.1f} MB/s")
            results.append({"strategy": label, "type": "upload", "method": "multi-file",
                           "chunk_mb": chunk_mb, "concurrency": conc, "throughput_mbps": round(tp, 1)})
        except Exception as e:
            print(f"ERROR: {e}")

        label = f"multi-file/get/{MULTI_FILE_COUNT}files/chunk={chunk_mb}MB/conc={conc}"
        print(f"    {label}...", end=" ", flush=True)
        try:
            tp = multi_file_range_get(bucket, "bench/opt-multi-get", FILE_SIZE, chunk_mb, conc, MULTI_FILE_COUNT)
            print(f"{tp:.1f} MB/s")
            results.append({"strategy": label, "type": "get", "method": "multi-file",
                           "chunk_mb": chunk_mb, "concurrency": conc, "throughput_mbps": round(tp, 1)})
        except Exception as e:
            print(f"ERROR: {e}")

    # Cleanup test object
    s3.delete_object(Bucket=bucket, Key=key)

    return results


def main():
    if not BUCKET_STD or not BUCKET_EXPRESS:
        print("ERROR: BENCH_BUCKET_STD and BENCH_BUCKET_EXPRESS required")
        sys.exit(1)

    all_results = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "region": REGION,
            "file_size_mb": FILE_SIZE // (1024 * 1024),
            "cpu_count": cpu_count(),
        },
        "standard": [],
        "express": [],
    }

    # Test Standard bucket
    all_results["standard"] = run_optimization_tests(BUCKET_STD, "S3 STANDARD")

    # Test Express bucket
    all_results["express"] = run_optimization_tests(BUCKET_EXPRESS, "S3 EXPRESS ONE ZONE")

    # Find best configs
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)

    for btype in ["standard", "express"]:
        print(f"\n  --- {btype.upper()} ---")
        data = all_results[btype]
        if not data:
            continue

        uploads = [r for r in data if r["type"] == "upload"]
        gets = [r for r in data if r["type"] == "get"]

        if uploads:
            best_up = max(uploads, key=lambda x: x["throughput_mbps"])
            print(f"  Best Upload: {best_up['throughput_mbps']} MB/s ({best_up['strategy']})")

        if gets:
            best_get = max(gets, key=lambda x: x["throughput_mbps"])
            print(f"  Best GET:    {best_get['throughput_mbps']} MB/s ({best_get['strategy']})")

    # Save results
    with open("/tmp/s3_optimization_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n✅ Results saved to /tmp/s3_optimization_results.json")


if __name__ == "__main__":
    multiprocessing.set_start_method("fork", force=True)
    main()
