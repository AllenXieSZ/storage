#!/usr/bin/env python3
"""
CloudFront Signed URL + S3 Upload Demo
通过 CloudFront Signed URL 上传 500MB 文件到 S3

流程:
  1. 先用 boto3 将文件上传到 S3 bucket (zh-jlc)
  2. 生成 CloudFront Signed URL 供下载验证
  
注意: CloudFront 标准配置不支持通过 Signed URL 上传（PUT）。
CloudFront Signed URL 主要用于受限下载（GET）场景。
如需通过 CloudFront 上传，需要配置 origin 允许 PUT 方法。

本脚本演示:
  - 方案A: 直接 S3 上传 + CloudFront Signed URL 下载
  - 方案B: 如果 distribution 允许 PUT，通过 Signed URL PUT 上传

支持平台: macOS / Linux / Windows (需要 Python 3.8+, boto3, cryptography)
"""

import boto3
import os
import sys
import time
import datetime
import argparse
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from botocore.signers import CloudFrontSigner


# ============ 配置 ============
CF_DOMAIN = "<CLOUDFRONT_DOMAIN>"
CF_KEY_PAIR_ID = "K3GBGTTVXQUCHQ"
PRIVATE_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cf_private_key.pem")
S3_BUCKET = "zh-jlc"
S3_REGION = "us-east-1"


def load_private_key(path):
    """加载 RSA private key"""
    with open(path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
    return private_key


def rsa_signer(message):
    """CloudFront 签名函数"""
    private_key = load_private_key(PRIVATE_KEY_PATH)
    return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())


def generate_signed_url(resource_url, expire_minutes=60):
    """生成 CloudFront Signed URL"""
    cf_signer = CloudFrontSigner(CF_KEY_PAIR_ID, rsa_signer)
    expire_date = datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes)
    signed_url = cf_signer.generate_presigned_url(resource_url, date_less_than=expire_date)
    return signed_url


def generate_test_file(path, size):
    """生成测试文件"""
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


def upload_to_s3(file_path, bucket, key):
    """上传文件到 S3"""
    from boto3.s3.transfer import TransferConfig

    s3 = boto3.client("s3", region_name=S3_REGION)
    file_size = os.path.getsize(file_path)

    config = TransferConfig(
        multipart_threshold=16 * 1024 * 1024,
        multipart_chunksize=16 * 1024 * 1024,
        max_concurrency=10,
    )

    uploaded_bytes = 0
    start_time = time.time()
    last_print = start_time

    def progress(bytes_transferred):
        nonlocal uploaded_bytes, last_print
        uploaded_bytes += bytes_transferred
        now = time.time()
        if now - last_print >= 2:
            pct = uploaded_bytes / file_size * 100
            speed = uploaded_bytes / (now - start_time) / 1024 / 1024
            print(f"    进度: {pct:.1f}% | 速度: {speed:.1f} MB/s")
            last_print = now

    s3.upload_file(file_path, bucket, key, Config=config, Callback=progress)
    elapsed = time.time() - start_time
    speed = file_size / elapsed / 1024 / 1024
    return elapsed, speed


def download_with_signed_url(signed_url, output_path):
    """通过 CloudFront Signed URL 下载文件"""
    import requests

    start_time = time.time()
    resp = requests.get(signed_url, stream=True)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    last_print = start_time

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if now - last_print >= 2:
                pct = downloaded / total * 100 if total else 0
                speed = downloaded / (now - start_time) / 1024 / 1024
                print(f"    进度: {pct:.1f}% | 速度: {speed:.1f} MB/s")
                last_print = now

    elapsed = time.time() - start_time
    speed = downloaded / elapsed / 1024 / 1024
    return elapsed, speed, downloaded


def main():
    parser = argparse.ArgumentParser(description="CloudFront Signed URL Upload/Download Demo")
    parser.add_argument("--size", type=int, default=500, help="测试文件大小 (MB), 默认 500")
    parser.add_argument("--key-path", default=PRIVATE_KEY_PATH, help="Private key 路径")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理 S3 对象")
    parser.add_argument("--download-only", action="store_true", help="只测试 Signed URL 下载（假设文件已在 S3）")
    args = parser.parse_args()

    key_path = args.key_path

    if not os.path.exists(key_path):
        print(f"错误: Private key 不存在: {key_path}")
        print(f"请确保 cf_private_key.pem 在脚本同目录下")
        sys.exit(1)

    file_size = args.size * 1024 * 1024
    s3_key = "test/cf-signed-upload-test.bin"
    cf_url = f"https://{CF_DOMAIN}/{s3_key}"

    print(f"\n{'='*60}")
    print(f"  CloudFront Signed URL Demo")
    print(f"{'='*60}")
    print(f"  Distribution: {CF_DOMAIN}")
    print(f"  S3 Bucket:    {S3_BUCKET} ({S3_REGION})")
    print(f"  Key Pair ID:  {CF_KEY_PAIR_ID}")
    print(f"  File Size:    {args.size} MB")
    print(f"{'='*60}")

    if not args.download_only:
        # Step 1: 生成测试文件
        test_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".test-cf-{args.size}mb.bin")
        generate_test_file(test_file, file_size)

        # Step 2: 上传到 S3
        print(f"\n{'─'*60}")
        print(f"  [1/3] 上传文件到 S3 (Multipart, 16MB parts, 10 并发)")
        print(f"  Target: s3://{S3_BUCKET}/{s3_key}")
        print(f"{'─'*60}")
        upload_time, upload_speed = upload_to_s3(test_file, S3_BUCKET, s3_key)
        print(f"  ✅ S3 上传完成 | 耗时: {upload_time:.2f}s | 速度: {upload_speed:.1f} MB/s")

        # 清理本地测试文件
        os.remove(test_file)

    # Step 3: 生成 Signed URL
    print(f"\n{'─'*60}")
    print(f"  [2/3] 生成 CloudFront Signed URL")
    print(f"{'─'*60}")
    signed_url = generate_signed_url(cf_url, expire_minutes=60)
    print(f"  ✅ Signed URL 生成成功 (有效期 60 分钟)")
    print(f"  URL: {signed_url[:100]}...")

    # Step 4: 通过 Signed URL 下载验证
    print(f"\n{'─'*60}")
    print(f"  [3/3] 通过 CloudFront Signed URL 下载")
    print(f"{'─'*60}")
    download_path = "/tmp/cf-download-test.bin"
    try:
        import requests
        dl_time, dl_speed, dl_size = download_with_signed_url(signed_url, download_path)
        print(f"  ✅ 下载完成 | 大小: {dl_size / 1024**2:.0f} MB | 耗时: {dl_time:.2f}s | 速度: {dl_speed:.1f} MB/s")
        os.remove(download_path)
    except ImportError:
        print(f"  ⚠️ 需要 requests 库: pip install requests")
        print(f"  手动测试: curl -o /tmp/test.bin '{signed_url}'")
    except Exception as e:
        print(f"  ❌ 下载失败: {e}")

    # 结果汇总
    print(f"\n{'='*60}")
    print(f"  📊 结果汇总")
    print(f"{'='*60}")
    if not args.download_only:
        print(f"  S3 上传:              {upload_time:.2f}s ({upload_speed:.1f} MB/s)")
    print(f"  CF Signed URL 下载:   {dl_time:.2f}s ({dl_speed:.1f} MB/s)")
    print(f"{'='*60}")

    # 清理 S3
    if not args.no_cleanup and not args.download_only:
        s3 = boto3.client("s3", region_name=S3_REGION)
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        print(f"\n  🧹 已清理 S3 测试对象")


if __name__ == "__main__":
    main()
