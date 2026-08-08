#!/usr/bin/env python3
"""
CloudFront Signed URL 上传 vs 普通 S3 上传 速度对比
单次 PUT（无 multipart），对比:
  1. 普通 S3 PUT 上传
  2. CloudFront Signed URL PUT 上传

支持平台: macOS / Linux / Windows (需要 Python 3.8+, boto3, cryptography, requests)
"""

import boto3
import os
import sys
import time
import datetime
import argparse
import requests
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


def make_rsa_signer(key_path):
    """创建 CloudFront RSA 签名函数"""
    private_key = load_private_key(key_path)
    def _signer(message):
        return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())
    return _signer


def generate_cf_signed_url(resource_url, key_pair_id, key_path, expire_minutes=60):
    """生成 CloudFront Signed URL"""
    signer = CloudFrontSigner(key_pair_id, make_rsa_signer(key_path))
    expire_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=expire_minutes)
    signed_url = signer.generate_presigned_url(resource_url, date_less_than=expire_date)
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


def upload_s3_direct(file_path, bucket, key, region):
    """普通 S3 单次 PUT 上传（不分片）"""
    s3 = boto3.client("s3", region_name=region)
    file_size = os.path.getsize(file_path)

    start_time = time.time()
    with open(file_path, "rb") as f:
        s3.put_object(Bucket=bucket, Key=key, Body=f)
    elapsed = time.time() - start_time
    speed = file_size / elapsed / 1024 / 1024
    return elapsed, speed


def upload_cf_signed_url(file_path, signed_url):
    """通过 CloudFront Signed URL PUT 上传"""
    file_size = os.path.getsize(file_path)

    start_time = time.time()
    with open(file_path, "rb") as f:
        resp = requests.put(signed_url, data=f, headers={"Content-Type": "application/octet-stream"})
    elapsed = time.time() - start_time

    if resp.status_code not in (200, 201, 204):
        print(f"  ❌ CloudFront PUT 失败: HTTP {resp.status_code}")
        print(f"  Response: {resp.text[:500]}")
        return None, None

    speed = file_size / elapsed / 1024 / 1024
    return elapsed, speed


def main():
    parser = argparse.ArgumentParser(
        description="CloudFront Signed URL PUT vs 普通 S3 PUT 上传速度对比（无分片）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 cf_signed_url_upload.py
  python3 cf_signed_url_upload.py --size 100
  python3 cf_signed_url_upload.py --key-path /path/to/cf_private_key.pem

注意:
  - 需要 CloudFront distribution 允许 PUT 方法
  - 需要 cf_private_key.pem 在脚本同目录下
  - pip install boto3 cryptography requests
        """,
    )
    parser.add_argument("--size", type=int, default=500, help="测试文件大小 (MB), 默认 500")
    parser.add_argument("--key-path", default=PRIVATE_KEY_PATH, help="CloudFront private key 路径")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理 S3 对象")
    args = parser.parse_args()

    key_path = args.key_path
    if not os.path.exists(key_path):
        print(f"错误: Private key 不存在: {key_path}")
        print(f"请确保 cf_private_key.pem 在脚本同目录下")
        sys.exit(1)

    file_size = args.size * 1024 * 1024
    s3_key_normal = "test/normal-put-upload.bin"
    s3_key_cf = "test/cf-signed-put-upload.bin"
    cf_url = f"https://{CF_DOMAIN}/{s3_key_cf}"

    # 生成测试文件
    test_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".test-cf-put-{args.size}mb.bin")
    generate_test_file(test_file, file_size)

    print(f"\n{'='*60}")
    print(f"  CloudFront Signed URL PUT vs 普通 S3 PUT 上传对比")
    print(f"  （单次 PUT，无 Multipart 分片）")
    print(f"{'='*60}")
    print(f"  S3 Bucket:     {S3_BUCKET} ({S3_REGION})")
    print(f"  CF Domain:     {CF_DOMAIN}")
    print(f"  File Size:     {args.size} MB")
    print(f"  Key Pair ID:   {CF_KEY_PAIR_ID}")
    print(f"{'='*60}")

    # Test 1: 普通 S3 PUT
    print(f"\n{'─'*60}")
    print(f"  [1/2] 普通 S3 PUT 上传")
    print(f"  Endpoint: {S3_BUCKET}.s3.{S3_REGION}.amazonaws.com")
    print(f"{'─'*60}")
    normal_time, normal_speed = upload_s3_direct(test_file, S3_BUCKET, s3_key_normal, S3_REGION)
    print(f"  ✅ 完成 | 耗时: {normal_time:.2f}s | 速度: {normal_speed:.1f} MB/s")

    # Test 2: CloudFront Signed URL PUT
    print(f"\n{'─'*60}")
    print(f"  [2/2] CloudFront Signed URL PUT 上传")
    print(f"  Endpoint: {CF_DOMAIN}")
    print(f"{'─'*60}")
    signed_url = generate_cf_signed_url(cf_url, CF_KEY_PAIR_ID, key_path, expire_minutes=60)
    print(f"  Signed URL 已生成 (有效期 60 分钟)")
    cf_time, cf_speed = upload_cf_signed_url(test_file, signed_url)

    if cf_time is not None:
        print(f"  ✅ 完成 | 耗时: {cf_time:.2f}s | 速度: {cf_speed:.1f} MB/s")

    # 对比结果
    print(f"\n{'='*60}")
    print(f"  📊 对比结果（单次 PUT，无分片）")
    print(f"{'='*60}")
    print(f"  {'方式':<35} {'耗时':>8} {'速度':>12}")
    print(f"  {'─'*57}")
    print(f"  {'普通 S3 PUT':<35} {normal_time:>7.2f}s {normal_speed:>9.1f} MB/s")
    if cf_time is not None:
        print(f"  {'CloudFront Signed URL PUT':<35} {cf_time:>7.2f}s {cf_speed:>9.1f} MB/s")
        print(f"  {'─'*57}")
        if normal_speed > 0:
            diff_pct = (cf_speed - normal_speed) / normal_speed * 100
            ratio = cf_speed / normal_speed
            if diff_pct >= 0:
                print(f"  CloudFront 比 S3 快: +{diff_pct:.1f}% (比值: {ratio:.2f}x)")
            else:
                print(f"  CloudFront 比 S3 慢: {diff_pct:.1f}% (比值: {ratio:.2f}x)")
    print(f"{'='*60}")

    print(f"\n  💡 说明:")
    print(f"     - CloudFront PUT 走最近的 Edge Location → AWS 骨干网 → S3 Origin")
    print(f"     - 跨洲场景（如深圳→us-east-1）CloudFront 可能有明显提升")
    print(f"     - 同 Region 场景提升取决于网络路径差异")
    print(f"     - 具体效果以实际测试为准")

    # 清理
    if not args.no_cleanup:
        s3 = boto3.client("s3", region_name=S3_REGION)
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key_normal)
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key_cf)
        print(f"\n  🧹 已清理 S3 测试对象")

    # 清理本地文件
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"  🧹 已清理本地测试文件")


if __name__ == "__main__":
    main()
