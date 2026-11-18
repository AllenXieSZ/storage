# FSx ONTAP: Linux df 在 Thin Provisioned Volume 上的显示行为

## 背景

客户在 Linux 上用 `df` 查看 FSx ONTAP 挂载的 volume 时，经常被 `Used` 和 `Use%` 的值误导。本文档通过实测说明 `df` 在 thin provisioned volume 上的真实行为，以及如何用 ONTAP CLI 查看准确数据。

## 测试环境

- **FS**: fs-0f89de8f02e9a7b2e（SINGLE_AZ_1，SSD 1024 GB，吞吐 128 MBps）
- **Volume**: vol17tb（17 TB，thin provisioned，Storage Efficiency 开启）
- **挂载**: NFS v3，Linux EC2 客户端
- **测试数据**: 200 GB 随机数据（`/dev/urandom`，不可压缩）

## 测试结果

### 空 volume — Linux df

```
Filesystem              Size  Used Avail Use% Mounted on
172.31.41.231:/vol17tb   17T   16T  859G  95% /mnt/vol17tb
```

⚠️ **volume 里没有任何文件，df 就显示 Used 16T、95% 满。**

### 写入 200 GB 随机数据后 — Linux df

```
Filesystem              Size  Used Avail Use% Mounted on
172.31.41.231:/vol17tb   17T   16T  655G  97% /mnt/vol17tb

Filesystem               1K-blocks        Used     Available Use% Mounted on
172.31.41.231:/vol17tb 17340930496 16654947008     685983488  97% /mnt/vol17tb

Filesystem                Inodes IUsed     IFree IUse% Mounted on
172.31.41.231:/vol17tb 541904072    98 541903974    1% /mnt/vol17tb
```

```
ls -lh:
-rw-r--r-- 1 root root 200G randomfile
```

### 写入 200 GB 随机数据后 — ONTAP CLI

```
volume show -volume vol17tb -fields used,logical-used,sis-space-saved

vserver volume  used    sis-space-saved logical-used
------- ------- ------- --------------- ------------
svm1    vol17tb 203.0GB 0B              203.0GB
```

```
volume show -volume vol17tb -fields size,used,available,percent-used,physical-used,physical-used-percent,logical-used,logical-used-percent,logical-used-by-afs

vserver volume  size available used    percent-used physical-used physical-used-percent logical-used logical-used-percent logical-used-by-afs
------- ------- ---- --------- ------- ------------ ------------- --------------------- ------------ -------------------- -------------------
svm1    vol17tb 17TB 653.0GB   203.1GB 1%           205.3GB       1%                    203.1GB      1%                   203.1GB
```

```
volume show-footprint -volume vol17tb

      Feature                                         Used       Used%
      --------------------------------             ----------    -----
      Volume Data Footprint                           200.6GB      22%
             Footprint in Performance Tier            204.1GB     100%
             Footprint in FSxFabricpoolObjectStore         0B       0%
      Volume Guarantee                                     0B       0%
      Flexible Volume Metadata                         1.24GB       0%
      Deduplication Metadata                           1.12GB       0%
      Delayed Frees                                   599.0MB       0%
      Total Footprint                                 205.3GB      23%
```

## 对比表

| 指标 | Linux `df` | ONTAP `volume show` | 说明 |
|---|---|---|---|
| 总大小 | 17T | 17TB | ✅ 一致 |
| 已用 | **16T** | **203.1GB** | ❌ df 严重失真 |
| 可用 | 655G | 653.0GB | ✅ 基本一致 |
| 使用率 | **97%** | **1%** | ❌ df 严重失真 |

## 原因分析

Linux `df` 的计算方式：
- `Size` = volume 逻辑大小 − snapshot reserve（17TB × 95% ≈ 16.15 TiB）
- `Available` = **底层 aggregate SSD 的物理剩余空间**（所有 volume 共享）
- `Used` = Size − Available（反算出来的，**不是实际数据量**）
- `Use%` = Used / Size

在 thin provisioned volume 上：
- Volume 逻辑大小（17TB）远大于底层 SSD（1TB）
- `Available` 反映的是物理 SSD 剩余，不是 volume 逻辑剩余
- 所以 `Used = 17T − 655G ≈ 16T`——但实际只存了 203GB 数据

## 如何查看真实用量

使用 ONTAP CLI（通过 SSH 连接到 fsxadmin）：

```bash
# 查看用量概要
sshpass -p <password> ssh fsxadmin@<mgmt-ip> \
  "volume show -volume <vol-name> -fields used,logical-used,sis-space-saved"

# 查看详细用量
sshpass -p <password> ssh fsxadmin@<mgmt-ip> \
  "volume show -volume <vol-name> -fields size,used,available,percent-used,physical-used,logical-used"

# 查看 footprint（物理占用分解）
sshpass -p <password> ssh fsxadmin@<mgmt-ip> \
  "volume show-footprint -volume <vol-name>"
```

关键字段：
- `used`：压缩/去重后的物理占用
- `logical-used`：压缩前的逻辑数据量（客户关心的"写了多少数据"）
- `sis-space-saved`：Storage Efficiency 节省的空间
- `physical-used`：aggregate 层面的物理占用（含元数据）

## 全零数据 vs 随机数据对比

额外用 `/dev/zero`（全零，可压缩）写入 200 GB 做对照：

| 指标 | 全零 200GB | 随机 200GB |
|---|---|---|
| `used` | 815.3MB | 203.0GB |
| `logical-used` | 200.3GB | 203.0GB |
| `sis-space-saved` | 199.5GB（压缩率 99.6%） | 0B |
| `physical-used` | 1.10GB | 205.3GB |

ONTAP 的 inline 压缩和去重对全零数据效果极好（200GB → 815MB），但 `df` 看不出区别——因为 `df` 显示的 Used 是反算的，不反映实际物理占用。
