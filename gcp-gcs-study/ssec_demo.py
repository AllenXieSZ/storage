#!/usr/bin/env python3
"""
SSE-C (Server-Side Encryption with Customer-provided keys) demo on AWS S3.

演示要点：
1. 上传对象时，客户端自己带 256-bit key（S3 不存 key，只存 key 的 MD5 做校验）
2. 读取对象时，必须再次带同一把 key，否则读不出来
3. 对比三种读取：带正确 key / 不带 key / 带错误 key

Bucket: s3lambdatest2 (us-east-2)

============================================================================
⚠️ 实测结论（2026-09-02，本账号 386094880462 / allenxie@amazon.com）：
本账号在一个启用了 SCP 的 AWS Organization (o-wadx9m1bah) 下，
**组织级 SCP 全局禁用了 SSE-C 上传**。无论对 s3lambdatest2 还是全新建的
bucket，PutObject 带 SSE-C 都返回：
  AccessDenied ... "this bucket has blocked upload requests that specify
  Server Side Encryption with Customer provided keys (SSE-C).
  Please specify a different server-side encryption type."
这是 Amazon 内部安全合规策略（SSE-C 密钥完全客户自管、AWS 不留可审计痕迹，
内部通常禁用，强制改用 SSE-KMS 以便审计）。SCP 是账号/OU 级强制，IAM admin
也无法覆盖，无法绕过。
→ 因此本 demo 的 SSE-C 上传在此账号跑不通；代码逻辑本身正确，可在无此 SCP
  限制的普通账号上正常运行。若要在本账号演示"客户管理密钥"，应改用 SSE-KMS。
============================================================================
"""
import boto3
import os
import base64
import hashlib
from botocore.exceptions import ClientError

REGION = "us-east-2"
BUCKET = "s3lambdatest2"
KEY = "ssec-demo/hello-ssec.txt"
PLAINTEXT = b"Hello SSE-C! This object is encrypted with a customer-provided key.\n"

s3 = boto3.client("s3", region_name=REGION)


def gen_key():
    """生成 256-bit (32 字节) 随机密钥，SSE-C 要求。"""
    return os.urandom(32)


def key_b64(k):
    return base64.b64encode(k).decode()


def key_md5_b64(k):
    """S3 用 key 的 MD5(base64) 做完整性校验。"""
    return base64.b64encode(hashlib.md5(k).digest()).decode()


def upload(key_bytes):
    print("=== 1) 上传对象（带 SSE-C key）===")
    s3.put_object(
        Bucket=BUCKET,
        Key=KEY,
        Body=PLAINTEXT,
        SSECustomerAlgorithm="AES256",
        SSECustomerKey=key_b64(key_bytes),
        SSECustomerKeyMD5=key_md5_b64(key_bytes),
    )
    print(f"  上传成功: s3://{BUCKET}/{KEY}")
    print(f"  使用的 key(base64): {key_b64(key_bytes)}")
    print(f"  key MD5(base64):    {key_md5_b64(key_bytes)}\n")


def read_with_correct_key(key_bytes):
    print("=== 2) 读取：带【正确】key ===")
    try:
        r = s3.get_object(
            Bucket=BUCKET, Key=KEY,
            SSECustomerAlgorithm="AES256",
            SSECustomerKey=key_b64(key_bytes),
            SSECustomerKeyMD5=key_md5_b64(key_bytes),
        )
        data = r["Body"].read()
        print(f"  ✅ 读取成功，内容: {data!r}")
        print(f"  响应头确认加密方式: {r.get('SSECustomerAlgorithm')}\n")
    except ClientError as e:
        print(f"  ❌ 意外失败: {e}\n")


def read_without_key():
    print("=== 3) 读取：【不带】key（模拟普通 GET）===")
    try:
        r = s3.get_object(Bucket=BUCKET, Key=KEY)
        print(f"  ⚠️ 竟然读到了?! {r['Body'].read()!r}\n")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"  ❌ 如预期失败: {code} - {e.response['Error']['Message']}\n")


def read_with_wrong_key():
    print("=== 4) 读取：带【错误】key ===")
    wrong = gen_key()
    try:
        r = s3.get_object(
            Bucket=BUCKET, Key=KEY,
            SSECustomerAlgorithm="AES256",
            SSECustomerKey=key_b64(wrong),
            SSECustomerKeyMD5=key_md5_b64(wrong),
        )
        print(f"  ⚠️ 竟然读到了?! {r['Body'].read()!r}\n")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"  ❌ 如预期失败: {code} - {e.response['Error']['Message']}\n")


def show_head_without_key():
    print("=== 5) HEAD（不带 key）看元数据 ===")
    try:
        r = s3.head_object(Bucket=BUCKET, Key=KEY)
        print(f"  元数据: {r.get('SSECustomerAlgorithm')}\n")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"  ❌ HEAD 也需要 key: {code} - {e.response['Error']['Message']}\n")


if __name__ == "__main__":
    k = gen_key()
    upload(k)
    read_with_correct_key(k)
    read_without_key()
    read_with_wrong_key()
    show_head_without_key()
    print("=== 演示完成 ===")
    print("结论预期：只有带正确 key 才能读；不带/错 key 一律 400；S3 不存 key，丢 key = 数据永久无法解密。")
