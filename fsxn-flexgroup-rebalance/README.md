# FSx for NetApp ONTAP — FlexGroup 跨 HA pair 数据分布实测

验证:把数据从「单 HA pair 的 FlexVol」经 **AWS DataSync** 拷到「2 HA pair 的 FlexGroup」后,数据**是否自动均衡分布到 2 个 aggregate(aggr1 / aggr2)**。

- Region: `us-east-2` (Ohio)
- FSxN 代次: **Gen2 (SINGLE_AZ_2)**
- ONTAP: 9.18.1P5
- 测试日期: 2026-08-28

> 本文档为第一部分(DataSync 全量 + 增量 + aggregate 分布 + 费用)。扩容/FlexVol→FlexGroup转换/均衡 + fio 压测结果见后续追加。

---

## 1. 实验设计

| 项 | 源 (SOURCE) | 目标 (TARGET) |
|---|---|---|
| FSxN | 2TB Gen2 Single-AZ, **1 HA pair**, 384 MB/s | 2TB Gen2 Single-AZ, **2 HA pair**, 1536 MB/s/HApair |
| 卷 | **FlexVol** `srcvol` (junction `/srcvol`) | **FlexGroup** `dstvol` (junction `/dstvol`, 8 constituents) |
| aggregate | aggr1 (1个) | aggr1 + aggr2 (2个, 各 ~907GB) |
| 数据 | 8×100GiB = 800GiB 大文件 (dd /dev/urandom) | DataSync 从源拷入 |
| 观察 | — | aggr1 vs aggr2 的 usedsize 是否 ≈ 400:400 |

FlexGroup `dstvol` 用 `-aggr-list aggr1,aggr2 -aggr-list-multiplier 4` 创建 = 每 aggregate 4 个 constituent,共 **8 个 constituent**。

---

## 2. 核心结论

**❌ 数据 NOT 自动均衡。** 8 个大文件在两个 aggregate 上分布明显偏斜。

### 第一组:全量 800GiB 后
| aggregate | node | usedsize | percent-used |
|---|---|---|---|
| **aggr1** | FsxId...-01 | **209.0 GB** | 23% |
| **aggr2** | FsxId...-03 | **616.1 GB** | 68% |

≈ **200 : 600**,远非理想的 400:400。

constituent 明细(全量后):

| constituent | aggregate | used |
|---|---|---|
| dstvol__0001 | aggr1 | 0.5 GB |
| dstvol__0002 | aggr2 | 202.1 GB (2文件) |
| dstvol__0003 | aggr1 | 0.5 GB |
| dstvol__0004 | aggr2 | 202.0 GB (2文件) |
| dstvol__0005 | aggr1 | 102.0 GB (1文件) |
| dstvol__0006 | aggr2 | 102.1 GB (1文件) |
| dstvol__0007 | aggr1 | 102.0 GB (1文件) |
| dstvol__0008 | aggr2 | 102.1 GB (1文件) |

→ 8 个文件按**文件名哈希**落到 8 个 constituent:**2 个落 aggr1,6 个落 aggr2**。constituent 会**弹性自动增长**(0002/0004 各落 2 个文件,自动长到 305GB)。

### 第二组:增量后(共 ~950GiB)
增量再传 3 个 50GiB 文件(见下),之后:

| aggregate | usedsize | percent-used |
|---|---|---|
| **aggr1** | **311.6 GB** | 34% |
| **aggr2** | **666.6 GB** | 73% |

≈ **32 : 68**,仍然不均衡。

### 为什么不均衡?
FlexGroup 的"均衡"是**按文件哈希(ingest heuristic)把每个文件整体放进某一个 constituent**。文件数量少(8~11个)时,哈希分布方差大 → 落点偏斜。**只有当文件数量很多(成百上千)时,哈希才趋于均匀。** 单个文件不会跨 constituent 拆分(除非 ONTAP 9.16.1+ 的 advanced capacity balancing)。
→ 想强制均衡需手动 `volume rebalance start` 或 `volume move`(后续实验验证)。

---

## 3. DataSync 传输时间 + 吞吐 + 费用

Task mode = **BASIC**(`create-task` 默认)。VerifyMode = ONLY_FILES_TRANSFERRED。

| 执行 | BytesTransferred | 传输时长 | 吞吐 | 校验时长 | 总时长 |
|---|---|---|---|---|---|
| **全量** (8×100GiB) | 858,993,459,200 B (800 GiB) | 40.5 min | ≈353 MB/s | 67.6 min | 108.5 min |
| **增量** (3×50GiB) | 161,061,273,600 B (150 GiB) | 8.2 min | ≈327 MB/s | 9.2 min | 17.5 min |

> ⚠️ **VerifyMode=ONLY_FILES_TRANSFERRED 对大文件回读校验极慢**:全量 verify 67.6min > 传输本身 40.5min(要把 800GB 从两端全部回读比对校验和)。想省时可用 `VerifyMode=NONE` 或 `POINT_IN_TIME_CONSISTENT`。

> **增量传了 150GiB 而非预期 100GiB**:因为源上除了 file_9/file_10(各50G),还多了一个 50G 的 fio 测试文件(压测预热时建的),也被当新文件抓走。三个新 50GiB 文件 = 150GiB。**这恰好证明增量(`TransferMode=CHANGED`)确实只传新增/变更文件,没有重传 800GB 旧数据。**

### 费用(DataSync Basic mode)
- 单价:**$0.0125 / GB**(Basic mode)。来源:[AWS DataSync Pricing](https://aws.amazon.com/datasync/pricing/)(多方核实,AWS 注明 per-GB 费率各 Region 相同;Enhanced mode 为 $0.015/GB + $0.55/execution)。
- 按**实测 BytesTransferred**(十进制 GB)计:
  - 全量:859.0 GB × $0.0125 = **$10.74**
  - 增量:161.06 GB × $0.0125 = **$2.01**
  - **DataSync 总费用 ≈ $12.75**
- 端点侧:源/目标同 Region、同 VPC、同账号 → **无跨区/跨 AZ Data Transfer OUT 费**;DataSync 传输的数据本身不走 PrivateLink 计费;FSxN SSD 存储费用另计。

---

## 4. 命令手册(脱敏)

占位符:`<ACCOUNT_ID>` / `<SRC_FS_ID>` / `<DST_FS_ID>` / `<SRC_SVM_ID>` / `<DST_SVM_ID>` / `<SUBNET_ID>` / `<SG_ID>` / `<SRC_MGMT_IP>` / `<DST_MGMT_IP>` / `<SRC_NFS_IP>` / `<SRC_LOC>` / `<DST_LOC>` / `<TASK_ID>` / `<FSXADMIN_PASSWORD>`

### 4.1 建源 FSxN(1 HA pair, Gen2 Single-AZ)
```bash
aws fsx create-file-system --file-system-type ONTAP --storage-capacity 2048 \
  --subnet-ids <SUBNET_ID> --region us-east-2 \
  --ontap-configuration \
  'DeploymentType=SINGLE_AZ_2,HAPairs=1,ThroughputCapacityPerHAPair=384,FsxAdminPassword=<FSXADMIN_PASSWORD>,PreferredSubnetId=<SUBNET_ID>'
```

### 4.2 建目标 FSxN(2 HA pair, Gen2 Single-AZ)
```bash
# ⚠️ 2 HA pair 的 ThroughputCapacityPerHAPair 只能是 [1536, 3072, 6144],不能用 384(那是 1 HA pair 的值)
aws fsx create-file-system --file-system-type ONTAP --storage-capacity 2048 \
  --subnet-ids <SUBNET_ID> --region us-east-2 \
  --ontap-configuration \
  'DeploymentType=SINGLE_AZ_2,HAPairs=2,ThroughputCapacityPerHAPair=1536,FsxAdminPassword=<FSXADMIN_PASSWORD>,PreferredSubnetId=<SUBNET_ID>'
```

### 4.3 建 SVM(源 / 目标各一个)
```bash
aws fsx create-storage-virtual-machine --file-system-id <SRC_FS_ID> --name srcsvm --region us-east-2
aws fsx create-storage-virtual-machine --file-system-id <DST_FS_ID> --name dstsvm --region us-east-2
```

### 4.4 建 FlexVol(源, ONTAP CLI)
```bash
# 经跳板机 SSM → sshpass 登录 fsxadmin@<SRC_MGMT_IP>
volume create -vserver srcsvm -volume srcvol -aggregate aggr1 \
  -size 1200GB -junction-path /srcvol -security-style unix -space-guarantee none
```

### 4.5 建 FlexGroup(目标, ONTAP CLI) —— 重点
```bash
# 先确认 aggregate 名字
storage aggregate show -fields node,size,usedsize,availsize
# 目标有 aggr1(node-01)+aggr2(node-03),用 aggr-list 跨两个 aggregate 建 8 个 constituent
volume create -vserver dstsvm -volume dstvol -aggr-list aggr1,aggr2 \
  -aggr-list-multiplier 4 -size 1600GB -junction-path /dstvol \
  -security-style unix -space-guarantee none
```

### 4.6 造 800GB 数据(在能挂源卷的 EC2 上)
```bash
mount -t nfs -o nfsvers=3 <SRC_NFS_IP>:/srcvol /mnt/src
# 8 个 100GiB 真实随机数据(并行), urandom 不可压缩,避免 ONTAP 存储效率把零压掉
for i in $(seq 1 8); do
  dd if=/dev/urandom of=/mnt/src/file_$i.bin bs=1M count=102400 iflag=fullblock &
done; wait
```

### 4.7 建 DataSync location ×2(FSx ONTAP 类型)
```bash
aws datasync create-location-fsx-ontap --region us-east-2 \
  --storage-virtual-machine-arn arn:aws:fsx:us-east-2:<ACCOUNT_ID>:storage-virtual-machine/<SRC_FS_ID>/<SRC_SVM_ID> \
  --security-group-arns arn:aws:ec2:us-east-2:<ACCOUNT_ID>:security-group/<SG_ID> \
  --protocol NFS={} --subdirectory /srcvol
aws datasync create-location-fsx-ontap --region us-east-2 \
  --storage-virtual-machine-arn arn:aws:fsx:us-east-2:<ACCOUNT_ID>:storage-virtual-machine/<DST_FS_ID>/<DST_SVM_ID> \
  --security-group-arns arn:aws:ec2:us-east-2:<ACCOUNT_ID>:security-group/<SG_ID> \
  --protocol NFS={} --subdirectory /dstvol
```

### 4.8 建 task
```bash
# ⚠️ 设了 LogLevel 就必须给 CloudWatch Log Group ARN,否则报错;这里用 OFF
aws datasync create-task --region us-east-2 \
  --source-location-arn arn:aws:datasync:us-east-2:<ACCOUNT_ID>:location/<SRC_LOC> \
  --destination-location-arn arn:aws:datasync:us-east-2:<ACCOUNT_ID>:location/<DST_LOC> \
  --name fsxn-flexgroup-rebalance-task \
  --options VerifyMode=ONLY_FILES_TRANSFERRED,LogLevel=OFF
```

### 4.9 第一次启动(全量)
```bash
aws datasync start-task-execution --region us-east-2 \
  --task-arn arn:aws:datasync:us-east-2:<ACCOUNT_ID>:task/<TASK_ID>
# 监控
aws datasync describe-task-execution --region us-east-2 \
  --task-execution-arn <EXEC_ARN> \
  --query '{Status:Status,BytesTransferred:BytesTransferred,FilesTransferred:FilesTransferred,Result:Result}'
```

### 4.10 查看数据分布(目标 ONTAP CLI)
```bash
# aggregate 级用量(核心)
storage aggregate show -fields node,size,usedsize,availsize,percent-used
# FlexGroup 各 constituent 落在哪个 aggregate、用了多少
volume show -vserver dstsvm -volume dstvol* -fields aggregate,size,used -is-constituent true
```

### 4.11 增量:源加 2×50GiB 文件
```bash
for i in 9 10; do
  dd if=/dev/urandom of=/mnt/src/file_$i.bin bs=1M count=51200 iflag=fullblock &
done; wait
```

### 4.12 第二次启动(增量)+ 查 BytesTransferred
```bash
aws datasync start-task-execution --region us-east-2 \
  --task-arn arn:aws:datasync:us-east-2:<ACCOUNT_ID>:task/<TASK_ID>
aws datasync describe-task-execution --region us-east-2 \
  --task-execution-arn <INCR_EXEC_ARN> \
  --query '{Status:Status,BytesTransferred:BytesTransferred,BytesWritten:BytesWritten,FilesTransferred:FilesTransferred}'
# 增量只传新增/变更文件(TransferMode=CHANGED),BytesTransferred≈新数据量,不重传旧数据
```

---

## 5. 踩坑记录
1. **Gen2 2 HA pair 的 ThroughputCapacityPerHAPair 只能 [1536, 3072, 6144]**;1 HA pair 可用 384。建目标时用 384 直接被拒。
2. **DataSync create-task 设 LogLevel 必须配 CloudWatch Log Group ARN**,否则 `LogLevelSetWithNoLogGroup` 报错。不需要日志就用 `LogLevel=OFF`。
3. **VerifyMode=ONLY_FILES_TRANSFERRED 对大文件校验极慢**(回读全部数据比对校验和)。
4. **FlexGroup 少量大文件分布必然偏斜** —— hash 落点方差大,不是 bug,是设计。

---

## 6. 参考
- [AWS DataSync Pricing](https://aws.amazon.com/datasync/pricing/)
- [FSx for NetApp ONTAP — FlexGroup volumes](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-volumes.html)
- [ONTAP FlexGroup 概念](https://docs.netapp.com/us-en/ontap/flexgroup/)
