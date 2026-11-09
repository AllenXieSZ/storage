# RUN_LOG — FSx ONTAP Storage Efficiency vs AI Model Files

## 时间线

| 时间 (UTC) | 事件 |
|---|---|
| 2026-11-09 05:33 | 创建 FSx ONTAP fs-07a1bc8b8903f81d4 (Gen2 SINGLE_AZ_2, 1024GiB, 384MB/s, us-east-2c) |
| 05:37 | 上传测试数据生成脚本到跳板机 |
| 05:38 | 开始生成测试数据（8 个文件，共 3.8GB） |
| 05:41 | 测试数据生成完毕（167 秒） |
| 05:47 | FSx ONTAP AVAILABLE，管理端点 IP 172.31.33.223 |
| 05:48 | 创建 SVM svm1 |
| 05:49 | SVM CREATED，NFS IP 172.31.47.138 |
| 05:49 | 创建 8 个 volumes（每种测试独立 volume） |
| 05:51 | 所有 volumes CREATED |
| 05:52 | NFS 挂载 8 个 volumes 到跳板机 |
| 05:52-05:53 | 写入测试数据（~30 秒完成 4.3GB） |
| 05:53 | 触发 background efficiency scan（volume efficiency start -scan-old-data true） |
| 05:54 | 等待 60 秒后收集 efficiency 数据 |
| 05:55-05:58 | 逐 volume 收集 volume efficiency show + volume show-space |
| 05:58 | 收集 aggregate show-efficiency |

## 完整命令记录

### 1. 创建 FSx ONTAP
```bash
aws fsx create-file-system \
  --file-system-type ONTAP \
  --storage-capacity 1024 \
  --storage-type SSD \
  --subnet-ids subnet-0c551a33e366d52d4 \
  --ontap-configuration '{
    "DeploymentType": "SINGLE_AZ_2",
    "ThroughputCapacity": 384,
    "FsxAdminPassword": "FsxOntap#2026Ohio",
    "PreferredSubnetId": "subnet-0c551a33e366d52d4",
    "DiskIopsConfiguration": {"Mode": "AUTOMATIC"}
  }' \
  --security-group-ids sg-00ca35d004d81089b \
  --tags "Key=Name,Value=ontap-model-compression-test" \
  --region us-east-2
```

### 2. 创建 SVM
```bash
aws fsx create-storage-virtual-machine \
  --file-system-id fs-07a1bc8b8903f81d4 \
  --name svm1 \
  --region us-east-2
```

### 3. 创建 Volumes（8 个独立 volume）
```bash
FSID=fs-07a1bc8b8903f81d4
SVMID=svm-020b7b8b24d5cd25f
for VNAME in vol_dense vol_sparse50 vol_sparse90 vol_contiguous50 vol_allzero vol_semi24 vol_int4 vol_dedup; do
  aws fsx create-volume --volume-type ONTAP --name $VNAME \
    --ontap-configuration "{
      \"JunctionPath\": \"/$VNAME\",
      \"SizeInMegabytes\": 10240,
      \"StorageVirtualMachineId\": \"$SVMID\",
      \"StorageEfficiencyEnabled\": true,
      \"TieringPolicy\": {\"CoolingPeriod\": 31, \"Name\": \"AUTO\"},
      \"SecurityStyle\": \"UNIX\"
    }" --region us-east-2
done
```

### 4. NFS 挂载（跳板机上）
```bash
NFS_IP=172.31.47.138
for VOL in vol_dense vol_sparse50 vol_sparse90 vol_contiguous50 vol_allzero vol_semi24 vol_int4 vol_dedup; do
  mkdir -p /mnt/$VOL
  mount -t nfs ${NFS_IP}:/${VOL} /mnt/${VOL} -o nfsvers=3,tcp,rsize=65536,wsize=65536
done
```

### 5. 写入测试数据
```bash
cp /tmp/test_data/01_dense_random_512mb.bin /mnt/vol_dense/
cp /tmp/test_data/02_sparse50_scattered_512mb.bin /mnt/vol_sparse50/
cp /tmp/test_data/03_sparse90_scattered_512mb.bin /mnt/vol_sparse90/
cp /tmp/test_data/04_sparse50_contiguous_512mb.bin /mnt/vol_contiguous50/
cp /tmp/test_data/05_allzero_512mb.bin /mnt/vol_allzero/
cp /tmp/test_data/06_semi24_512mb.bin /mnt/vol_semi24/
cp /tmp/test_data/07_int4_random_256mb.bin /mnt/vol_int4/
# Dedup test: same file twice
cp /tmp/test_data/01_dense_random_512mb.bin /mnt/vol_dedup/copy1.bin
cp /tmp/test_data/01_dense_random_512mb.bin /mnt/vol_dedup/copy2.bin
sync
```

### 6. 测试数据生成脚本
见同目录 `gen_test_data_v3.py`。核心策略：
- 随机数据 = `os.urandom()`（高熵不可压缩，模拟训练后的 FP16 权重）
- 散零 = `os.urandom()` 后按概率将 FP16 word 置零
- 连续零 = 前半全零 + 后半 `os.urandom()`
- 2:4 = 每 4 个 FP16 word 中随机 2 个置零

### 7. 触发 Background Efficiency + 收集数据
```bash
MGMT=172.31.33.223
PASS='FsxOntap#2026Ohio'
# 触发
for VOL in vol_dense vol_sparse50 vol_sparse90 vol_contiguous50 vol_allzero vol_semi24 vol_int4 vol_dedup; do
  sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no fsxadmin@$MGMT \
    "volume efficiency start -vserver svm1 -volume $VOL -scan-old-data true"
done
# 等待后收集
sshpass -p "$PASS" ssh fsxadmin@$MGMT \
  "set -units MB; volume show -vserver svm1 -fields volume,size,used,available,logical-used,logical-used-percent"
sshpass -p "$PASS" ssh fsxadmin@$MGMT \
  "set -units MB; volume show-space -vserver svm1 -volume <vol>"
sshpass -p "$PASS" ssh fsxadmin@$MGMT \
  "storage aggregate show-efficiency"
```

## ONTAP 原始输出

### volume show（所有 volume 汇总）
```
vserver volume           size     available used  logical-used logical-used-percent 
------- ---------------  ------   --------- ----  ------------ -------------------- 
svm1    vol_allzero      10240MB  9725MB    2MB   514MB        5%                   
svm1    vol_contiguous50 10240MB  9465MB    262MB 518MB        5%                   
svm1    vol_dedup        10240MB  9203MB    524MB 1036MB       11%                  
svm1    vol_dense        10240MB  9205MB    522MB 522MB        5%                   
svm1    vol_int4         10240MB  9466MB    261MB 261MB        3%                   
svm1    vol_semi24       10240MB  9205MB    522MB 522MB        5%                   
svm1    vol_sparse50     10240MB  9205MB    522MB 522MB        5%                   
svm1    vol_sparse90     10240MB  9205MB    522MB 522MB        5%                   
```

### Aggregate Efficiency
```
Aggregate: aggr1
Total Storage Efficiency Ratio: 1.54:1
```
