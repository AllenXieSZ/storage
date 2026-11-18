# FSx ONTAP: Linux df 在不同 Volume 大小下的显示行为

## 背景

客户在 Linux 上用 `df` 查看 FSx ONTAP 挂载的 volume 时，可能被 `Used` 和 `Use%` 的值误导。本文档通过两组实测（500GB volume 和 17TB volume）说明 `df` 的显示行为及其准确性，以及如何用 ONTAP CLI 查看准确数据。

## 测试环境

- **FS**: fs-0f89de8f02e9a7b2e（SINGLE_AZ_1，**SSD 1024 GB**，吞吐 128 MBps）
- **挂载**: NFS v3，Linux EC2 客户端
- **数据**: `/dev/urandom` 随机数据（不可压缩）

## 测试一：500GB Volume + 50GB 数据

Volume 大小（500GB）< SSD 容量（1024GB），**未超配**。

### 空 volume — Linux df

```
Filesystem               Size  Used Avail Use%
172.31.41.231:/vol500gb  475G  320K  475G   1%
```

### 写入 50GB 随机数据后

**Linux df：**

```
Filesystem               Size  Used Avail Use%
172.31.41.231:/vol500gb  475G   51G  425G  11%
```

**ONTAP CLI：**

```
volume show -volume vol500gb -fields size,used,available,percent-used,physical-used,logical-used

vserver volume   size  available used    percent-used physical-used logical-used
------- -------- ----- --------- ------- ------------ ------------- ------------
svm1    vol500gb 500GB 424.3GB   50.71GB 10%          51.04GB       50.71GB
```

**对比：**

| 指标 | Linux df | ONTAP CLI | 匹配？ |
|---|---|---|---|
| Size | 475G（500G − 5% snapshot reserve） | 500GB | ✅ |
| Used | **51G** | **50.71GB** | ✅ 一致 |
| Avail | 425G | 424.3GB | ✅ |
| Use% | 11% | 10% | ✅ |

**✅ 结论：volume ≤ SSD 容量时，df 显示准确。**

## 测试二：17TB Volume + 200GB 数据

Volume 大小（17TB）>> SSD 容量（1024GB），**严重超配（thin provisioned）**。

### 空 volume — Linux df

```
Filesystem              Size  Used Avail Use%
172.31.41.231:/vol17tb   17T   16T  859G  95%
```

⚠️ **volume 里没有任何文件，df 就显示 Used 16T、95% 满。**

### 写入 200GB 随机数据后

**Linux df：**

```
Filesystem              Size  Used Avail Use%
172.31.41.231:/vol17tb   17T   16T  655G  97%
```

**ONTAP CLI：**

```
volume show -volume vol17tb -fields size,used,available,percent-used,physical-used,logical-used

vserver volume  size available used    percent-used physical-used logical-used
------- ------- ---- --------- ------- ------------ ------------- ------------
svm1    vol17tb 17TB 653.0GB   203.1GB 1%           205.3GB       203.1GB
```

**对比：**

| 指标 | Linux df | ONTAP CLI | 匹配？ |
|---|---|---|---|
| Size | 17T | 17TB | ✅ |
| Used | **16T** | **203.1GB** | ❌ df 严重失真 |
| Avail | 655G | 653.0GB | ✅ |
| Use% | **97%** | **1%** | ❌ df 严重失真 |

**❌ 结论：volume >> SSD 容量时，df 的 Used 和 Use% 严重失真。**

## 原因分析

Linux `df` 通过 NFS `statfs` 获取三个值：`total`、`free`、`available`，然后：
- `Size` = total（volume 逻辑大小 − snapshot reserve）
- `Available` = 底层 aggregate SSD 的物理剩余空间（所有 volume 共享）
- `Used` = Size − Available（**反算**，不是实际数据量）

| 场景 | Size | Available 来源 | Used = Size − Available | 准确？ |
|---|---|---|---|---|
| volume ≤ SSD | 475G | volume 逻辑剩余（475G − 51G = 424G） | 51G ≈ 真实 | ✅ |
| volume >> SSD | 17T | SSD 物理剩余（~655G） | 17T − 655G ≈ 16T ≠ 真实 203G | ❌ |

**根因**：ONTAP 通过 NFS `statfs` 返回的 `available` 是 aggregate 层面的物理剩余，不是 volume 逻辑剩余。当 volume 逻辑大小远超物理 SSD 时，`Used = Size − Available` 会被严重高估。

## 如何查看真实用量

使用 ONTAP CLI（通过 SSH 连接 fsxadmin）：

```bash
# 用量概要
sshpass -p <password> ssh fsxadmin@<mgmt-ip> \
  "volume show -volume <vol-name> -fields used,logical-used,sis-space-saved"

# 详细用量
sshpass -p <password> ssh fsxadmin@<mgmt-ip> \
  "volume show -volume <vol-name> -fields size,used,available,percent-used,physical-used,logical-used"
```

关键字段：
- `used`：压缩/去重后的物理占用
- `logical-used`：压缩前的逻辑数据量（"写了多少数据"）
- `sis-space-saved`：Storage Efficiency 节省的空间

## 总结

| volume 大小 vs SSD 容量 | df Used 准确？ | df Use% 准确？ | 建议 |
|---|---|---|---|
| volume ≤ SSD 容量 | ✅ 准确 | ✅ 准确 | 可以用 df |
| volume > SSD 容量（thin provisioned） | ❌ 虚高 | ❌ 虚高 | 必须用 ONTAP CLI |
