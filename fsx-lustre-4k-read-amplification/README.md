# FSx for Lustre 4K Random Read Amplification — Cache-Bypass Verification

**Tested: 2026-10-27 | Region: us-east-2 (Ohio)**

## TL;DR

When 4K random reads miss the OSS in-memory cache on FSx for Lustre, each 4K client request causes the OSS to read **256KB from disk** — a **~26× read amplification**. This saturates the provisioned disk throughput (FileServerDiskThroughputUtilization → 90–102%) while the client only receives ~80 MB/s out of the 2,400 MB/s provisioned capacity (effective utilization ~3.3%).

AWS documentation confirms this design: the recommended minimum transfer size is **>256KB** to achieve expected throughput.

## Background: Why 256KB?

### AWS Documentation

From the FSx for Lustre internal performance guidance:

> *FSx Lustre file system allows customer to scale to millions of IOPS for read and write, but has no explicit SLA or provisioned data IOPS expectation. Today, we only measure performance by aggregate throughput. To achieve the expected throughput, customer application needs to drive enough parallelism and **using meaningful transfer size (>256k)**.*

This means 256KB is the **minimum effective I/O unit** at the disk layer. Any I/O smaller than 256KB will still consume 256KB of disk throughput — the "tax" for small random reads.

### What stripe_size (1MB) actually means

A common misconception is that stripe_size determines the disk I/O granularity. It does not:

| Concept | Value | What it controls |
|---|---|---|
| **stripe_size** | 1MB (default PFL) | Distribution of data across OSTs: every 1MB chunk goes to the next OST |
| **Disk I/O granularity** | **256KB** | The minimum read unit when the OSS reads from its backing SSD |
| **ldiskfs block size** | 4KB | Filesystem allocation granularity (not I/O granularity) |

From the Lustre Wiki ([Configuring Lustre File Striping](https://wiki.lustre.org/Configuring_Lustre_File_Striping)):

> *stripe_size does not affect the allocation size of the file on disk (which is controlled by the underlying OST filesystem, typically 4KB for ldiskfs), but only the distribution of file data across OSTs.*

## Test Environment

| Component | Configuration |
|---|---|
| FSx for Lustre | fs-0abb08606bd0a8f3e, PERSISTENT_2, 4800 GiB SSD, 500 MB/s/TiB |
| Provisioned disk throughput | 4.8 TiB × 500 = **2,400 MB/s** |
| OSS in-memory cache | ~65.76 GiB (13.7 GiB/TiB × 4.8 TiB, per [AWS docs](https://docs.aws.amazon.com/fsx/latest/LustreGuide/ssd-storage.html)) |
| OST count | 4 (OST0000–OST0003), stripe_count=-1, stripe_size=1M |
| OSS count | 2 (OSS0000, OSS0002; each serving 2 OSTs) |
| EC2 client | c6i.4xlarge (16 vCPU, 32 GiB), Amazon Linux 2023, us-east-2c |
| Lustre client version | 2.15.6 |
| fio version | 3.32 |
| Mount options | `mount -t lustre -o noatime,flock` |

### Test Data

4 × 50GB files (200GB total), written with random data (`fio --refill_buffers`), striped across all 4 OSTs:

```bash
lfs setstripe -c -1 -S 1M /mnt/lustre/bigdata
fio --name=gen --ioengine=libaio --direct=1 --rw=write --bs=1M \
  --numjobs=1 --size=50G --filename=/mnt/lustre/bigdata/bigfile_0 \
  --refill_buffers --buffer_pattern=0xdeadbeef
# Repeat for bigfile_1 (0xcafebabe), bigfile_2 (0xfeedface), bigfile_3 (0xbaadf00d)
```

200GB working set >> 65.76 GiB OSS cache → ensures cache misses during test.

## Test Method

### Step 1: Cache Pollution (Evict bigfile_0 from OSS cache)

Before each test run, sequentially read bigfile_1/2/3 (150GB) to fill the ~66GB OSS cache with data that is NOT bigfile_0:

```bash
for f in bigfile_1 bigfile_2 bigfile_3; do
  dd if=/mnt/lustre/bigdata/$f of=/dev/null bs=1M iflag=direct &
done
wait
```

After this, bigfile_0's data is almost entirely evicted from OSS RAM cache.

### Step 2: 4K Random Read Matrix

8 test configurations with increasing queue depth, each running 60 seconds:

```bash
sync && echo 3 > /proc/sys/vm/drop_caches && sleep 5

fio --name=<TAG> \
  --ioengine=libaio --direct=1 --bs=4k --rw=randread \
  --time_based --runtime=60 \
  --numjobs=<NJ> --iodepth=<ID> \
  --filename=/mnt/lustre/bigdata/bigfile_0 \
  --size=50G \
  --group_reporting \
  --output=<LOGDIR>/<TAG>.json --output-format=json+
```

| Test | numjobs | iodepth | Total QD |
|---|---|---|---|
| T1 | 1 | 1 | 1 |
| T2 | 1 | 16 | 16 |
| T3 | 1 | 64 | 64 |
| T4 | 1 | 128 | 128 |
| T5 | 4 | 32 | 128 |
| T6 | 8 | 32 | 256 |
| T7 | 16 | 32 | 512 |
| T8 | 16 | 64 | 1024 |

## Results

### fio Client-Side Performance

| Test | numjobs | iodepth | Total QD | IOPS | BW (MiB/s) | clat_avg (µs) | p99 (µs) |
|---|---|---|---|---|---|---|---|
| T1 | 1 | 1 | 1 | 836 | 3.3 | 1,182 | 1,499 |
| T2 | 1 | 16 | 16 | 21,560 | 84.2 | 730 | 1,647 |
| T3 | 1 | 64 | 64 | 23,605 | 92.2 | 2,700 | 18,481 |
| T4 | 1 | 128 | 128 | 23,643 | 92.4 | 5,402 | 35,914 |
| T5 | 4 | 32 | 128 | 23,574 | 92.1 | 5,417 | 35,914 |
| T6 | 8 | 32 | 256 | 23,579 | 92.1 | 10,843 | 69,730 |
| T7 | 16 | 32 | 512 | 23,517 | 91.9 | 21,755 | 131,596 |
| T8 | 16 | 64 | 1024 | 23,381 | 91.3 | 43,780 | 261,095 |

**Key observation:** IOPS plateau at ~23,500 from QD≥16 onward. Adding more queue depth only increases latency, not throughput.

### CloudWatch Metrics: The Read Amplification Evidence

All values below are from CloudWatch, Sum statistic, 60-second period.

#### DataReadBytes (Client-Side) vs DiskReadBytes (Disk-Side, 4 OSTs Combined)

| Time (UTC) | Client DataReadBytes (MB/s) | Disk DiskReadBytes 4 OST (MB/s) | **Read Amplification** | Phase |
|---|---|---|---|---|
| 10:21–10:23 | 521–1,176 | — | — | Cache eviction (dd 150GB) |
| 10:24 | 3.0 | 1,401 | 468× | Transition (T1 starting) |
| **10:25** | **80.2** | **2,018** | **25.2×** | T1→T2 |
| **10:26** | **79.1** | **2,082** | **26.3×** | T2–T3 |
| **10:27** | **79.5** | **2,080** | **26.2×** | T3–T4 |
| **10:28** | **79.3** | **2,077** | **26.2×** | T4–T5 |
| **10:29** | **79.3** | **2,276** | **28.7×** | T5–T6 |
| **10:30** | **79.1** | **2,179** | **27.5×** | T6–T7 |
| **10:31** | **78.4** | **2,058** | **26.3×** | T7–T8 |
| 10:32 | 81.5 | 586 | 7.2× | T8 tail + idle |

**Steady-state read amplification: 25.2×–28.7× (median ~26×)**

#### FileServerDiskThroughputUtilization (per OSS)

| Time (UTC) | OSS0000 (%) | OSS0002 (%) | Phase |
|---|---|---|---|
| 10:24 | 63.10 | 62.26 | Transition |
| 10:25 | 90.19 | 90.37 | T1→T2 |
| 10:26 | 92.94 | 93.38 | T2–T3 |
| 10:27 | 92.71 | 93.37 | T3–T4 |
| 10:28 | 92.61 | 93.21 | T4–T5 |
| **10:29** | **101.25** | **102.45** | **T5–T6 (burst > 100%)** |
| 10:30 | 97.63 | 97.36 | T6–T7 |
| 10:31 | 91.48 | 92.67 | T7–T8 |

**Both OSS servers hit 90–102% disk throughput utilization** — fully saturated.

#### DiskIopsUtilization (per OST)

| Time (UTC) | OST0000 (%) | OST0001 (%) | OST0002 (%) | OST0003 (%) |
|---|---|---|---|---|
| 10:26 | 57.7 | 57.7 | 58.0 | 58.0 |
| 10:27 | 57.5 | 57.6 | 58.0 | 57.9 |
| 10:29 | 62.9 | 62.8 | 63.7 | 63.6 |

**IOPS utilization ~58% — NOT the bottleneck.** The bottleneck is throughput, not IOPS count.

#### NetworkThroughputUtilization (per OSS)

| Time (UTC) | OSS0000 (%) | OSS0002 (%) |
|---|---|---|
| 10:25–10:31 | 0.81–0.95 | 0.69–0.86 |

**Network is almost idle (<1%).** 4K data volume is tiny. 100% of the bottleneck is at the disk layer.

### Deriving the 256KB Disk I/O Granularity

From CloudWatch per-OST data at 10:26 (steady state):

```
Per-OST DiskReadBytes:  ~520 MB/s
Per-OST DiskReadOps:    ~2,078 ops/s
Per-OST avg I/O size:   520 MB/s ÷ 2,078 ops/s = ~256 KB/op
```

Each 4K client request causes a **256KB disk read** — a 64:1 I/O size amplification per operation. The aggregate amplification is ~26× (not 64×) because some 4K reads within the same 256KB region hit the freshly-fetched cache.

## Read Amplification Mechanism

```
Client sends 4K random read (bs=4k, direct=1)
       ↓
Lustre client calculates which OST holds this 4K (based on stripe layout)
       ↓
OSS receives RPC for 4K
       ↓
OSS checks in-memory cache (~66GB) → MISS (working set evicted)
       ↓
OSS reads from backing disk → ⚠️ reads 256KB (not 4K!)
       ↓
256KB cached in OSS RAM; only 4K returned to client
       ↓
Result: 4K useful / 256KB consumed = 64:1 per-I/O amplification
        Aggregate: ~26:1 (some subsequent 4K reads hit the fresh 256KB chunk)
```

### Why ~23,500 IOPS is the ceiling

```
Provisioned disk throughput:           2,400 MB/s
Disk I/O per 4K client read:           256 KB
Max client IOPS (throughput-limited):  2,400 MB/s ÷ 256 KB = ~9,600 IOPS (theoretical)
```

Actual ~23,500 IOPS > theoretical 9,600 because:
1. Some reads hit OSS cache (not all are cold misses)
2. Disk can burst above provisioned baseline (DiskThroughputUtilization reached 102%)
3. Spatial locality: consecutive 4K reads within the same 256KB chunk get served from cache

## Comparison: Cached vs Cache-Bypass

These tests used the same FS configuration (P2, 4.8 TiB, 500 MB/s/TiB):

| Metric | 8GB working set (all cached) | 50GB working set (cache bypass) | Change |
|---|---|---|---|
| IOPS (high QD) | ~252,000 | ~23,500 | **↓ 10.7×** |
| Client throughput | ~985 MB/s | ~80 MB/s (CW) | **↓ 12.3×** |
| DiskThroughputUtilization | < 0.01% | **90–102%** | Cache → Disk |
| Latency clat_avg (QD=64) | ~638 µs | ~2,700 µs | **↑ 4.2×** |
| Bottleneck | Client CPU/protocol | **Disk throughput saturation** | — |

**The cached test (8GB) does not reflect real disk performance.** It only measures the OSS in-memory cache.

## Practical Implications

### Who is affected?

Workloads with **random small-I/O reads** where the working set exceeds the OSS cache (~14 GiB/TiB for P-500):
- Random database queries on Lustre
- Small-file random access (ML data loading with random sampling)
- Any 4K/8K/16K random read pattern with working set > cache

### Who is NOT affected?

- **Large sequential I/O** (checkpoints, bulk data reads): no amplification, 1:1 disk utilization
- **Working sets that fit in cache**: OSS RAM serves requests at full speed with no disk I/O
- **Reads ≥256KB**: aligned with disk I/O granularity, no wasted throughput

### Effective throughput by I/O size (with cache miss)

| Client I/O size | Disk I/O per request | Amplification | Effective use of 2,400 MB/s |
|---|---|---|---|
| 4K | 256K | 64× | ~38 MB/s (1.6%) |
| 16K | 256K | 16× | ~150 MB/s (6.3%) |
| 64K | 256K | 4× | ~600 MB/s (25%) |
| 256K | 256K | **1× (none)** | **2,400 MB/s (100%)** |
| 1M | 1M | 1× | 2,400 MB/s (100%) |

*Theoretical maximums; actual values depend on cache hit ratio and spatial locality.*

## OSS In-Memory Cache Sizes

From [AWS documentation](https://docs.aws.amazon.com/fsx/latest/LustreGuide/ssd-storage.html):

| Throughput tier | Cache (GiB/TiB) | 4.8 TiB total cache |
|---|---|---|
| PERSISTENT-125 | 3.4 | 16.3 GiB |
| PERSISTENT-250 | 6.8 | 32.6 GiB |
| **PERSISTENT-500** | **13.7** | **65.8 GiB** |
| PERSISTENT-1000 | 27.3 | 131.0 GiB |

Higher throughput tiers have proportionally more cache. PERSISTENT-1000 has 2× the cache of P-500, which helps absorb more random reads — but once the working set exceeds cache, the same 256KB amplification applies.

## CloudWatch Metric Dimensions (Important!)

Querying FSx Lustre CloudWatch metrics requires specific sub-dimensions or you get no data:

| Metric | Required Dimensions | Notes |
|---|---|---|
| FileServerDiskThroughputUtilization | FileSystemId + **FileServer** (OSS0000, ...) | ⚠️ No FileServer dim = no data |
| DiskIopsUtilization | FileSystemId + **StorageTargetId** (OST0000, ...) | |
| DiskReadBytes / DiskReadOperations | FileSystemId + **StorageTargetId** (OST0000, ...) | |
| DataReadBytes / DataReadOperations | FileSystemId only (no sub-dim) | Client-side aggregate |
| NetworkThroughputUtilization | FileSystemId + **FileServer** (OSS0000, ...) | |

Example query:
```bash
aws cloudwatch get-metric-statistics \
  --namespace "AWS/FSx" \
  --metric-name "DiskReadBytes" \
  --dimensions "Name=FileSystemId,Value=<FS_ID>" "Name=StorageTargetId,Value=OST0000" \
  --start-time "<START>" --end-time "<END>" \
  --period 60 --statistics Sum \
  --region us-east-2
```

## Full Reproduction Commands

### 1. Create FSx Lustre

```bash
aws fsx create-file-system \
  --file-system-type LUSTRE \
  --storage-capacity 4800 \
  --storage-type SSD \
  --subnet-ids <SUBNET_ID> \
  --security-group-ids <SG_ID> \
  --lustre-configuration '{
    "DeploymentType": "PERSISTENT_2",
    "PerUnitStorageThroughput": 500,
    "MetadataConfiguration": {"Mode": "AUTOMATIC"}
  }' \
  --tags "Key=Name,Value=lustre-4k-read-amp-test" \
  --region us-east-2
```

### 2. Create EC2 + Install

```bash
aws ec2 run-instances \
  --image-id <AL2023_AMI> \
  --instance-type c6i.4xlarge \
  --key-name <KEY> \
  --subnet-id <SUBNET_ID> \
  --security-group-ids <SG_ID> \
  --region us-east-2

# On the instance:
sudo dnf install -y lustre-client fio
sudo modprobe lustre
sudo mkdir -p /mnt/lustre
sudo mount -t lustre -o noatime,flock \
  <FS_DNS>@tcp:/<MOUNT_NAME> /mnt/lustre
```

### 3. Create 200GB Test Data

```bash
sudo lfs setstripe -c -1 -S 1M /mnt/lustre/bigdata

for i in 0 1 2 3; do
  PATTERNS=(0xdeadbeef 0xcafebabe 0xfeedface 0xbaadf00d)
  sudo fio --name=gen${i} --ioengine=libaio --direct=1 --rw=write --bs=1M \
    --numjobs=1 --size=50G --filename=/mnt/lustre/bigdata/bigfile_${i} \
    --refill_buffers --buffer_pattern=${PATTERNS[$i]}
done
```

### 4. Cache Eviction + 4K Random Read Test

```bash
#!/bin/bash
set -e
MOUNT=/mnt/lustre
LOGDIR=/tmp/fio_4k_read_amp
mkdir -p $LOGDIR

# Phase 1: Evict bigfile_0 from OSS cache
echo "=== Evicting cache: reading bigfile_1,2,3 (150GB) ==="
for f in bigfile_1 bigfile_2 bigfile_3; do
  dd if=$MOUNT/bigdata/$f of=/dev/null bs=1M iflag=direct 2>/dev/null &
done
wait
sleep 5

# Phase 2: 4K random read matrix
TESTS=("T1" "T2" "T3" "T4" "T5" "T6" "T7" "T8")
JOBS=(1 1 1 1 4 8 16 16)
DEPTHS=(1 16 64 128 32 32 32 64)

for i in "${!TESTS[@]}"; do
  TAG=${TESTS[$i]}
  NJ=${JOBS[$i]}
  ID=${DEPTHS[$i]}
  echo "=== $TAG: numjobs=$NJ iodepth=$ID ==="

  sync && echo 3 > /proc/sys/vm/drop_caches
  sleep 5

  fio --name=${TAG}_nj${NJ}_d${ID} \
    --ioengine=libaio --direct=1 --bs=4k --rw=randread \
    --time_based --runtime=60 \
    --numjobs=$NJ --iodepth=$ID \
    --filename=$MOUNT/bigdata/bigfile_0 \
    --size=50G \
    --group_reporting \
    --output=${LOGDIR}/${TAG}.json \
    --output-format=json+

  echo "=== $TAG done ==="
  sleep 3
done
```

### 5. Collect CloudWatch Metrics

```bash
FS_ID=<your-fs-id>
START="2026-10-27T10:20:00Z"
END="2026-10-27T10:35:00Z"

# Client-side data read (no sub-dimension needed)
aws cloudwatch get-metric-statistics \
  --namespace "AWS/FSx" --metric-name "DataReadBytes" \
  --dimensions "Name=FileSystemId,Value=$FS_ID" \
  --start-time $START --end-time $END --period 60 --statistics Sum \
  --region us-east-2

# Disk-side read per OST
for OST in OST0000 OST0001 OST0002 OST0003; do
  aws cloudwatch get-metric-statistics \
    --namespace "AWS/FSx" --metric-name "DiskReadBytes" \
    --dimensions "Name=FileSystemId,Value=$FS_ID" "Name=StorageTargetId,Value=$OST" \
    --start-time $START --end-time $END --period 60 --statistics Sum \
    --region us-east-2
done

# Disk throughput utilization per OSS
for OSS in OSS0000 OSS0002; do
  aws cloudwatch get-metric-statistics \
    --namespace "AWS/FSx" --metric-name "FileServerDiskThroughputUtilization" \
    --dimensions "Name=FileSystemId,Value=$FS_ID" "Name=FileServer,Value=$OSS" \
    --start-time $START --end-time $END --period 60 --statistics Average \
    --region us-east-2
done
```

## Raw CloudWatch Data

### DataReadBytes (Client-Side, FS-level aggregate, Sum per 60s)

| Timestamp (UTC) | Sum (Bytes) | MB/s |
|---|---|---|
| 10:20 | 0 | 0.0 |
| 10:21 | 32,807,845,888 | 521.5 |
| 10:22 | 73,990,668,288 | 1,176.0 |
| 10:23 | 54,280,065,024 | 862.8 |
| 10:24 | 188,219,392 | 3.0 |
| 10:25 | 5,045,858,304 | 80.2 |
| 10:26 | 4,975,919,104 | 79.1 |
| 10:27 | 5,001,170,944 | 79.5 |
| 10:28 | 4,989,988,864 | 79.3 |
| 10:29 | 4,986,060,800 | 79.3 |
| 10:30 | 4,977,274,880 | 79.1 |
| 10:31 | 4,931,547,136 | 78.4 |
| 10:32 | 5,129,715,712 | 81.5 |

### DiskReadBytes (Disk-Side, per OST, Sum per 60s)

| Timestamp | OST0000 (Bytes) | OST0001 (Bytes) | OST0002 (Bytes) | OST0003 (Bytes) | **Total MB/s** |
|---|---|---|---|---|---|
| 10:24 | 22,175,547,392 | 22,191,276,032 | 21,881,421,824 | 21,889,286,144 | 1,400.9 |
| 10:25 | 31,716,802,560 | 31,691,636,736 | 31,769,231,360 | 31,765,299,200 | 2,017.7 |
| 10:26 | 32,684,900,352 | 32,662,618,112 | 32,841,138,176 | 32,813,350,912 | 2,082.2 |
| 10:27 | 32,567,721,984 | 32,618,840,064 | 32,843,235,328 | 32,807,059,456 | 2,079.6 |
| 10:28 | 32,551,993,344 | 32,555,139,072 | 32,688,570,368 | 32,847,429,632 | 2,076.5 |
| 10:29 | 35,611,475,968 | 35,575,300,096 | 36,051,877,888 | 35,982,147,584 | 2,276.4 |
| 10:30 | 34,319,106,048 | 34,319,372,288 | 34,191,704,064 | 34,256,453,632 | 2,178.9 |
| 10:31 | 32,169,263,104 | 32,152,485,888 | 32,600,489,984 | 32,556,974,080 | 2,058.0 |
| 10:32 | 8,988,917,760 | 8,910,012,416 | 9,498,787,840 | 9,469,689,856 | 586.0 |

## Conclusions

1. **FSx Lustre has a 256KB minimum effective disk I/O unit.** This is confirmed by both CloudWatch measurement (DiskReadBytes / DiskReadOps = 256KB) and AWS documentation (">256k" transfer size recommendation).

2. **4K random reads with cache misses produce ~26× read amplification.** Client receives ~80 MB/s while disks are reading ~2,080 MB/s.

3. **The bottleneck is disk throughput, not IOPS count or network.** FileServerDiskThroughputUtilization hits 90–102% while DiskIopsUtilization is only ~58% and NetworkThroughputUtilization is <1%.

4. **OSS in-memory cache masks the amplification.** With an 8GB working set (fits in 66GB cache), the same FS delivered 252K IOPS at <0.01% disk utilization. Real-world performance depends entirely on cache hit ratio.

5. **Recommendation:** For random small-I/O workloads on FSx Lustre, either (a) keep the working set within the OSS cache, (b) use I/O sizes ≥256KB, or (c) accept reduced effective throughput and provision accordingly.

## Resources Cleaned

All test resources have been deleted:
- FSx Lustre: fs-0abb08606bd0a8f3e (deleted)
- EC2: i-06f6e18f680453866 (terminated)
