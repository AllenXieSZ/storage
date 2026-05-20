#!/usr/bin/env python3
"""
S3 Transfer Accelerate vs Normal Multipart Upload — 对比测试工具

对比 S3 Transfer Accelerate 和普通 Multipart Upload 的传输性能差异。
生成指定大小的测试文件，分别用两种方式上传，打印速度对比。

支持平台: macOS / Linux / Windows (需要 Python 3.8+ 和 boto3)
"""

import boto3
import os
import sys
import time
import argparse
from boto3.s3.transfer import TransferConfig


def generate_test_file(path, size):
    """生成指定大小的测试文件"""
    if os.path.exists(path) and os.path.getsize(path) == size:
        print(f"测试文件已存在: {path} ({size / 1024**3:.2f} GB)")
        return
    print(f"生成 {size / 1024**3:.2f} GB 测试文件...")
    chunk = os.urandom(1024 * 1024)  # 1MB random data
    written = 0
    with open(path, "wb") as f:
        while written < size:
            to_write = min(len(chunk), size - written)
            f.write(chunk[:to_write])
            written += to_write
    print(f"文件生成完成: {path}")


def upload_file(file_path, bucket, key, use_accelerate, concurrency, part_size):
    """上传文件，返回 (耗时秒, 速度MB/s)"""

    config_kwargs = {}
    if use_accelerate:
        config_kwargs["s3"] = {"use_accelerate_endpoint": True}

    s3_client = boto3.client("s3", config=boto3.session.Config(**config_kwargs))

    transfer_config = TransferConfig(
        multipart_threshold=part_size,
        multipart_chunksize=part_size,
        max_concurrency=concurrency,
        use_threads=True,
    )

    file_size = os.path.getsize(file_path)
    uploaded_bytes = 0
    start_time = time.time()
    last_print_time = start_time

    def progress_callback(bytes_transferred):
        nonlocal uploaded_bytes, last_print_time
        uploaded_bytes += bytes_transferred
        now = time.time()
        if now - last_print_time >= 2:
            pct = uploaded_bytes / file_size * 100
            speed = uploaded_bytes / (now - start_time) / 1024 / 1024
            print(f"    进度: {pct:.1f}% ({uploaded_bytes / 1024**2:.0f} MB) | 速度: {speed:.1f} MB/s")
            last_print_time = now

    s3_client.upload_file(
        Filename=file_path,
        Bucket=bucket,
        Key=key,
        Config=transfer_config,
        Callback=progress_callback,
    )

    elapsed = time.time() - start_time
    speed = file_size / elapsed / 1024 / 1024
    return elapsed, speed


def main():
    parser = argparse.ArgumentParser(
        description="S3 Transfer Accelerate vs Normal Multipart Upload 对比测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 默认: 上传 1GB 到 <BUCKET>
  python3 s3_accelerate_upload.py

  # 指定 bucket 和大小
  python3 s3_accelerate_upload.py --bucket my-bucket --size 512

  # 调整并发和分片大小
  python3 s3_accelerate_upload.py --concurrency 20 --part-size 32

  # 只测试 Accelerate（跳过普通上传）
  python3 s3_accelerate_upload.py --accelerate-only

注意:
  - 目标 bucket 必须已开启 Transfer Accelerate
  - 开启命令: aws s3api put-bucket-accelerate-configuration \\
      --bucket BUCKET --accelerate-configuration Status=Enabled
  - AWS credentials 需通过环境变量或 ~/.aws/credentials 配置
        """,
    )
    parser.add_argument("--bucket", default="<BUCKET>", help="S3 bucket 名称 (须已开启 Accelerate)")
    parser.add_argument("--size", type=int, default=1024, help="测试文件大小 (MB), 默认 1024 (1GB)")
    parser.add_argument("--concurrency", type=int, default=10, help="并发上传线程数, 默认 10")
    parser.add_argument("--part-size", type=int, default=64, help="分片大小 (MB), 默认 64")
    parser.add_argument("--accelerate-only", action="store_true", help="只测试 Accelerate, 跳过普通上传")
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
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".test-{args.size}mb.bin")
        generate_test_file(file_path, file_size)

    key_normal = "test/normal-upload.bin"
    key_accel = "test/accelerate-upload.bin"

    print(f"\n{'='*60}")
    print(f"  S3 Multipart Upload 对比测试")
    print(f"{'='*60}")
    print(f"  Bucket:      {bucket}")
    print(f"  File:        {file_size / 1024**2:.0f} MB ({file_size / 1024**3:.2f} GB)")
    print(f"  Part size:   {args.part_size} MB")
    print(f"  Concurrency: {concurrency}")
    print(f"{'='*60}")

    normal_time = normal_speed = None

    # 普通上传
    if not args.accelerate_only:
        print(f"\n{'─'*60}")
        print(f"  [1/2] 普通 S3 Multipart Upload")
        print(f"  Endpoint: {bucket}.s3.<region>.amazonaws.com")
        print(f"{'─'*60}")
        normal_time, normal_speed = upload_file(file_path, bucket, key_normal, False, concurrency, part_size)
        print(f"  ✅ 完成 | 耗时: {normal_time:.2f}s | 速度: {normal_speed:.1f} MB/s")

    # Accelerate 上传
    step = "1/1" if args.accelerate_only else "2/2"
    print(f"\n{'─'*60}")
    print(f"  [{step}] Transfer Accelerate Multipart Upload")
    print(f"  Endpoint: {bucket}.s3-accelerate.amazonaws.com")
    print(f"{'─'*60}")
    accel_time, accel_speed = upload_file(file_path, bucket, key_accel, True, concurrency, part_size)
    print(f"  ✅ 完成 | 耗时: {accel_time:.2f}s | 速度: {accel_speed:.1f} MB/s")

    # 对比结果
    print(f"\n{'='*60}")
    print(f"  📊 对比结果")
    print(f"{'='*60}")
    print(f"  {'方式':<30} {'耗时':>8} {'速度':>12}")
    print(f"  {'─'*54}")
    if normal_speed is not None:
        print(f"  {'普通 S3 Multipart':<30} {normal_time:>7.2f}s {normal_speed:>9.1f} MB/s")
    print(f"  {'Transfer Accelerate':<30} {accel_time:>7.2f}s {accel_speed:>9.1f} MB/s")

    if normal_speed is not None and normal_speed > 0:
        print(f"  {'─'*54}")
        ratio = accel_speed / normal_speed
        diff_pct = (accel_speed - normal_speed) / normal_speed * 100
        if diff_pct >= 0:
            print(f"  Accelerate 比普通快: +{diff_pct:.1f}% (比值: {ratio:.2f}x)")
        else:
            print(f"  Accelerate 比普通慢: {diff_pct:.1f}% (比值: {ratio:.2f}x)")

    print(f"{'='*60}")

    if normal_speed is not None and abs((accel_speed - normal_speed) / normal_speed * 100) < 20:
        print(f"\n  💡 提示: 当前机器可能与 bucket 在同 Region，")
        print(f"     Transfer Accelerate 对同 Region 传输提升有限。")
        print(f"     从远距离（如中国→us-east-2）上传时，提升通常 2-5x。")

    # 清理
    if not args.no_cleanup:
        s3 = boto3.client("s3")
        if not args.accelerate_only:
            s3.delete_object(Bucket=bucket, Key=key_normal)
        s3.delete_object(Bucket=bucket, Key=key_accel)
        print(f"\n  🧹 已清理 S3 测试对象")

    # 清理生成的临时文件
    if not args.file and os.path.exists(file_path):
        os.remove(file_path)
        print(f"  🧹 已清理本地测试文件")


if __name__ == "__main__":
    main()
