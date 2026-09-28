# RUN_LOG.md — FSxN in-place upgrade (no DataSync), 2026-09-28

Region: **us-east-2** | Account: **386094880462** | All timestamps **UTC**.

## Resources
| Item | Value |
|---|---|
| FSx ONTAP file system | `fs-0db43d5be0f77763f` (Gen2 SINGLE_AZ_2, ONTAP) |
| Initial config | ThroughputCapacity **1536 MB/s**, **1 HA pair**, **2048 GB** |
| SVM | `svm-0a8adbb726d0ee7e1` (name `testsvm`), NFS IP `172.31.40.216` |
| Volume | `fsvol-01720468375417426` (name `testvol`), junction `/vol1`, FlexVol 1 TB, StorageEfficiency off |
| Mgmt endpoint | `172.31.33.108` (fsxadmin) |
| fio EC2 | `i-018ba743b2b13cea4` c6in.4xlarge, AL2023, us-east-2b (see note), priv 172.31.28.43 |
| fio SG | `sg-0c9a3559bc188e145` |
| FSxN SG | `sg-0ce9e0af3f447aef3` |

> AZ note: FSx is in us-east-2c (subnet-0c551a33e366d52d4). c6in.4xlarge had InsufficientInstanceCapacity in 2c across retries, so the fio client launched in us-east-2b (same VPC vpc-0c28d2a9082ef222e). NFS traffic is cross-AZ within the VPC.

## Mount command (on fio EC2)
```
sudo mount -t nfs -o nfsvers=3,rsize=65536,wsize=65536,hard,timeo=600,retrans=2,nconnect=16 \
  172.31.40.216:/vol1 /mnt/fsxn
```

## fio job file (`fio_test.fio`) — exact, reproducible
```ini
[global]
ioengine=libaio
direct=1
time_based=1
runtime=10800
group_reporting=0
directory=/mnt/fsxn
size=4096MiB
numjobs=3
randrepeat=0

[randrw_4k]
rw=randrw
bs=4k
iodepth=32
rwmixread=70

[seqrw_1m]
rw=rw
bs=1M
iodepth=16
rwmixread=70
```
2 jobs × numjobs=3 = **6 processes total** (3× 4K randrw @ iodepth 32, 3× 1M seqrw @ iodepth 16), libaio, direct=1, 70/30 read/write.

### Exact launch command (run on fio EC2 as root)
```
cd /root
fio /root/fio_test.fio --status-interval=20 --output=/root/fio_run.log
```
`--status-interval=20` prints a cumulative snapshot of every job every 20 s; `parse_fio_multi.py` diffs consecutive per-pid cumulative counters and sums across the 6 pids to recover per-interval instantaneous IOPS/throughput.

### Stop
```
sudo pkill -INT fio
```

## ONTAP commands (via SSM → jumpbox i-0dffb881b2a90daa2 → sshpass fsxadmin@172.31.33.108)
Wrapper: `ontap_run.sh <mgmt-ip> "<cmd>"`. fsxadmin password = `<FSXADMIN_PASSWORD>`.

### 1. FlexVol → FlexGroup conversion (diag)
```
set -privilege diagnostic -confirmations off
volume conversion start -vserver testsvm -volume testvol -foreground true
```
Result: `[Job 46] Job succeeded: success` — produced single constituent `testvol__0001` on aggr1.

### 2. Expand HA 1 → 2 (no per-HA-pair throughput change) — AWS API
```
aws fsx update-file-system --region us-east-2 --file-system-id fs-0db43d5be0f77763f \
  --storage-capacity 4096 \
  --ontap-configuration '{"HAPairs":2,"ThroughputCapacityPerHAPair":1536}'
```
AWS requires StorageCapacity→4096 when HAPairs 1→2. **ThroughputCapacityPerHAPair kept at 1536** (no throughput upgrade). This created a second aggregate `aggr2`.

### 3. Volume move (aggr1 → aggr2) on the FlexGroup constituent
```
volume move start -vserver testsvm -volume testvol__0001 -destination-aggregate aggr2
volume move show  -vserver testsvm -volume testvol__0001 -fields percent-complete,state
volume move trigger-cutover -vserver testsvm -volume testvol__0001 -force true   # forced final cutover
```
Under active fio the delta-sync kept re-syncing (percent oscillated 89–98%); a forced cutover completed it. actual-completion-time = **17:27:47 UTC**.

### 4. Expand constituents ×16
Pre-req fix (new constituents inherited a conflicting compression config → first attempt failed):
```
volume efficiency modify -vserver testsvm -volume testvol -compression true -inline-compression true
```
Expand (8 per aggregate across both → +16 constituents):
```
set -confirmations off
volume expand -vserver testsvm -volume testvol -aggr-list aggr1,aggr2 -aggr-list-multiplier 8
```
Result: FlexGroup grew from **1 constituent (1 TB)** to **17 constituents (~17 TiB)** — i.e. +16 constituents (×16 more than the single original). Distribution: aggr1=8, aggr2=9.

### 5. Resize back to original size (1 TB)
```
set -confirmations off
volume size -vserver testsvm -volume testvol 1099511627776
```
Result: `Volume "testsvm:testvol" size set to 1t.` Final size 1100204236800 B (≈1 TiB; ONTAP rounds so the total divides evenly across 17 constituents ~60.2 GB each).

## Timeline (UTC)
| Event | Time (UTC) |
|---|---|
| fio start | 16:56:32 |
| FlexVol→FlexGroup convert start | 16:58:36 |
| FlexVol→FlexGroup convert end | 16:59:12 (~36 s) |
| HA expand 1→2 start | 16:59:33 |
| HA expand 1→2 end | 17:11:24 (~11m51s) |
| **volume move start** | **17:12:13** |
| **volume move end (cutover)** | **17:27:47** |
| **volume move duration** | **15m34s** |
| expand constituent ×16 start | 17:34:37 |
| expand constituent ×16 end | 17:42:34 (~7m57s) |
| resize → 1 TB start | 17:43:37 |
| resize → 1 TB end | 17:44:22 (~45 s) |
| fio stop | 17:47:50 |

## Resize before/after
| | Size (bytes) | Human | Constituents |
|---|---|---|---|
| Before resize (after ×16 expand) | 18,691,697,672,192 | ≈17 TiB | 17 |
| After resize | 1,100,204,236,800 | ≈1 TiB | 17 (~60.2 GB each) |

## Log retrieval
fio log pulled off the private fio EC2 via S3: `gzip fio_run.log → s3://s3lambdatest2/.../raw/fio_run.log.gz → local`.
Parsed with `parse_fio_multi.py`; plotted with `plot_iops.py`.
