# EBS Performance Benchmark

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![AWS](https://img.shields.io/badge/AWS-EBS%20%7C%20EC2%20%7C%20SSM-orange?logo=amazonaws)

Automated EBS performance benchmark using **fio**. Provisions EC2 + EBS volumes, runs comprehensive I/O tests, generates an HTML report, and cleans up all resources.

## What It Tests

| Category | Test | Block Size | IO Depth | Jobs |
|----------|------|-----------|----------|------|
| **IOPS** | Random Read | 4K | 64 | 4 |
| **IOPS** | Random Write | 4K | 64 | 4 |
| **Throughput** | Sequential Read | 1M | 32 | 4 |
| **Throughput** | Sequential Write | 1M | 32 | 4 |
| **Latency** | Random Read (single) | 4K | 1 | 1 |
| **Latency** | Random Write (single) | 4K | 1 | 1 |
| **Mixed** | 70% Read / 30% Write | 4K | 64 | 4 |

Tests run on **raw block device** (no filesystem overhead). Each test runs for 60 seconds with 5-second ramp.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Your Machine (macOS / Linux / Windows)         │
│  └─ ebs-bench.py (boto3 API calls only)         │
│       ├── Selects optimal EC2 instance type     │
│       ├── Creates IAM Role + Instance Profile   │
│       ├── Launches EC2 (Nitro, SSM enabled)     │
│       ├── Creates & attaches EBS volume(s)      │
│       ├── Runs fio tests via SSM                │
│       ├── Generates HTML + JSON report          │
│       └── Cleans up ALL resources               │
└─────────────────────────────────────────────────┘
```

**No SSH key needed** — uses AWS Systems Manager (SSM).  
**Cross-platform** — orchestrator runs anywhere; fio runs on remote EC2.

## Prerequisites

- Python 3.8+
- `boto3` (`pip install boto3`)
- AWS credentials (env vars, `~/.aws/credentials`, or `--profile`)

## Quick Start

```bash
pip install boto3

# Using default credentials
python ebs-bench.py --region us-east-2

# Using a named profile
python ebs-bench.py --region us-east-2 --profile myprofile

# Using explicit keys
python ebs-bench.py --region us-east-2 --access-key AKIA... --secret-key ...
```

## Configuration

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--region` | *required* | AWS region |
| `--runtime` | `60` | fio runtime per test (seconds) |
| `--profile` | — | AWS CLI profile |
| `--access-key` / `--secret-key` | — | Explicit credentials |
| `--no-cleanup` | off | Skip cleanup (for debugging) |

### Volume Configs (edit in code)

Default tests two volume types:

```python
EBS_CONFIGS = [
    {"name": "gp3-20k", "volume_type": "gp3", "size_gib": 100, "iops": 20000, "throughput": 1000},
    {"name": "io2-20k", "volume_type": "io2", "size_gib": 100, "iops": 20000},
]
```

Add/modify entries to test different configurations (gp2, io1, st1, sc1, etc.)

### Instance Auto-Selection

The script automatically selects the smallest EC2 instance that can drive the requested EBS performance:

| Max IOPS | Max Throughput | Instance |
|----------|---------------|----------|
| 10,000 | 593 MB/s | c6i.2xlarge |
| 20,000 | 1,187 MB/s | c6i.4xlarge |
| 40,000 | 2,375 MB/s | c6i.8xlarge |
| 80,000 | 5,000 MB/s | c6i.16xlarge |
| 160,000 | 10,000 MB/s | c6i.24xlarge |

## Example Results

### gp3 — 100 GiB, 20,000 IOPS, 1,000 MB/s

| Test | IOPS | BW (MB/s) | Lat p50 (µs) | Lat p99 (µs) |
|------|------|-----------|-------------|-------------|
| Random Read 4K | 19,980 | 78 | 828 | 10,944 |
| Random Write 4K | 19,967 | 78 | 776 | 12,256 |
| Sequential Read 1M | 942 | 987 | 4,300 | 142,000 |
| Sequential Write 1M | 938 | 983 | 4,400 | 145,000 |
| Random Read 4K (Latency) | 3,842 | 15 | 236 | 388 |
| Random Write 4K (Latency) | 3,690 | 14 | 243 | 556 |

## Output

After a successful run:
- `ebs-report-{region}-{timestamp}.html` — Visual HTML report (dark theme)
- `ebs-report-{region}-{timestamp}.json` — Raw fio data + parsed metrics

See [`samples/`](./samples/) for example output reports (HTML + JSON).

## Cost

~15-20 minutes runtime depending on number of volume configs. Cost is primarily EC2 on-demand pricing for the duration (~$0.20-$0.50). All resources are automatically deleted.

## Cleanup Script

If a previous run was interrupted, use `ebs-cleanup.py` to remove leftover resources:

```bash
python ebs-cleanup.py --region us-east-2
```

## License

MIT
