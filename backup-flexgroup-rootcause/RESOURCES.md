# RESOURCES — backup-flexgroup-rootcause (H1 verification)

Region: us-east-2 | ONTAP 9.18.1P5 | Gen2 SINGLE_AZ_2 | task 2026-08-30

## AWS Resources (all tagged project=storage-bench-agent, taskId=backup-flexgroup-rootcause)
- FSxN file system: fs-0184d1e4b81ce12a8 (1HA / 1536 MB/s / 2048GB SSD)
  - Mgmt endpoint: 172.31.11.231  | fsxadmin pw: <redacted>
  - NFS endpoint: 172.31.13.55
- SVM: svm-0af4df6f58574e440 (ONTAP name: bkpfgsvm)
- Volumes (FlexVol, 512GB, StorageEfficiency off, Tiering NONE):
  - bkpvol   = fsvol-0b96244abc8fcb7bd  (junction /bkpvol)   → experiment: backed up once; **now FLEXGROUP after backup deleted (2026-08-30, REPORT2)**
  - cleanvol = fsvol-0ff9b92f659a38ed5  (junction /cleanvol) → control: never backed up (flexgroup)
- FSx volume-level backup: backup-01aaa29249100f88b (of bkpvol) — **DELETED 2026-08-30 13:06 UTC (REPORT2 experiment); gone in ~10s API, backend copy-to-cloud released ~1min)**
- EC2: i-0e64df080d1d36235 (c6i.large, ohio key, SSM) — data loader
- SG: sg-093d35d24e799e2dc
- Subnet: subnet-0ebad2264c331f72b (us-east-2a) | VPC vpc-0c28d2a9082ef222e
- IAM: bkpfg-ssm-role (instance profile)

## Data
- Both volumes: 10 GiB = 100 files × 100 MiB (dd urandom)

## Status: resources RETAINED (delete only after 伟伟 confirms)
