# S3 Benchmark: Standard vs Express One Zone

Automated benchmark tool comparing **Amazon S3 Standard** and **S3 Express One Zone** performance.

## What It Tests

### 1. Object I/O Latency
Single-object PUT and GET latency for:
- **4 KB** — small objects (metadata-heavy)
- **4 MB** — medium objects
- **8 MB** — larger objects

Each test runs 20 iterations, reporting avg, p50, p90, p99, min, max, and stddev.

### 2. Bucket Throughput
Large file (1 GB) transfer performance:
- **Multipart Upload** — parallel chunked upload (8 MB parts)
- **Range GET** — parallel byte-range reads (8 MB ranges)

Both tests use configurable concurrency (default: 64 threads) and run 3 rounds.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Your Machine (with AWS credentials)                    │
│  └─ run_benchmark.py                                    │
│       ├── Creates S3 Standard bucket                    │
│       ├── Creates S3 Express One Zone bucket            │
│       ├── Creates IAM Role + Instance Profile           │
│       ├── Launches EC2 (same AZ as Express bucket)      │
│       ├── Runs benchmark.py on EC2 via SSM              │
│       ├── Downloads HTML + JSON reports                 │
│       └── Cleans up ALL resources (trap on exit)        │
└─────────────────────────────────────────────────────────┘
```

**No SSH key needed** — uses AWS Systems Manager (SSM) for remote execution.

## Prerequisites

- Python 3.8+
- `boto3` (`pip install boto3`)
- AWS credentials with permissions:
  - `ec2:*` (launch/terminate instances, security groups)
  - `s3:*` + `s3express:CreateSession` (create/delete buckets, read/write objects)
  - `iam:*` (create roles, instance profiles)
  - `ssm:SendCommand`, `ssm:GetCommandInvocation` (remote execution)

## Quick Start

```bash
pip install boto3
python run_benchmark.py
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `BENCH_REGION` | `us-east-2` | AWS region |
| `BENCH_AZ_ID` | `use2-az1` | Availability Zone ID for Express bucket |
| `BENCH_INSTANCE_TYPE` | `c6in.2xlarge` | EC2 instance type (50 Gbps network) |
| `BENCH_ITERATIONS` | `20` | Number of latency test iterations |
| `BENCH_CONCURRENCY` | `64` | Parallel threads for throughput tests |

## Example Results

Tested on **c6in.2xlarge** (50 Gbps dedicated network), same AZ as Express bucket:

### Latency

| Object Size | Standard PUT | Express PUT | Δ | Standard GET | Express GET | Δ |
|-------------|-------------|-------------|---|-------------|-------------|---|
| 4 KB | 25 ms | **10 ms** | **-60%** | 25 ms | **5 ms** | **-79%** |
| 4 MB | 57 ms | **42 ms** | **-26%** | 48 ms | **28 ms** | **-42%** |
| 8 MB | 95 ms | **76 ms** | **-20%** | 94 ms | **60 ms** | **-37%** |

### Throughput

| Test | Standard | Express | Δ |
|------|----------|---------|---|
| Multipart Upload (1 GB) | ~650 MB/s | **~920 MB/s** | **+42%** |
| Range GET (1 GB) | ~570 MB/s | ~585 MB/s | +3% |

### Key Findings
- Express One Zone latency advantage is most dramatic for **small objects** (4 KB GET: 5x faster)
- Upload throughput consistently higher on Express (+40-60%)
- Range GET throughput is similar (likely bottlenecked by Python GIL at high concurrency)
- All results measured from EC2 in the **same AZ** as the Express bucket

## Files

| File | Description |
|------|-------------|
| `run_benchmark.py` | Main orchestrator — creates infra, runs test, generates report, cleans up |
| `benchmark.py` | Core benchmark logic — runs on EC2, measures latency & throughput |
| `sample_report.html` | Example HTML report output |

## Output

After a successful run:
- `reports/s3_bench_report.html` — Visual comparison report
- `reports/s3_bench_results.json` — Raw data (all latencies + throughput numbers)

## Cost

A typical run takes ~10 minutes and costs approximately **$0.10-0.15** (c6in.2xlarge on-demand + minimal S3 usage). All resources are automatically cleaned up after the test.

## License

MIT
