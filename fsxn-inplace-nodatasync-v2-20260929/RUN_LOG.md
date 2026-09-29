# RUN_LOG.md — FSxN in-place upgrade (no DataSync) v2, 2026-09-29

Region: **us-east-2** | Account: **386094880462** | All timestamps **UTC**.
Order (v2): **create 1536/1HA/2TB → expand HA to 2HA → convert FlexGroup → expand ×16 → volume move → resize back 1TB** — fio running continuously the entire time.

## Resources
| Item | Value |
|---|---|
| FSx ONTAP file system | `fs-03e3f1619726ec2a8` (Gen2 SINGLE_AZ_2) |
| Initial config | ThroughputCapacity **1536 MB/s**, **1 HA pair**, **2048 GB** |
| SVM | `svm-0f887b1776733e7d3` (name `testsvm`), NFS IP `172.31.43.187` |
| Volume | `fsvol-0958a724071ab13c2` (name `testvol`), junction `/vol1`, FlexVol 1 TB, StorageEfficiency off |
| Mgmt endpoint | `172.31.39.198` (fsxadmin) |
| fio EC2 | `i-00912cbc0ac97b432` c6in.4xlarge, AL2023, **us-east-2c** (subnet-0c551a33e366d52d4, same AZ as FSx) |
| fio SG | `sg-065452b111d0ecef6` |
| FSxN SG | `sg-09ec422ed11229db2` |
| VPC | `vpc-0c28d2a9082ef222e` |

## Mount command (on fio EC2)
```
sudo mount -t nfs -o nfsvers=3,rsize=65536,wsize=65536,hard,timeo=600,retrans=2,nconnect=16 \
  172.31.43.187:/vol1 /mnt/fsxn
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

## AWS create commands
### Create file system (1536 MB/s, 1 HA pair, 2048 GB, Gen2 SINGLE_AZ_2)
```
aws fsx create-file-system --region us-east-2 --file-system-type ONTAP \
  --storage-capacity 2048 --subnet-ids subnet-0c551a33e366d52d4 \
  --security-group-ids sg-09ec422ed11229db2 --storage-type SSD \
  --ontap-configuration '{"DeploymentType":"SINGLE_AZ_2","ThroughputCapacityPerHAPair":1536,"HAPairs":1,"PreferredSubnetId":"subnet-0c551a33e366d52d4"}'
# fsxadmin password set via update-file-system --ontap-configuration '{"FsxAdminPassword":"<FSXADMIN_PASSWORD>"}'
```
### Create SVM + Volume
```
aws fsx create-storage-virtual-machine --region us-east-2 --file-system-id fs-03e3f1619726ec2a8 --name testsvm
aws fsx create-volume --region us-east-2 --volume-type ONTAP --name testvol \
  --ontap-configuration '{"StorageVirtualMachineId":"svm-0f887b1776733e7d3","JunctionPath":"/vol1","SizeInBytes":1099511627776,"StorageEfficiencyEnabled":false,"SecurityStyle":"UNIX","TieringPolicy":{"Name":"NONE"}}'
```

## ONTAP commands (via SSM → jumpbox i-0dffb881b2a90daa2 → sshpass fsxadmin@172.31.39.198)
Wrapper: `ontap_run.sh <mgmt-ip> "<cmd>"`. fsxadmin password = `<FSXADMIN_PASSWORD>`.

### 1. Expand HA 1 → 2 (no throughput change; already 1536) — AWS API
```
aws fsx update-file-system --region us-east-2 --file-system-id fs-03e3f1619726ec2a8 \
  --storage-capacity 4096 \
  --ontap-configuration '{"HAPairs":2,"ThroughputCapacityPerHAPair":1536}'
```
AWS requires StorageCapacity→4096 when HAPairs 1→2. **ThroughputCapacityPerHAPair kept at 1536** (no throughput upgrade). This created a second aggregate `aggr2`.
Aggregates after: `aggr1` (1.73 TB avail), `aggr2` (1.77 TB avail).

### 2. FlexVol → FlexGroup conversion (diag)
```
set -privilege diagnostic -confirmations off
volume conversion start -vserver testsvm -volume testvol -foreground true
```
Result: `[Job 68] Job succeeded: success` — produced single constituent `testvol__0001` on **aggr1**.

### 3. Expand constituents ×16 (2 aggrs × multiplier 8 = +16 → 17 total)
```
set -confirmations off
volume expand -vserver testsvm -volume testvol -aggr-list aggr1,aggr2 -aggr-list-multiplier 8 -foreground true
```
Result: FlexGroup grew from **1 constituent** to **17 constituents** (`testvol__0001` … `testvol__0017`, each 1 TB → logical ≈17 TB). Distribution: **aggr1=9, aggr2=8**.

### 4. Volume move (constituent `testvol__0001`, aggr1 → aggr2) on the expanded FlexGroup
Pre-move distribution confirmed via `volume show -vserver testsvm -is-constituent true -fields aggregate` (aggr1=9, aggr2=8). Chose to move the original constituent `testvol__0001` from the heavier aggr1 to aggr2.
```
volume move start -vserver testsvm -volume testvol__0001 -destination-aggregate aggr2
volume move show  -vserver testsvm -volume testvol__0001 -fields percent-complete,state
volume move trigger-cutover -vserver testsvm -volume testvol__0001 -force true   # forced final cutover
```
Under active fio the delta-sync oscillated 89–98 %; a forced cutover completed it (100 % done). Post-move distribution: **aggr1=8, aggr2=9**.

### 5. Resize back to original size (1 TB)
```
set -confirmations off
volume size -vserver testsvm -volume testvol 1TB
```
Result: `vol size: Volume "testsvm:testvol" size set to 1t.`

## Timeline (UTC)
| Event | Time (UTC) |
|---|---|
| fio start | 02:04:03 |
| **HA expand 1→2 start** | 02:06:33 |
| **HA expand 1→2 end** | 02:17:46 (~11m13s) |
| FlexVol→FlexGroup convert start | 02:18:10 |
| FlexVol→FlexGroup convert end | 02:18:35 (~25 s) |
| expand constituent ×16 start | 02:19:47 |
| expand constituent ×16 end | 02:21:25 (~1m38s) |
| **volume move start (aggr1→aggr2)** | **02:22:01** |
| **volume move end (forced cutover)** | **02:42:27** |
| **volume move duration** | **20m26s** |
| resize → 1 TB start | 02:43:16 |
| resize → 1 TB end | 02:43:47 (~31 s) |
| fio stop | 02:46:08 |

## Volume move detail
- Object moved: FlexGroup constituent `testvol__0001` (the original, only one on aggr1 before expand; after expand it was one of 9 on aggr1).
- Direction: **aggr1 → aggr2**.
- Duration under active fio: **20m26s** (delta-sync oscillated 89–98 %, completed with `trigger-cutover -force`).
- Effect: rebalanced constituent count from aggr1=9/aggr2=8 to **aggr1=8/aggr2=9**. `volume move` operates per-constituent (one constituent = one FlexVol-equivalent move); it is a full constituent relocation, not a data-balancing pass across the whole FlexGroup.

## Resize before/after
| | Size | Human | Constituents |
|---|---|---|---|
| Before resize (after ×16 expand) | 17 TB | ≈17 TiB | 17 |
| After resize | 1,102,360,223,744 B | ≈1.00 TiB | 17 (~60.2 GB each; two moved/original constituents 57.6–65.5 GB) |

## Log retrieval
fio log pulled off the private fio EC2 via S3: `gzip fio_run.log → s3://s3lambdatest2/fsxn-inplace-nodatasync-v2-20260929/raw/fio_run.log.gz → local`.
Parsed with `parse_fio_multi.py`; plotted with `plot_iops.py` (`iops_timeseries.png`).
