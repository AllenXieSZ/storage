# ⚠️ 2026-08-30 已清理（DELETED）
> 小帅确认后已删除本实验全部 EC2 + FSx ONTAP（含卷/SVM/DataSync task+location）。以下清单仅存档。

# RESOURCES — backup-flexgroup-rootcause (H1 verification)

Region: us-east-2 | ONTAP 9.18.1P5 | Gen2 SINGLE_AZ_2 | task 2026-08-30

## AWS Resources (all tagged project=storage-bench-agent, taskId=backup-flexgroup-rootcause)
- FSxN file system: fs-0123456789abcdef0 (1HA / 1536 MB/s / 2048GB SSD)
  - Mgmt endpoint: 172.31.x.x  | fsxadmin pw: <redacted>
  - NFS endpoint: 172.31.x.x
- SVM: svm-01234567890abcdef (ONTAP name: bkpfgsvm)
- Volumes (FlexVol, 512GB, StorageEfficiency off, Tiering NONE):
  - bkpvol   = fsvol-0123456789abcdef  (junction /bkpvol)   → experiment: backed up once; **now FLEXGROUP after backup deleted (2026-08-30, REPORT2)**
  - cleanvol = fsvol-0123456789abcdef  (junction /cleanvol) → control: never backed up (flexgroup)
- FSx volume-level backup: backup-01aaa29249100f88b (of bkpvol) — **DELETED 2026-08-30 13:06 UTC (REPORT2 experiment); gone in ~10s API, backend copy-to-cloud released ~1min)**
- EC2: i-0e64df080d1d36235 (c6i.large, ohio key, SSM) — data loader
- SG: sg-0123456789abcdef0
- Subnet: subnet-0123456789abcdef (us-east-2a) | VPC vpc-0123456789abcdef0
- IAM: bkpfg-ssm-role (instance profile)

## Data
- Both volumes: 10 GiB = 100 files × 100 MiB (dd urandom)

## Status: resources RETAINED (delete only after 小帅 confirms)
