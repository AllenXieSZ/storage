# S3 Benchmark: Standard vs Express One Zone

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![AWS](https://img.shields.io/badge/AWS-S3%20%7C%20EC2%20%7C%20SSM-orange?logo=amazonaws)

Automated benchmark tool comparing **Amazon S3 Standard** and **S3 Express One Zone** performance.
Pure Python (boto3) — no AWS CLI required.

## What It Tests

### 1. Object I/O Latency
Single-object PUT and GET latency for:
- **4 KB** — small objects (metadata-heavy)
- **4 MB** — medium objects
- **8 MB** — larger objects

Each test runs 20 iterations, reporting avg, p50, p90, p99, min, max, and stddev.

### 2. Bucket Throughput (Optimized)
Large file (1 GB) transfer performance:
- **Multipart Upload** — parallel chunked upload (64 MB parts, 128 threads)
- **Range GET** — parallel byte-range reads (64 MB ranges, multiprocessing to bypass GIL)

Both tests run 3 rounds for consistency.

## Performance Optimization

Throughput was optimized by testing multiple strategies:

| Strategy | Upload | GET |
|----------|--------|-----|
| 8MB chunk / 16 threads (naive) | ~540 MB/s | ~565 MB/s |
| 64MB chunk / 128 threads | **~773 MB/s** | ~650 MB/s |
| 64MB chunk / multiprocessing | ~700 MB/s | **~1190 MB/s** |
| **Final (64MB + mp GET)** | **773 MB/s** | **1190 MB/s** |

Key optimizations:
1. **Larger chunks (64 MB)** — reduces request overhead by 8x vs 8MB
2. **Multiprocessing for GET** — Python GIL blocks `Body.read()` in threads; forking bypasses this
3. **Per-thread/process S3 clients** — avoids connection pool contention

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Your Machine (macOS / Linux / Windows)                 │
│  └─ run_benchmark.py (boto3 API calls only)             │
│       ├── Creates S3 Standard + Express One Zone bucket │
│       ├── Creates IAM Role + Instance Profile           │
│       ├── Launches EC2 (same AZ as Express bucket)      │
│       ├── Runs benchmark.py on EC2 via SSM              │
│       ├── Downloads HTML + JSON reports                 │
│       └── Cleans up ALL resources (trap on exit)        │
└─────────────────────────────────────────────────────────┘
```

**No SSH key needed** — uses AWS Systems Manager (SSM) for remote execution.  
**Cross-platform** — orchestrator runs on any OS; benchmark runs on remote Linux EC2.

## Prerequisites

- Python 3.8+
- `boto3` (`pip install boto3`)
- AWS credentials with admin-level permissions (EC2, S3, IAM, SSM)
- **Works on macOS, Linux, and Windows** — tested on all three platforms

## Quick Start

```bash
# macOS / Linux / Windows
pip install boto3
python run_benchmark.py
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `BENCH_REGION` | `us-east-2` | AWS region |
| `BENCH_AZ_ID` | `use2-az1` | AZ ID for Express bucket |
| `BENCH_INSTANCE_TYPE` | `c6in.2xlarge` | EC2 type (50 Gbps network) |
| `BENCH_ITERATIONS` | `20` | Latency test iterations |
| `BENCH_CONCURRENCY` | `128` | Upload thread count |

## Results (c6in.2xlarge, 50 Gbps, same AZ)

### Latency

| Size | Standard PUT | Express PUT | Δ | Standard GET | Express GET | Δ |
|------|-------------|-------------|---|-------------|-------------|---|
| 4 KB | 25 ms | **10 ms** | **-60%** | 25 ms | **5 ms** | **-79%** |
| 4 MB | 56 ms | **43 ms** | **-23%** | 48 ms | **28 ms** | **-42%** |
| 8 MB | 95 ms | **75 ms** | **-21%** | 95 ms | **58 ms** | **-38%** |

### Throughput (Optimized)

| Test | Standard | Express | Δ |
|------|----------|---------|---|
| Multipart Upload (1 GB) | 773 MB/s | **884 MB/s** | +14% |
| Range GET (1 GB) | 1190 MB/s | **1575 MB/s** | +32% |

> Express One Zone Range GET reached **1575 MB/s (12.6 Gbps)** — saturating the c6in.2xlarge network capacity.

## Transfer Accelerate Benchmarks

Besides the Standard vs Express comparison, this directory includes two scripts for benchmarking **S3 Transfer Accelerate**:

### s3_accelerate_upload.py — SDK Multipart Upload (Normal vs Accelerate)

Uses `boto3` `upload_file` with `TransferConfig` for multipart upload. Compares normal S3 endpoint vs Transfer Accelerate endpoint.

```bash
pip install boto3
python3 s3_accelerate_upload.py --bucket my-bucket --size 500
```

### s3_presigned_upload.py — Presigned URL Multipart Upload (Normal vs Accelerate)

Uses **Presigned URLs** + `requests.put` for each part — simulates browser/client-side upload without AWS credentials on the client.

```bash
pip install boto3 requests
python3 s3_presigned_upload.py --bucket my-bucket --size 500
```

### What is Transfer Accelerate?

S3 Transfer Accelerate routes uploads through the nearest CloudFront Edge Location, then via AWS backbone to the target bucket. Useful for cross-continent uploads (e.g., China → us-east-2). The actual speedup depends on network conditions — run the scripts to measure your specific environment.

📖 [Amazon S3 Transfer Acceleration User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/transfer-acceleration.html)

**Prerequisite:** Target bucket must have Transfer Accelerate enabled:
```bash
aws s3api put-bucket-accelerate-configuration \
  --bucket BUCKET --accelerate-configuration Status=Enabled
```

For detailed usage and parameters, see [README-accelerate.md](README-accelerate.md).

---

## CloudFront Signed URL Benchmarks

Compare **direct S3 PUT** vs **CloudFront Signed URL PUT** upload speed (single PUT, no multipart).

### cf_signed_url_upload.py — CloudFront Signed URL PUT vs S3 PUT

Uploads a file via direct S3 PUT and via CloudFront Signed URL PUT, then prints speed comparison.

```bash
pip install boto3 cryptography requests
python3 cf_signed_url_upload.py --size 500
```

### cf_signed_url_demo.py — S3 Upload + CloudFront Signed URL Download

Uploads file to S3 (multipart), generates a CloudFront Signed URL, then downloads via the signed URL. Demonstrates the full workflow.

```bash
python3 cf_signed_url_demo.py --size 500
```

### How CloudFront Signed URL PUT works

```
Your machine (Shenzhen)
    │
    │  HTTP PUT https://<CLOUDFRONT_ID>.cloudfront.net/key?Signature=xxx
    │  Body: [file data]
    │
    ▼
CloudFront Edge (nearest: Hong Kong/Guangzhou)
    │  ├─ Verify signature (RSA + Public Key)
    │  ├─ Check expiration
    │  └─ Forward PUT via AWS backbone
    ▼
S3 Bucket: zh-jlc (us-east-1)
    └─ Write object → return 200
```

**Key differences from S3 Presigned URL:**

| | S3 Presigned URL | CloudFront Signed URL |
|---|---|---|
| **Signing** | AWS SigV4 (HMAC-SHA256) | RSA-SHA1 (asymmetric key pair) |
| **Traffic path** | Client → S3 direct | Client → CF Edge → AWS backbone → S3 |
| **Acceleration** | None (unless Transfer Accelerate) | Edge node proximity + backbone |
| **Use case** | Backend-signed URL for frontend direct upload | Global distribution + CDN acceleration |

**Prerequisites:**
- CloudFront distribution must allow PUT in `AllowedMethods`
- A trusted key group with your RSA public key must be configured
- `cf_private_key.pem` must be present locally (not committed to git)
- Download it: `aws s3 cp s3://<BUCKET>/keys/cf_private_key.pem ./cf_private_key.pem`

📖 [CloudFront Signed URLs User Guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-signed-urls.html)

---

## Files

| File | Description |
|------|-------------|
| `run_benchmark.py` | Main entry — full lifecycle orchestrator (Standard vs Express) |
| `benchmark.py` | Core benchmark (runs on EC2) — latency + optimized throughput |
| `optimize_throughput.py` | Throughput optimization explorer (tests chunk/concurrency/process combos) |
| `s3_accelerate_upload.py` | Transfer Accelerate vs Normal — SDK multipart upload |
| `s3_presigned_upload.py` | Transfer Accelerate vs Normal — Presigned URL multipart upload |
| `cf_signed_url_upload.py` | CloudFront Signed URL PUT vs direct S3 PUT |
| `cf_signed_url_demo.py` | S3 upload + CloudFront Signed URL download demo |
| `README-accelerate.md` | Detailed documentation for Transfer Accelerate scripts |
| `sample_report.html` | Example HTML comparison report |

## How It Works

1. **You run** `python run_benchmark.py` on your laptop (macOS/Linux/Windows)
2. Script creates AWS resources (EC2, S3 buckets, IAM role, security group)
3. EC2 launches in the **same AZ** as the Express One Zone bucket
4. Benchmark executes on EC2 via **SSM** (no SSH needed)
5. HTML + JSON reports are downloaded to your local `reports/` directory
6. **All AWS resources are automatically deleted** (even if the script crashes)

## Cost

~10 minutes runtime, approximately **$0.10-0.15** (c6in.2xlarge on-demand). All resources auto-cleaned.

## License

MIT
