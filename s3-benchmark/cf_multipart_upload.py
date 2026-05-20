#!/usr/bin/env python3
"""
CloudFront Signed Cookie + Multipart Upload Demo
通过 CloudFront Signed Cookie 实现分片上传到 S3

流程:
  1. 生成 CloudFront Signed Cookie（覆盖 test/* 路径）
  2. 通过 CloudFront 发起 CreateMultipartUpload (POST)
  3. 通过 CloudFront 并发 PUT 每个 part
  4. 通过 CloudFront 发起 CompleteMultipartUpload (POST)

对比:
  - 普通 S3 PUT（单次，无分片）
  - CloudFront Signed Cookie + Multipart Upload

支持平台: macOS / Linux / Windows (需要 Python 3.8+, boto3, cryptography, requests)
"""

import boto3
import os
import sys
import time
import datetime
import argparse
import json
import hashlib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from botocore.signers import CloudFrontSigner
import requests
import threading


# ============ 配置 ============
CF_DOMAIN = "<CLOUDFRONT_ID>.cloudfront.net"
CF_KEY_PAIR_ID = "K3GBGTTVXQUCHQ"
PRIVATE_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cf_private_key.pem")
S3_BUCKET = "zh-jlc"
S3_REGION = "us-east-1"


def load_private_key(path):
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())


def make_rsa_signer(key_path):
    private_key = load_private_key(key_path)
    def _signer(message):
        return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())
    return _signer


def generate_signed_cookies(key_pair_id, key_path, cf_domain, resource_path="test/*", expire_minutes=60):
    """
    生成 CloudFront Signed Cookies (Set-Cookie 格式)
    使用 Custom Policy 覆盖通配路径，这样 multipart 的多个请求都能复用
    """
    signer = CloudFrontSigner(key_pair_id, make_rsa_signer(key_path))
    expire_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=expire_minutes)

    # Custom policy 覆盖通配路径
    resource = f"https://{cf_domain}/{resource_path}"
    policy = {
        "Statement": [{
            "Resource": resource,
            "Condition": {
                "DateLessThan": {"AWS:EpochTime": int(expire_date.timestamp())}
            }
        }]
    }

    # 用 CloudFrontSigner 的内部方法生成 signed cookie 组件
    policy_json = json.dumps(policy, separators=(",", ":"))
    policy_b64 = signer._url_b64encode(policy_json.encode("utf-8")).decode("utf-8")
    signature = signer._url_b64encode(
        signer.rsa_signer(policy_json.encode("utf-8"))
    ).decode("utf-8")

    cookies = {
        "CloudFront-Policy": policy_b64,
        "CloudFront-Signature": signature,
        "CloudFront-Key-Pair-Id": key_pair_id,
    }
    return cookies


def cf_multipart_upload(file_path, cf_domain, s3_key, cookies, part_size, concurrency):
    """
    通过 CloudFront + Signed Cookies 实现 Multipart Upload
    """
    base_url = f"https://{cf_domain}/{s3_key}"
    file_size = os.path.getsize(file_path)
    num_parts = (file_size + part_size - 1) // part_size

    session = requests.Session()
    session.cookies.update(cookies)

    # Step 1: CreateMultipartUpload (POST ?uploads)
    resp = session.post(f"{base_url}?uploads", headers={"Content-Type": "application/octet-stream"})
    if resp.status_code != 200:
        print(f"  ❌ CreateMultipartUpload 失败: HTTP {resp.status_code}")
        print(f"  Response: {resp.text[:500]}")
        return None, None

    # 解析 XML 获取 UploadId
    root = ET.fromstring(resp.text)
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    upload_id = root.find(".//s3:UploadId", ns)
    if upload_id is None:
        upload_id = root.find(".//{http://s3.amazonaws.com/doc/2006-03-01/}UploadId")
    if upload_id is None:
        # 尝试无 namespace
        upload_id = root.find(".//UploadId")
    upload_id_text = upload_id.text if upload_id is not None else None

    if not upload_id_text:
        print(f"  ❌ 无法解析 UploadId")
        print(f"  Response: {resp.text[:500]}")
        return None, None

    print(f"    UploadId: {upload_id_text[:20]}...")

    # Step 2: Upload parts concurrently
    parts = []
    uploaded_bytes = 0
    start_time = time.time()
    last_print_time = start_time
    lock = threading.Lock()

    def upload_part(part_num, data):
        nonlocal uploaded_bytes, last_print_time
        url = f"{base_url}?partNumber={part_num}&uploadId={upload_id_text}"
        resp = session.put(url, data=data)
        resp.raise_for_status()
        etag = resp.headers.get("ETag", "").strip('"')
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
            for part_num in range(1, num_parts + 1):
                data = f.read(part_size)
                if not data:
                    break
                futures.append(executor.submit(upload_part, part_num, data))

            for future in as_completed(futures):
                parts.append(future.result())

    parts.sort(key=lambda x: x["PartNumber"])

    # Step 3: CompleteMultipartUpload (POST)
    complete_xml = "<CompleteMultipartUpload>"
    for p in parts:
        complete_xml += f'<Part><PartNumber>{p["PartNumber"]}</PartNumber><ETag>"{p["ETag"]}"</ETag></Part>'
    complete_xml += "</CompleteMultipartUpload>"

    resp = session.post(
        f"{base_url}?uploadId={upload_id_text}",
        data=complete_xml,
        headers={"Content-Type": "application/xml"}
    )
    if resp.status_code != 200:
        print(f"  ❌ CompleteMultipartUpload 失败: HTTP {resp.status_code}")
        print(f"  Response: {resp.text[:500]}")
        return None, None

    elapsed = time.time() - start_time
    speed = file_size / elapsed / 1024 / 1024
    return elapsed, speed


def upload_s3_direct(file_path, bucket, key, region):
    """普通 S3 单次 PUT（对比基准）"""
    s3 = boto3.client("s3", region_name=region)
    file_size = os.path.getsize(file_path)
    start_time = time.time()
    with open(file_path, "rb") as f:
        s3.put_object(Bucket=bucket, Key=key, Body=f)
    elapsed = time.time() - start_time
    speed = file_size / elapsed / 1024 / 1024
    return elapsed, speed


def generate_test_file(path, size):
    if os.path.exists(path) and os.path.getsize(path) == size:
        print(f"测试文件已存在: {path} ({size / 1024**2:.0f} MB)")
        return
    print(f"生成 {size / 1024**2:.0f} MB 测试文件...")
    chunk = os.urandom(1024 * 1024)
    written = 0
    with open(path, "wb") as f:
        while written < size:
            to_write = min(len(chunk), size - written)
            f.write(chunk[:to_write])
            written += to_write
    print(f"文件生成完成: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="CloudFront Signed Cookie + Multipart Upload vs S3 PUT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 cf_multipart_upload.py --size 500
  python3 cf_multipart_upload.py --size 100 --part-size 8 --concurrency 5
        """,
    )
    parser.add_argument("--size", type=int, default=500, help="测试文件大小 (MB), 默认 500")
    parser.add_argument("--part-size", type=int, default=16, help="分片大小 (MB), 默认 16")
    parser.add_argument("--concurrency", type=int, default=10, help="并发线程数, 默认 10")
    parser.add_argument("--key-path", default=PRIVATE_KEY_PATH, help="CloudFront private key 路径")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理 S3 对象")
    args = parser.parse_args()

    key_path = args.key_path
    if not os.path.exists(key_path):
        print(f"错误: Private key 不存在: {key_path}")
        sys.exit(1)

    file_size = args.size * 1024 * 1024
    part_size = args.part_size * 1024 * 1024
    s3_key_normal = "test/normal-put.bin"
    s3_key_cf = "test/cf-multipart.bin"

    test_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".test-cfmp-{args.size}mb.bin")
    generate_test_file(test_file, file_size)

    print(f"\n{'='*60}")
    print(f"  CloudFront Multipart Upload vs S3 PUT 对比")
    print(f"{'='*60}")
    print(f"  S3 Bucket:     {S3_BUCKET} ({S3_REGION})")
    print(f"  CF Domain:     {CF_DOMAIN}")
    print(f"  File Size:     {args.size} MB")
    print(f"  Part Size:     {args.part_size} MB ({file_size // part_size} parts)")
    print(f"  Concurrency:   {args.concurrency}")
    print(f"{'='*60}")

    # Test 1: 普通 S3 PUT（单次，无分片）
    print(f"\n{'─'*60}")
    print(f"  [1/2] 普通 S3 PUT（单次上传，无分片）")
    print(f"{'─'*60}")
    normal_time, normal_speed = upload_s3_direct(test_file, S3_BUCKET, s3_key_normal, S3_REGION)
    print(f"  ✅ 完成 | 耗时: {normal_time:.2f}s | 速度: {normal_speed:.1f} MB/s")

    # Test 2: CloudFront Signed Cookie + Multipart
    print(f"\n{'─'*60}")
    print(f"  [2/2] CloudFront Signed Cookie + Multipart Upload")
    print(f"  Endpoint: {CF_DOMAIN}")
    print(f"{'─'*60}")

    # 生成 signed cookies
    cookies = generate_signed_cookies(CF_KEY_PAIR_ID, key_path, CF_DOMAIN, "test/*", expire_minutes=60)
    print(f"    Signed Cookies 已生成 (覆盖 test/*)")

    cf_time, cf_speed = cf_multipart_upload(test_file, CF_DOMAIN, s3_key_cf, cookies, part_size, args.concurrency)

    if cf_time is not None:
        print(f"  ✅ 完成 | 耗时: {cf_time:.2f}s | 速度: {cf_speed:.1f} MB/s")

        # 对比
        print(f"\n{'='*60}")
        print(f"  📊 对比结果")
        print(f"{'='*60}")
        print(f"  {'方式':<40} {'耗时':>8} {'速度':>12}")
        print(f"  {'─'*62}")
        print(f"  {'普通 S3 PUT（无分片）':<40} {normal_time:>7.2f}s {normal_speed:>9.1f} MB/s")
        print(f"  {'CloudFront Multipart（{0} parts）'.format(file_size//part_size):<40} {cf_time:>7.2f}s {cf_speed:>9.1f} MB/s")
        print(f"  {'─'*62}")
        if normal_speed > 0:
            diff_pct = (cf_speed - normal_speed) / normal_speed * 100
            ratio = cf_speed / normal_speed
            if diff_pct >= 0:
                print(f"  CloudFront Multipart 比 S3 PUT 快: +{diff_pct:.1f}% ({ratio:.2f}x)")
            else:
                print(f"  CloudFront Multipart 比 S3 PUT 慢: {diff_pct:.1f}% ({ratio:.2f}x)")
        print(f"{'='*60}")
    else:
        print(f"  ❌ CloudFront Multipart Upload 失败")

    print(f"\n  💡 说明:")
    print(f"     - CloudFront Multipart = Signed Cookie + 并发 PUT parts 经 CF Edge")
    print(f"     - 速度提升来自: 分片并发 + Edge 就近接入 + 骨干网传输")
    print(f"     - 具体效果以实际测试为准")

    # 清理
    if not args.no_cleanup:
        s3 = boto3.client("s3", region_name=S3_REGION)
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key_normal)
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key_cf)
        print(f"\n  🧹 已清理 S3 测试对象")

    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"  🧹 已清理本地测试文件")


if __name__ == "__main__":
    main()
