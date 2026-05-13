# AWS Storage Benchmarks

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![AWS](https://img.shields.io/badge/cloud-AWS-orange?logo=amazonaws)

A collection of automated storage performance benchmarking tools for AWS.
All tools are **pure Python (boto3)** — no AWS CLI required, cross-platform (macOS/Linux/Windows).

## Benchmarks

| Tool | What It Tests | Key Metrics |
|------|--------------|-------------|
| **[s3-benchmark](./s3-benchmark/)** | S3 Standard vs Express One Zone | Latency (4KB-8MB), Throughput (1GB multipart/range) |
| **[ebs-benchmark](./ebs-benchmark/)** | EBS volume types (gp3, io2, etc.) | IOPS, Throughput, Latency (via fio) |

## How They Work

1. **You run** the script on your laptop
2. Script provisions EC2 + storage resources in AWS
3. Benchmark executes on EC2 via **SSM** (no SSH needed)
4. HTML + JSON reports download to your machine
5. **All resources auto-cleaned** (even on crash/interrupt)

## Quick Start

```bash
pip install boto3

# S3 benchmark
cd s3-benchmark && python run_benchmark.py

# EBS benchmark
cd ebs-benchmark && python ebs-bench.py --region us-east-2
```

## Prerequisites

- Python 3.8+
- `boto3`
- AWS credentials with admin permissions

## License

MIT
