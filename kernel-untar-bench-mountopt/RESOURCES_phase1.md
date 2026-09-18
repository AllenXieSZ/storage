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

## Cleanup status — 资源已全部删除 (2026-09-18)

All Phase 1 (P1) resources **and** the stuck Phase 2 / Phase 3 (P2/P3) leftovers were deleted and verified GONE:

**P1 (mine):**
- EC2 `i-0b6c386131b978b8b` (client) → terminated
- EC2 `i-025d6e9b90c64f050` (kernel-bench-opt-B-redis) → terminated
- S3 Files `fs-02860f149ef6d6d4d` (+ MT `fsmt-087e397a3cd7d5be1`, AP `fsap-0203d93b8b4eb6891`) → deleted
- EFS `fs-038852c6b9dc878de` (+ MT `fsmt-0af180618ed37586a`) → deleted (FileSystemNotFound confirmed)
- Bucket `kernel-bench-opt-1789706736` (~450k versions from JuiceFS blocks) → emptied + deleted
- SG `sg-0d9207e44914198ce` → deleted
- IAM role `kernel-bench-opt-s3files-role` → deleted

**P2/P3 leftovers (finished on requester's behalf):**
- S3 Files: `fs-01c7f37fab49d4e9b`, `fs-024f076414cc341b5`, `fs-0131f802710957f3e`, `fs-08ff887c0874cb5a1`
  (+ their MTs/APs `fsmt-0abe65d6c87c50fc9`/`fsap-03e2e0e78e6c08c1a`, `fsmt-01918732937d48c86`/`fsap-0e71e7eb28b275488`) → all deleted (force-delete where "pending export")
- Buckets `kernel-bench-p2-1789712716`, `kernel-bench-p3-20260918062516` → emptied + deleted
- SGs `sg-0e094a3bd85791026` (P3), `sg-02fa308849e231f60` (P2) → deleted
- IAM roles `kernel-bench-p2-s3files-role`, `kernel-bench-p3-s3files-role` → already gone

**Untouched (as required):** MySQL-Master `i-0dffb881b2a90daa2` and all other pre-existing resources.
`fio-i7i-ssm-role` left as-is (its S3Files/EFS client policies pre-dated this run; not added by me).

**Correct S3 Files delete API** (why `aws efs delete-file-system` failed with "does not exist"):
```
aws s3files delete-access-point  --region us-east-2 --access-point-id fsap-xxx
aws s3files delete-mount-target  --region us-east-2 --mount-target-id fsmt-xxx   # releases the ENI
aws s3files delete-file-system   --region us-east-2 --file-system-id fs-xxx [--force-delete]
```

