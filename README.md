# EBS Performance Benchmark Tool

Automated EBS performance testing tool that provisions EC2 instances + EBS volumes, runs [fio](https://github.com/axboe/fio) benchmarks, and generates an HTML report — all in one command.

## Features

- **Fully automated**: Creates EC2, attaches EBS, runs tests, generates report, cleans up
- **Multiple EBS types**: Compares gp3 vs io2 (easily extensible)
- **7 fio test scenarios**: Random/Sequential Read/Write, Latency, Mixed workload
- **Smart instance selection**: Picks the right EC2 size to match EBS performance requirements
- **HTML report**: AWS-styled visual report with comparison tables
- **Cleanup tool**: Safely removes all resources created by the benchmark

## Prerequisites

- **Python 3.8+**
- **boto3** — `pip3 install boto3`
- **AWS credentials** with sufficient IAM permissions (see [IAM Permissions Required](#iam-permissions-required))
- **Network**: The launched EC2 instance needs internet access so the SSM agent can register and fio can be installed via `yum`/`dnf`

> **Note**: You do **not** need to install AWS CLI or the SSM Session Manager plugin locally. All SSM interactions use the boto3 SDK (`ssm:SendCommand` / `ssm:GetCommandInvocation`), not `aws ssm start-session`.

## Quick Start

### On Amazon Linux 2023 / RHEL / Fedora

```bash
# Install pip and boto3
sudo yum install python3-pip -y
pip3 install boto3

# Clone the repo and run
git clone https://github.com/AllenXieSZ/storage.git
cd storage/ebs-bench
python3 ebs-bench.py --region us-east-1
```

### On Ubuntu / Debian

```bash
sudo apt update && sudo apt install python3-pip -y
pip3 install boto3

git clone https://github.com/AllenXieSZ/storage.git
cd storage/ebs-bench
python3 ebs-bench.py --region us-east-1
```

### Other Options

```bash
# Specify credentials explicitly
python3 ebs-bench.py --access-key AKIA... --secret-key ... --region us-east-2

# Use a named AWS profile
python3 ebs-bench.py --profile myprofile --region us-east-2
```

The tool will:
1. Create an IAM role with SSM access
2. Launch an EC2 instance (auto-selected for EBS performance)
3. Create and attach EBS volumes (gp3, io2)
4. Install fio via SSM
5. Run all benchmark tests
6. Generate JSON + HTML report
7. Terminate EC2 (volumes are cleaned up separately with `ebs-cleanup.py`)

## Test Scenarios

| Test | Block Size | Pattern | IO Depth | Jobs | Measures |
|------|-----------|---------|----------|------|----------|
| Random Read 4K | 4K | randread | 64 | 4 | IOPS |
| Random Write 4K | 4K | randwrite | 64 | 4 | IOPS |
| Sequential Read 1M | 1M | read | 32 | 4 | Throughput (MB/s) |
| Sequential Write 1M | 1M | write | 32 | 4 | Throughput (MB/s) |
| Random Read 4K (Latency) | 4K | randread | 1 | 1 | Latency (μs) |
| Random Write 4K (Latency) | 4K | randwrite | 1 | 1 | Latency (μs) |
| Mixed Random 70R/30W 4K | 4K | randrw (70/30) | 64 | 4 | Mixed IOPS |

All tests use `direct=1` (O_DIRECT) to bypass OS page cache.

## EBS Configurations

Default configurations (editable in `ebs-bench.py`):

| Config | Type | Size | IOPS | Throughput |
|--------|------|------|------|------------|
| gp3-20k | gp3 | 100 GiB | 20,000 | 1,000 MB/s |
| io2-20k | io2 | 100 GiB | 20,000 | Auto |

## fio Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| `--runtime` | 60s | Per test (configurable) |
| `--ramp_time` | 5s | Warm-up before measurement |
| `--size` | 20G | Test file size |
| `--ioengine` | libaio | Linux native async I/O |
| `--direct` | 1 | Bypass page cache |
| `--time_based` | yes | Run for full duration |

## EC2 Instance Auto-Selection

The tool automatically picks the smallest EC2 instance that can saturate the EBS volume:

| Max IOPS | Max Throughput | Instance |
|----------|---------------|----------|
| 10,000 | 593 MB/s | c6i.2xlarge |
| 20,000 | 1,187 MB/s | c6i.4xlarge |
| 40,000 | 2,375 MB/s | c6i.8xlarge |
| 80,000 | 5,000 MB/s | c6i.16xlarge |
| 160,000 | 10,000 MB/s | c6i.24xlarge |

## Output

- **JSON**: `ebs-report-{region}-{timestamp}.json` — Raw fio results
- **HTML**: `ebs-report-{region}-{timestamp}.html` — Visual comparison report

## Cleanup

If the benchmark is interrupted or you want to remove leftover resources:

```bash
# Dry run — show what would be deleted
python3 ebs-cleanup.py --region us-east-2 --dry-run

# Actually clean up
python3 ebs-cleanup.py --region us-east-2
```

The cleanup tool finds and removes:
- EC2 instances tagged `ebs-bench`
- EBS volumes tagged `ebs-bench`
- Security groups named `ebs-bench-*`
- IAM role and instance profile `ebs-bench-ssm-*`

## IAM Permissions Required

The AWS credentials you provide need:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances", "ec2:TerminateInstances", "ec2:DescribeInstances",
        "ec2:CreateVolume", "ec2:DeleteVolume", "ec2:AttachVolume",
        "ec2:DescribeVolumes", "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
        "ec2:CreateTags", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups",
        "ssm:SendCommand", "ssm:GetCommandInvocation", "ssm:DescribeInstanceInformation",
        "iam:CreateRole", "iam:DeleteRole", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile",
        "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
        "iam:PassRole", "iam:GetInstanceProfile"
      ],
      "Resource": "*"
    }
  ]
}
```

Or simply use `AdministratorAccess` for testing.

## Customization

Edit the constants at the top of `ebs-bench.py`:

```python
RUNTIME_SECONDS = 60        # fio duration per test
WARMUP_SECONDS = 10         # warmup before each test
FIO_FILE_SIZE = "20G"       # fio test file size
RAMP_TIME = 5               # fio ramp time

# Add/modify EBS configs
EBS_CONFIGS = [
    {
        "name": "gp3-custom",
        "volume_type": "gp3",
        "size_gib": 200,
        "iops": 16000,
        "throughput": 1000,
        "description": "gp3 — 200 GiB, 16K IOPS, 1 GB/s"
    },
]

# Add/modify fio tests
FIO_TESTS = [
    {
        "name": "rand-read-8k",
        "label": "Random Read 8K",
        "category": "IOPS",
        "bs": "8k",
        "rw": "randread",
        "iodepth": 128,
        "numjobs": 4,
        "direct": 1,
    },
]
```

## Example Report

Sample test on us-east-2 (2026-04-27):

| Metric | gp3 (20K IOPS) | io2 (20K IOPS) |
|--------|----------------|----------------|
| Random Read 4K IOPS | 20,014 | 19,987 |
| Random Write 4K IOPS | 19,892 | 19,901 |
| Seq Read 1M Throughput | 1,003 MB/s | 1,250 MB/s |
| Seq Write 1M Throughput | 998 MB/s | 1,248 MB/s |
| Random Read Latency p99 | 845 μs | 612 μs |

## Files

```
ebs-bench/
├── README.md           # This file
├── ebs-bench.py        # Main benchmark tool
├── ebs-cleanup.py      # Resource cleanup tool
└── ebs-report-*.html   # Generated reports
```

## Requirements

- Python 3.8+
- boto3 (`pip3 install boto3`)
- AWS account with EC2/EBS/SSM/IAM permissions (see [IAM Permissions Required](#iam-permissions-required))
- The launched EC2 instance needs internet access (SSM agent registration + fio install via yum/dnf)
- **Not required**: AWS CLI, SSM Session Manager plugin (all SSM ops use boto3 API, not CLI)

## License

MIT
