#!/usr/bin/env python3
"""
S3 Presigned URL + Multipart Upload 对比测试
对比 普通 Endpoint 和 Transfer Accelerate Endpoint 的 Presigned URL 上传速度

支持平台: macOS / Linux / Windows (需要 Python 3.8+ , boto3, requests)
"""

import boto3
import os
import sys
import time
import argparse
import hashlib
import base64
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def generate_test_file(path, size):
    """生成指定大小的测试文件"""
    if os.path.exists(path) and os.path.getsize(path) == size:
        print(f"测试文件已存在: {path} ({size / 1024**3:.2f} GB)")
        return
    print(f"生成 {size / 1024**2:.0f} MB 测试文件...")
    chunk = os.urandom(1024 * 1024)  # 1MB random data
    written = 0
    with open(path, "wb") as f:
        while written < size:
            to_write = min(len(chunk), size - written)
            f.write(chunk[:to_write])
            written += to_write
    print(f"文件生成完成: {path}")


def presigned_multipart_upload(file_path, bucket, key, part_size, concurrency, use_accelerate=False):
    """
    使用 Presigned URL 进行 Multipart Upload
    流程:
      1. CreateMultipartUpload
      2. 为每个 part 生成 presigned URL
      3. 并发 PUT 上传每个 part（用 requests，模拟客户端行为）
      4. CompleteMultipartUpload
    """

    config_kwargs = {}
    if use_accelerate:
        config_kwargs["s3"] = {"use_accelerate_endpoint": True}

    s3_client = boto3.client("s3", config=boto3.session.Config(**config_kwargs))

    file_size = os.path.getsize(file_path)
    num_parts = (file_size + part_size - 1) // part_size

    # Step 1: Create Multipart Upload
    mpu = s3_client.create_multipart_upload(Bucket=bucket, Key=key)
    upload_id = mpu["UploadId"]

    try:
        # Step 2: Generate presigned URLs for each part
        presigned_urls = []
        for part_num in range(1, num_parts + 1):
            url = s3_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_num,
                },
                ExpiresIn=3600,
            )
            presigned_urls.append((part_num, url))

        # Step 3: Upload parts concurrently using requests
        parts = []
        uploaded_bytes = 0
        start_time = time.time()
        last_print_time = start_time
        lock = __import__("threading").Lock()

        def upload_part(part_num, url, data):
            nonlocal uploaded_bytes, last_print_time
            resp = requests.put(url, data=data)
            resp.raise_for_status()
            etag = resp.headers["ETag"]
            with lock:
                uploaded_bytes += len(data)
                now = time.time()
                if now - last_print_time >= 2:
                    pct = uploaded_bytes / file_size * 100
                    speed = uploaded_bytes / (now - start_time) / 1024 / 1024
                    print(f"    进度: {pct:.1f}% ({uploaded_bytes / 1024**2:.0f} MB) | 速度: {speed:.1f} MB/s")
                    last_print_time = now
            return {"PartNumber": part_num, "ETag": etag}

        with open(file_path, "rb") as f:
            futures = []
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                for part_num, url in presigned_urls:
                    data = f.read(part_size)
                    if not data:
                        break
                    futures.append(executor.submit(upload_part, part_num, url, data))

                for future in as_completed(futures):
                    parts.append(future.result())

        # Sort parts by part number
        parts.sort(key=lambda x: x["PartNumber"])

        # Step 4: Complete Multipart Upload
        s3_client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

        elapsed = time.time() - start_time
        speed = file_size / elapsed / 1024 / 1024
        return elapsed, speed

    except Exception as e:
        # Abort on failure
        s3_client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        raise e


def main():
    parser = argparse.ArgumentParser(
        description="S3 Presigned URL + Multipart Upload 对比测试 (Normal vs Accelerate)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 默认: 500MB, 16MB 分片, 10 并发
  python3 s3_presigned_upload.py

  # 指定 bucket 和大小
  python3 s3_presigned_upload.py --bucket my-bucket --size 1024

  # 调整并发和分片
  python3 s3_presigned_upload.py --concurrency 20 --part-size 8

注意:
  - 目标 bucket 必须已开启 Transfer Accelerate
  - 需要安装: pip install boto3 requests
  - AWS credentials 需通过环境变量或 ~/.aws/credentials 配置
        """,
    )
    parser.add_argument("--bucket", default="<BUCKET>", help="S3 bucket 名称 (须已开启 Accelerate)")
    parser.add_argument("--size", type=int, default=500, help="测试文件大小 (MB), 默认 500")
    parser.add_argument("--concurrency", type=int, default=10, help="并发上传线程数, 默认 10")
    parser.add_argument("--part-size", type=int, default=16, help="分片大小 (MB), 默认 16")
    parser.add_argument("--accelerate-only", action="store_true", help="只测试 Accelerate")
    parser.add_argument("--no-cleanup", action="store_true", help="测试完不删除 S3 对象")
    parser.add_argument("--file", default=None, help="使用已有文件而非生成随机文件")

    args = parser.parse_args()

    file_size = args.size * 1024 * 1024
    part_size = args.part_size * 1024 * 1024
    bucket = args.bucket
    concurrency = args.concurrency

    # 测试文件
    if args.file:
        file_path = args.file
        if not os.path.exists(file_path):
            print(f"错误: 文件不存在: {file_path}")
            sys.exit(1)
        file_size = os.path.getsize(file_path)
    else:
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".test-presigned-{args.size}mb.bin")
        generate_test_file(file_path, file_size)

    key_normal = "test/presigned-normal-upload.bin"
    key_accel = "test/presigned-accelerate-upload.bin"

    print(f"\n{'='*60}")
    print(f"  S3 Presigned URL + Multipart Upload 对比测试")
    print(f"{'='*60}")
    print(f"  Bucket:      {bucket}")
    print(f"  File:        {file_size / 1024**2:.0f} MB ({file_size / 1024**3:.2f} GB)")
    print(f"  Part size:   {args.part_size} MB ({file_size // part_size} parts)")
    print(f"  Concurrency: {concurrency}")
    print(f"  Method:      Presigned URL + Multipart (requests.put)")
    print(f"{'='*60}")

    normal_time = normal_speed = None

    # 普通 Presigned URL 上传
    if not args.accelerate_only:
        print(f"\n{'─'*60}")
        print(f"  [1/2] 普通 Endpoint Presigned Multipart Upload")
        print(f"  URL 格式: https://{bucket}.s3.amazonaws.com/...?X-Amz-Signature=...")
        print(f"{'─'*60}")
        normal_time, normal_speed = presigned_multipart_upload(
            file_path, bucket, key_normal, part_size, concurrency, use_accelerate=False
        )
        print(f"  ✅ 完成 | 耗时: {normal_time:.2f}s | 速度: {normal_speed:.1f} MB/s")

    # Accelerate Presigned URL 上传
    step = "1/1" if args.accelerate_only else "2/2"
    print(f"\n{'─'*60}")
    print(f"  [{step}] Transfer Accelerate Presigned Multipart Upload")
    print(f"  URL 格式: https://{bucket}.s3-accelerate.amazonaws.com/...?X-Amz-Signature=...")
    print(f"{'─'*60}")
    accel_time, accel_speed = presigned_multipart_upload(
        file_path, bucket, key_accel, part_size, concurrency, use_accelerate=True
    )
    print(f"  ✅ 完成 | 耗时: {accel_time:.2f}s | 速度: {accel_speed:.1f} MB/s")

    # 对比结果
    print(f"\n{'='*60}")
    print(f"  📊 对比结果 (Presigned URL + Multipart)")
    print(f"{'='*60}")
    print(f"  {'方式':<40} {'耗时':>8} {'速度':>12}")
    print(f"  {'─'*62}")
    if normal_speed is not None:
        print(f"  {'普通 Presigned Multipart':<40} {normal_time:>7.2f}s {normal_speed:>9.1f} MB/s")
    print(f"  {'Accelerate Presigned Multipart':<40} {accel_time:>7.2f}s {accel_speed:>9.1f} MB/s")

    if normal_speed is not None and normal_speed > 0:
        print(f"  {'─'*62}")
        ratio = accel_speed / normal_speed
        diff_pct = (accel_speed - normal_speed) / normal_speed * 100
        if diff_pct >= 0:
            print(f"  Accelerate 比普通快: +{diff_pct:.1f}% (比值: {ratio:.2f}x)")
        else:
            print(f"  Accelerate 比普通慢: {diff_pct:.1f}% (比值: {ratio:.2f}x)")

    print(f"{'='*60}")

    print(f"\n  💡 说明: Transfer Accelerate 的提升幅度取决于网络条件：")
    print(f"     - 同 Region / 低延迟网络: 提升有限")
    print(f"     - 跨洲高延迟网络（如中国→美东）: 可能有较明显提升")
    print(f"     - 网络质量差/丢包率高的环境: 提升相对明显")
    print(f"     具体提升幅度以实际测试结果为准，不同环境差异较大。")

    # 清理
    if not args.no_cleanup:
        s3 = boto3.client("s3")
        if not args.accelerate_only:
            s3.delete_object(Bucket=bucket, Key=key_normal)
        s3.delete_object(Bucket=bucket, Key=key_accel)
        print(f"\n  🧹 已清理 S3 测试对象")

    # 清理临时文件
    if not args.file and os.path.exists(file_path):
        os.remove(file_path)
        print(f"  🧹 已清理本地测试文件")


if __name__ == "__main__":
    main()
