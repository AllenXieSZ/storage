# Phase 2 — Resource Inventory (KEPT, no cleanup)

**Date:** 2026-09-18  **Region:** us-east-2 (Ohio)  **Account:** 386094880462  **TS:** 1789712716

## EC2
| Role | Instance ID | Type | Subnet | Notes |
|------|-------------|------|--------|-------|
| Client (bench) | i-007d7c253abfdaf79 | c7i.4xlarge | subnet-0ebad2264c331f72b (2a) | root gp3 100GB 8000 IOPS/500 MB/s; local source at /data/nixpkgs-src |
| Redis (JuiceFS meta) | i-0686f9747e8fc2462 | c7i.4xlarge | subnet-0ebad2264c331f72b (2a) | redis6 on 0.0.0.0:6379; private IP 172.31.0.220 |

- Key pair: `ohio`
- Instance profile: `fio-i7i-ssm-profile` (role fio-i7i-ssm-role)
- SG: `sg-02fa308849e231f60` (kernel-bench-p2-sg) — self-ref all TCP + egress

## Storage
| Type | ID | Detail |
|------|-----|--------|
| EFS | fs-09329ceebbfab3588 | elastic throughput, encrypted; MT fsmt-01053768aa31abfbf (2a) |
| S3 Files | fs-024f076414cc341b5 | prefix s3files/; AP fsap-0e71e7eb28b275488; MT fsmt-01918732937d48c86; role kernel-bench-p2-s3files-role |
| JuiceFS | redis://172.31.0.220:6379/1, name=myjfs | data on S3 bucket prefix myjfs/ |
| S3 bucket | kernel-bench-p2-1789712716 | versioning ENABLED; prefixes s3files/ + juicefs/ (+ myjfs/ used by JuiceFS) |

## IAM
- Role `kernel-bench-p2-s3files-role` (trust elasticfilesystem.amazonaws.com), inline policy `s3access` → s3:* on the bucket.

## Mount commands (on client i-007d7c253abfdaf79)
```
# EFS optimized
mount -t efs -o tls,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600 fs-09329ceebbfab3588:/ /mnt/efs_opt

# S3 Files optimized
mount -t s3files -o tls,iam,accesspoint=fsap-0e71e7eb28b275488,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600 fs-024f076414cc341b5:/ /mnt/s3files

# JuiceFS format + optimized mount
juicefs format --storage s3 --bucket https://kernel-bench-p2-1789712716.s3.us-east-2.amazonaws.com redis://172.31.0.220:6379/1 myjfs
juicefs mount --writeback --attr-cache 300 --entry-cache 300 --dir-entry-cache 300 --cache-size 10240 --buffer-size 1024 redis://172.31.0.220:6379/1 /mnt/juicefs_opt -d

# EBS reference (local root gp3)
# clone target /data/clone_ebs (root xfs volume)
```

## Mountpoints
- /mnt/efs_opt (EFS optimized)
- /mnt/s3files (S3 Files optimized)
- /mnt/juicefs_opt (JuiceFS optimized)
- /data (local EBS: nixpkgs-src source + clone_ebs target)
