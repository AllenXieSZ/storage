# RESOURCES — Phase 1 (mount-option tar benchmark)

**Date:** 2026-09-18  **Region:** us-east-2  **Account:** 386094880462

> ⚠️ Per final instruction (2026-09-18), **all Phase 1 resources below were DELETED after the run** (see cleanup
> confirmation at bottom). This file documents what was used.

## Resources used (reused the prior partial set + added an access point)

| Resource | ID | Notes |
|---|---|---|
| Client EC2 | `i-0b6c386131b978b8b` | c7i.4xlarge, AL2023, subnet 2a (subnet-0ebad2264c331f72b), 172.31.8.163; reused |
| EFS | `fs-038852c6b9dc878de` (kernel-bench-opt-efs) | MT `fsmt-0af180618ed37586a` @ 172.31.10.232 (2a) |
| S3 Files fs | `fs-02860f149ef6d6d4d` | bucket kernel-bench-opt-1789706736; role kernel-bench-opt-s3files-role |
| S3 Files MT | `fsmt-087e397a3cd7d5be1` | @ 172.31.13.162 (2a) |
| S3 Files AP | `fsap-0203d93b8b4eb6891` | **created this run** |
| Versioned bucket | `kernel-bench-opt-1789706736` | versioning enabled; also JuiceFS data (`kernelbench-jfs/`) |
| JuiceFS meta | redis6 on the client (127.0.0.1:6379 db1) | fs name `kernelbench-jfs` |
| Security Group | `sg-0d9207e44914198ce` (kernel-bench-opt-sg) | self-referencing all-traffic |
| IAM role | `kernel-bench-opt-s3files-role` | S3 Files service role (created by prior run, not this run) |

## Mount commands used

```bash
# EFS optimized (tls)
mount -t efs -o tls,noatime,nodiratime,rsize=1048576,wsize=1048576 fs-038852c6b9dc878de:/ /mnt/efs_opt
# EFS optimized + actimeo
mount -t efs -o tls,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600 fs-038852c6b9dc878de:/ /mnt/efs_act
# EFS nconnect=16 raw NFS (no tls) — PATHOLOGICAL / wedged
mount -t nfs4 -o nfsvers=4.1,noatime,nodiratime,nconnect=16,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport 172.31.10.232:/ /mnt/efs_nc
# S3 Files optimized
mount -t s3files -o tls,iam,accesspoint=fsap-0203d93b8b4eb6891,noatime,nodiratime,rsize=1048576,wsize=1048576 fs-02860f149ef6d6d4d:/ /mnt/s3files_opt
# S3 Files optimized + actimeo
mount -t s3files -o tls,iam,accesspoint=fsap-0203d93b8b4eb6891,noatime,nodiratime,rsize=1048576,wsize=1048576,actimeo=600 fs-02860f149ef6d6d4d:/ /mnt/s3files_act
# JuiceFS optimized
juicefs mount --writeback --attr-cache 300 --entry-cache 300 --dir-entry-cache 300 --cache-size 10240 --buffer-size 1024 redis://127.0.0.1:6379/1 /mnt/juicefs_opt -d
```

## Cleanup status
See the "资源已全部删除" confirmation appended by the cleanup step.
