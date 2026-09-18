# RESOURCES — Phase 3 (npm install bench) — KEPT, NOT CLEANED UP

**Date:** 2026-09-18  **Region:** us-east-2 (Ohio)  **Account:** 386094880462

## Resource inventory

| Resource | ID / Value |
|---|---|
| VPC | vpc-0c28d2a9082ef222e (default) |
| Subnet (2a) | subnet-0ebad2264c331f72b |
| Security Group | **sg-0e094a3bd85791026** (kernel-bench-p3-sg; self-ref all TCP + egress all) |
| AMI | ami-0d4dbb113bd1c81b2 (AL2023 x86_64) |
| EC2-A (client) | **i-0d62135b964578d14** (c7i.4xlarge, gp3 100GB 8000 IOPS/500MB/s, priv IP 172.31.14.107) |
| EC2-B (redis) | **i-0ccdb249eaded90df** (c7i.4xlarge, gp3 30GB, priv IP **172.31.15.79**) |
| Redis endpoint | redis://172.31.15.79:6379/1 (JuiceFS meta, DB 1) |
| S3 bucket (versioned) | **kernel-bench-p3-20260918062516** (prefixes: s3files/ , p3jfs/ , artifacts/) |
| EFS | **fs-0a5f43311aecee082** (elastic throughput, encrypted) |
| EFS mount target (2a) | fsmt-0b18b440b8a4a7acc |
| S3 Files FS | **fs-01c7f37fab49d4e9b** (prefix s3files/, NFSv4.2) |
| S3 Files mount target (2a) | fsmt-0abe65d6c87c50fc9 |
| S3 Files access point | **fsap-03e2e0e78e6c08c1a** |
| S3 Files IAM role | kernel-bench-p3-s3files-role (arn:aws:iam::386094880462:role/kernel-bench-p3-s3files-role) |
| Instance profile | fio-i7i-ssm-profile (role fio-i7i-ssm-role) |
| Key pair | ohio (no local .pem — drive via SSM) |
| JuiceFS volume name | p3jfs (formatted on redis DB1 + S3 data at s3://<bucket>/p3jfs/) |

## Drive the client via SSM
```bash
aws ssm start-session --target i-0d62135b964578d14 --region us-east-2
# or AWS-RunShellScript send-command
```

## Reuse mount commands (run on EC2-A as root)

### EBS (local reference — root fs is xfs noatime)
```bash
mkdir -p /mnt/ebs   # on root gp3 volume, already noatime
```

### EFS
```bash
# default
mount -t efs -o tls fs-0a5f43311aecee082:/ /mnt/efs
# optimized
mount -t efs -o tls,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600 fs-0a5f43311aecee082:/ /mnt/efs_opt
```

### S3 Files
```bash
# default
mount -t s3files -o tls,iam,accesspoint=fsap-03e2e0e78e6c08c1a fs-01c7f37fab49d4e9b:/ /mnt/s3files
# optimized
mount -t s3files -o tls,iam,accesspoint=fsap-03e2e0e78e6c08c1a,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600 fs-01c7f37fab49d4e9b:/ /mnt/s3files_opt
```

### JuiceFS (redis on EC2-B, S3 data). Already formatted as p3jfs.
```bash
# (re-format only if wiped)  juicefs format --storage s3 \
#   --bucket https://kernel-bench-p3-20260918062516.s3.us-east-2.amazonaws.com \
#   redis://172.31.15.79:6379/1 p3jfs
# default
juicefs mount redis://172.31.15.79:6379/1 /mnt/juicefs -d
# optimized (writeback + caches)
juicefs mount --writeback --attr-cache 300 --entry-cache 300 --dir-entry-cache 300 \
  --cache-size 10240 --buffer-size 1024 redis://172.31.15.79:6379/1 /mnt/juicefs_opt -d
```

## Workload reuse
- `package.json` + `package-lock.json` stored in this dir and in `s3://kernel-bench-p3-20260918062516/artifacts/`.
- Node.js v18.20.8 LTS, npm 10.8.2 installed on EC2-A. npm cache primed at `/root/.npm` (~712 MB).
- Runner: `/root/run_bench.sh <mountpoint> <label>` copies package.json+lock into `<mp>/npmrun_<label>`,
  drops caches, then `/usr/bin/time -v npm install --prefer-offline --no-audit --no-fund`.

## Results summary
| Storage | Mount | npm install | files | opt vs default |
|---|---|---|---|---|
| EBS gp3 | local noatime | 13.1 s | 66,513 | reference |
| EFS | default | 223.1 s | 66,513 | — |
| EFS | optimized | 228.8 s | 66,513 | −2.6% |
| S3 Files | default | 239.4 s | 66,513 | — |
| S3 Files | optimized | 238.8 s | 66,513 | +0.3% |
| JuiceFS | default | 432.1 s | 66,513 | — |
| JuiceFS | optimized (writeback) | 103.1 s | 66,513 | +76.1% |

**RESOURCES ARE KEPT — DO NOT CLEAN UP.**
