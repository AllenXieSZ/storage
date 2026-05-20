# S3 Transfer Accelerate Benchmark

## 简介

对比 **S3 Transfer Accelerate** 和普通 S3 Multipart Upload 的传输性能。

### 什么是 Transfer Accelerate？

S3 Transfer Accelerate 利用 Amazon CloudFront 的全球边缘节点加速数据传输。上传时，数据先到达距离客户端最近的 CloudFront Edge Location，然后通过 AWS 内部优化的骨干网传输到目标 S3 bucket。

```
普通上传:     客户端 ──── 公网 ────────────── S3 (us-east-2)
Accelerate:  客户端 ── Edge(最近) ── AWS骨干网 ── S3 (us-east-2)
```

**适用场景：**
- 跨洲/跨国大文件上传（如中国→美国，欧洲→亚太）
- 客户端网络到 S3 Region 延迟高的场景
- 大文件传输需要稳定高吞吐的场景

**不适用：**
- 同 Region 传输（已在 AWS 内部网络，无需加速）
- bucket 名称含 `.`（不支持）
- 纯下载场景（Accelerate 主要优化上传，下载建议用 CloudFront CDN）

**费用：**
- Transfer Accelerate 额外收费 $0.04/GB（加速有效时）
- 如果 Accelerate 比普通传输更慢，AWS 不收取加速费用

📖 **官方文档：** [Amazon S3 Transfer Acceleration User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/transfer-acceleration.html)

---

## 环境要求

- **Python**: 3.8+
- **依赖**: `boto3`
- **平台**: macOS / Linux / Windows
- **AWS**: 已配置 credentials (`~/.aws/credentials` 或环境变量)

```bash
pip install boto3
```

---

## 前置条件

目标 bucket 必须开启 Transfer Accelerate：

```bash
# 开启
aws s3api put-bucket-accelerate-configuration \
  --bucket YOUR_BUCKET \
  --accelerate-configuration Status=Enabled

# 验证
aws s3api get-bucket-accelerate-configuration --bucket YOUR_BUCKET
```

---

## 用法

```bash
# 默认: 1GB 文件，10 并发，64MB 分片
python3 s3_accelerate_upload.py

# 指定 bucket 和文件大小 (MB)
python3 s3_accelerate_upload.py --bucket my-bucket --size 512

# 调整并发线程和分片大小
python3 s3_accelerate_upload.py --concurrency 20 --part-size 32

# 只测试 Accelerate（跳过普通上传对比）
python3 s3_accelerate_upload.py --accelerate-only

# 使用已有文件
python3 s3_accelerate_upload.py --file /path/to/large-file.zip

# 测试完保留 S3 对象（不自动删除）
python3 s3_accelerate_upload.py --no-cleanup
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--bucket` | <BUCKET> | 目标 S3 bucket（须已开启 Accelerate） |
| `--size` | 1024 | 测试文件大小 (MB) |
| `--concurrency` | 10 | 并发上传线程数 |
| `--part-size` | 64 | Multipart 分片大小 (MB) |
| `--accelerate-only` | false | 只测试 Accelerate |
| `--no-cleanup` | false | 不清理 S3 测试对象 |
| `--file` | - | 使用已有文件 |

---

## 示例输出

```
============================================================
  S3 Multipart Upload 对比测试
  Bucket: <BUCKET>
  File: 1024 MB (1.00 GB)
  Part size: 64 MB | Concurrency: 10
============================================================

────────────────────────────────────────────────────────────
  [1/2] 普通 S3 Multipart Upload
────────────────────────────────────────────────────────────
  ✅ 完成 | 耗时: 15.30s | 速度: 66.9 MB/s

────────────────────────────────────────────────────────────
  [2/2] Transfer Accelerate Multipart Upload
────────────────────────────────────────────────────────────
  ✅ 完成 | 耗时: 7.93s | 速度: 129.1 MB/s

============================================================
  📊 对比结果
============================================================
  普通 S3 Multipart              15.30s      66.9 MB/s
  Transfer Accelerate             7.93s     129.1 MB/s
  ──────────────────────────────────────────────────────
  Accelerate 比普通快: +92.9% (比值: 1.93x)
============================================================
```

---

## 技术细节

- 使用 `boto3` 的 `TransferConfig` 配置 multipart 参数
- Accelerate 通过 `use_accelerate_endpoint: True` 启用，请求走 `bucket.s3-accelerate.amazonaws.com`
- 两种方式使用完全相同的 multipart 参数（分片大小、并发数），确保公平对比
- 测试完成后自动清理 S3 对象和本地临时文件
