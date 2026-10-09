# FSx for Lustre：Persistent 1 与 Persistent 2 对比（官方文档 + 实测验证）

区域 us-east-2，2026-10-09。"实测"= 用 AWS CLI 实际调用 CreateFileSystem / UpdateFileSystem 等得到的返回；"文档"= FSx for Lustre User Guide / API Reference。

## 0. 特性逐项实测对比表（2026-10-09，us-east-2，CLI 实际创建/修改）

| 特性 | 测试方法 | Persistent 1 | Persistent 2 |
|---|---|---|---|
| SSD 存储 | 建 1200 GiB | ✅ 创建成功 | ✅ 创建成功 |
| **HDD 存储** | 建 HDD 6000 GiB / 1800 GiB | ✅ 12 MBps/TiB + SSD 读缓存、40 MBps/TiB 无缓存均成功 | ❌ `StorageType HDD is not supported for ... PERSISTENT_2` |
| HDD 读缓存参数 | 不填 DriveCacheType | ❌ `DriveCacheType must be provided for storage type HDD. Supported values are [NONE,READ]` | — |
| Intelligent-Tiering | ThroughputCapacity=4000 | ❌ `DeploymentType must be PERSISTENT_2` | ✅ 创建成功（需同时带 Metadata 配置） |
| **EFA** | EfaEnabled=true | ❌ `EFA is only supported for PERSISTENT_2 filesystems with metadata configuration`（换成自引用安全组仍失败） | ✅ 4800 GiB / 1000 MBps/TiB + Metadata + 自引用安全组 创建成功 |
| EFA 前提 | P2 各种组合 | — | 无 Metadata 配置 ❌；安全组无自引用全通 ❌；1000 档 <4800 GiB ❌；125 档 <38400 GiB ❌ |
| 吞吐档位 | 互用对方档位 | 50/100/200，用 125 ❌ | 125/250/500/1000，用 200 ❌ |
| 修改吞吐 | update-file-system | SSD 可在 50/100/200 内改；**HDD 不能改**（`Throughput scaling is not supported for ... HDD`） | SSD 可在 125–1000 内改；EFA 文件系统不能改（文档） |
| **Metadata IOPS（创建时）** | MetadataConfiguration | ❌ `Cannot specify metadata configuration for deployment type 'PERSISTENT_1'` | ✅ AUTOMATIC / USER_PROVISIONED 1500–192000（192000 实测成功；5000 非法） |
| Metadata IOPS（创建后加） | update-file-system | ❌ | ❌ 建时没配的加不上；✅ 建时配了的可以改（1500→3000 已受理） |
| Metadata + Lustre 版本 | P2 + 2.12 + Metadata | — | ❌ `A FileSystemTypeVersion of '2.15' is required ... when specifying a metadata configuration` |
| CLI 默认 Lustre 版本 | 不指定版本 | **2.10** | 2.15 |
| 可选 Lustre 版本 | — | 2.10 / 2.12 / 2.15 | 2.12 / 2.15（带 Metadata 只能 2.15） |
| S3 关联（DRA） | create-data-repository-association | 2.10 ❌ `does not support data repository associations`；升级 2.15 后 ✅ | ✅ |
| 旧式 S3 关联（ImportPath） | 建 FS 时指定 | ✅（文档） | ❌ `Linking a Persistent 2 file system to an S3 bucket using the LustreConfiguration is not supported` |
| Lustre 版本升级 | 2.10 → 2.15 | ✅ 约 12 分钟 | ✅（文档） |
| LZ4 数据压缩 | update-file-system | ✅ 成功 | ✅ 成功 |
| 备份 | create-backup | ❌ 关联了 S3 的文件系统不能备份（P1、P2 相同报错 `Backups cannot be created on S3-linked file systems`） | 同左 |
| 最小容量 | — | SSD 1200 GiB；HDD-12 6000 GiB；HDD-40 1800 GiB | SSD 1200 GiB；EFA 4800–38400 GiB（按档位） |
| 创建方式 | — | 只能 CLI / API（文档） | 控制台 / CLI / API |
| 创建耗时 | — | SSD 约 6 分钟；HDD 约 7 分钟 | SSD 约 6–7 分钟 |
| 存储价格 SSD $/GB-月 | Price List API | 0.14 / 0.19 / 0.29 | 0.145 / 0.21 / 0.34 / 0.60 |
| 存储价格 HDD $/GB-月 | Price List API | 12：0.025（+缓存 0.041）；40：0.083（+缓存 0.099） | — |


### EFA 只支持 Persistent 2：官方文档出处

[Working with EFA-enabled file systems → Considerations](https://docs.aws.amazon.com/fsx/latest/LustreGuide/efa-file-systems.html#efa-considerations)：

> **Deployment type:** EFA is supported on Persistent 2 file systems with a metadata configuration specified, including file systems using the Intelligent-Tiering storage class.

此外 [IP addresses for file systems](https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-fsx-lustre.html#ip-addesses-for-fs) 表中只有 "Persistent 2 EFA" 一行，Persistent 1 只有 SSD / HDD，没有 EFA 选项。

⚠️ 文档中的 EFA 创建示例 CLI 没有带 `MetadataConfiguration`，但实测不带会报错 `EFA is only supported for PERSISTENT_2 filesystems with metadata configuration`，与 Considerations 一节一致——示例本身不完整。

### 性能小测（1200 GiB 或最小规格，单台 m6i.large 客户端，结果受客户端带宽限制）

| 文件系统 | 顺序写 / 读（4×1 GiB，direct） | 元数据 创建 / 删除（16 并发×1250 文件） |
|---|---|---|
| P1 SSD 50，1200 GiB | 581 / 590 MB/s | 6,223 / 7,540 个/秒 |
| P2 SSD 125，1200 GiB | 588 / 590 MB/s | 7,675 / 9,254 个/秒 |
| P1 HDD 12 + SSD 读缓存，6000 GiB（4 个 OST） | 577 / 584 MB/s | 5,752 / 4,329 个/秒 |
| P2 SSD 125 + Metadata 1500 IOPS，1200 GiB | 440 / 490 MB/s | 7,234 / 7,075 个/秒 |

- 顺序吞吐都在 ~590 MB/s，接近 m6i.large 的网络上限（12.5 Gbps 突发），**看不出文件系统差别**（推测是客户端瓶颈）。
- HDD 的删除速度明显低于 SSD（4,329 vs 7,540–9,254 个/秒）。
- 要测出真实吞吐差别需要更大的客户端和更大的文件系统，本次未做。

## 1. 结论总表

| 对比项 | Persistent 1 | Persistent 2 | 依据 |
|---|---|---|---|
| 创建方式 | **只能 CLI / API** | 控制台 / CLI / API | 文档；CLI 创建 P1 实测成功 |
| SSD 吞吐档位（MBps/TiB） | **50 / 100 / 200** | **125 / 250 / 500 / 1000** | 文档 + 实测（互用对方档位报错） |
| 存储类型 | SSD、**HDD**（12 / 40 MBps/TiB，可选 SSD 读缓存） | SSD、**Intelligent-Tiering** | 文档 + 实测 |
| 单独配置 Metadata IOPS | **不支持** | 支持（AUTOMATIC / USER_PROVISIONED，1500–192000） | 文档 + 实测 |
| EFA / GPUDirect Storage | **不支持** | 支持（需同时配置 Metadata） | 文档 + 实测 |
| 默认 Lustre 版本（CLI 不指定时） | **2.10** | 2.15 | 实测 |
| Lustre 版本 | 2.10 / 2.12 / 2.15（可升级） | 2.12 / 2.15（**不能用 2.10**） | 文档 + 实测 |
| S3 关联（DRA）/ 自动导出 | 2.10 不支持；**升级到 2.12+ 后支持** | 支持 | 文档 + 实测 |
| 旧式 S3 关联（建 FS 时 ImportPath/ExportPath） | 支持 | **不支持**，只能用 DRA | 实测 |
| 存储价格（SSD，us-east-2） | 0.14 / 0.19 / 0.29 $/GB-月 | 0.145 / 0.21 / 0.34 / 0.60 $/GB-月 | AWS Price List API |
| 每 OSS 存储 | 2.4 TiB（SSD） | 2.4 TiB（非 EFA）；EFA 4.8–38.4 TiB | 文档 |
| 网络吞吐 baseline（MBps/TiB） | 250 / 500 / 750 | 320 / 640 / 1300 / 2600 | 文档 |
| 磁盘吞吐 burst | 240 MBps/TiB | 125/250 档 burst 到 500；500/1000 档无 burst | 文档 |
| 内存缓存（GiB/TiB） | 2.2 / 4.4 / 8.8 | 3.4 / 6.8 / 13.7 / 27.3 | 文档 |
| 可用区域 | 部分区域没有（如新西兰、马来西亚、台北、泰国、卡尔加里） | 部分区域没有（如巴林、UAE、洛杉矶 LZ） | 文档区域表 |
| 文档定位 | "previous generation" | 最新一代 | 文档 |

## 2. 你提到的 4 点逐条验证

### 2.1 吞吐档位不同 ✅

```
# P1 用 125
InvalidPerUnitStorageThroughput: The storage throughput (MB/s/TiB) value should be one of [50,100,200].
# P2 用 200
InvalidPerUnitStorageThroughput: The storage throughput (MB/s/TiB) value should be one of [125,250,500,1000].
# P1 创建后把吞吐改成 125
BadRequest: The storage throughput (MB/s/TiB) value should be one of [50,100,200].
```
P1 和 P2 之间**不能互相转换**，修改吞吐也只能在本类型的档位内改。

### 2.2 存储价格不一样 ✅（us-east-2，AWS Price List API）

| 类型 | 档位（MBps/TiB） | $/GB-月 | 每 MBps 吞吐的成本（$/月，按 1 TiB） |
|---|---|---|---|
| P1 SSD | 50 | 0.140 | 2.87 |
| P1 SSD | 100 | 0.190 | 1.95 |
| P1 SSD | 200 | 0.290 | 1.48 |
| **P2 SSD** | **125** | **0.145** | **1.19** |
| P2 SSD | 250 | 0.210 | 0.86 |
| P2 SSD | 500 | 0.340 | 0.70 |
| P2 SSD | 1000 | 0.600 | 0.61 |
| P1 HDD | 12（无缓存 / 带 SSD 缓存） | 0.025 / 0.041 | — |
| P1 HDD | 40（无缓存 / 带 SSD 缓存） | 0.083 / 0.099 | — |

- P2-125 只比 P1-50 贵 $0.005/GB-月，吞吐却是 2.5 倍。
- P2-250（0.21）比 P1-200（0.29）**更便宜**，吞吐还更高。
- P2 额外 Metadata IOPS：超出默认值部分 $0.055 / IOPS-月。
- 只有低成本大容量场景（HDD 0.025 起）P1 才有价格优势。

### 2.3 Persistent 1 只能通过 CLI 创建 ✅

文档原文："You can create Persistent 1 deployment types only by using the AWS CLI and the Amazon FSx API."
实测 CLI 创建 P1 成功（fs-0981c63f654d6d647，约 6 分钟）。控制台本次未登录验证，以文档为准。

### 2.4 Persistent 1 不能单独配置 Metadata IOPS ✅

```
# 创建 P1 时指定 MetadataConfiguration
BadRequest: Cannot specify metadata configuration for deployment type 'PERSISTENT_1'.
# 创建后再加
BadRequest: Updating metadata configuration is not supported on file systems created without specifying a metadata configuration.
```

⚠️ **P2 也有同样的坑**：P2 创建时如果**没有**指定 MetadataConfiguration，之后也加不上（实测同一条报错）。要用 Metadata IOPS，P2 必须在**创建时**就指定（AUTOMATIC 或 USER_PROVISIONED）。

实测 P2 创建时指定 `Mode=USER_PROVISIONED,Iops=6000` 成功。

## 3. 其他差别（实测）

### 3.1 HDD 和 Intelligent-Tiering 互斥
```
# P2 + HDD
BadRequest: StorageType HDD is not supported for file systems with DeploymentType: PERSISTENT_2.
# P1 + Intelligent-Tiering
BadRequest: Invalid Deployment type specified for INTELLIGENT TIERING file systems. DeploymentType must be PERSISTENT_2.
```

### 3.2 EFA 只有 P2
```
# P1 + EfaEnabled=true
BadRequest: EFA is only supported for PERSISTENT_2 filesystems with metadata configuration.
```

### 3.3 P1 默认是 Lustre 2.10，不能直接用 DRA
- CLI 创建 P1 不指定版本 → **2.10**（P2 默认 2.15）。
- 2.10 上建 DRA：`UnsupportedOperation: This file system does not support data repository associations.`
- 升级 2.10 → 2.15：`update-file-system --file-system-type-version 2.15`，**约 12 分钟**，期间需卸载所有客户端。
- 升级后建 DRA（自动导出）成功（约 40 秒）。
- P2 不能用 2.10；指定 2.12 可以创建。

建议：P1 创建时直接加 `--file-system-type-version 2.15`。

### 3.4 P2 不支持旧式 S3 关联
```
# P2 + ImportPath
BadRequest: Linking a Persistent 2 file system to an S3 bucket using the LustreConfiguration is not supported.
Create a file system and then create a data repository association to link S3 buckets to the file system.
```

### 3.5 最小容量
| 类型 | 最小容量 |
|---|---|
| P1 SSD | 1200 GiB |
| P1 HDD 12 MBps/TiB | 6000 GiB |
| P2 SSD | 1200 GiB |

### 3.6 元数据性能（同为 1200 GiB，客户端 m6i.large，16 并发各 1250 个空文件）

| 文件系统 | 创建（个/秒） | 删除（个/秒） |
|---|---|---|
| P1-50（2.10，未配 Metadata IOPS） | 7,125 | 8,810 |
| P2-125（2.15，未配 Metadata IOPS） | 7,159 | 9,118 |

1200 GiB 小规模下两者元数据性能几乎相同；瓶颈可能在单台客户端（推测）。P2 的优势在于可以**单独加 Metadata IOPS**（最高 192000）和增加 MDS 数量，P1 只能靠扩容存储。

### 3.7 Changelog（附带验证）
P1 在升级到 2.15 并建好自动导出 DRA 后，同样出现 Changelog（序号从 1 开始），与 P2 行为一致。

## 4. 怎么选

| 场景 | 建议 |
|---|---|
| 新建 SSD 文件系统 | **P2**：同价位吞吐更高、可配 Metadata IOPS、支持 EFA |
| 大量小文件 / 元数据密集 | **P2**，创建时就配置 MetadataConfiguration |
| GPU 训练、需要 EFA / GDS | **P2**（必须带 Metadata 配置） |
| 冷数据、超低单价 | P1 HDD（0.025 $/GB-月起）或 P2 Intelligent-Tiering |
| 区域只有 P1（如巴林、UAE） | P1，创建时指定 2.15 |

## 5. 参考
- [Deployment and storage class options](https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-fsx-lustre.html)
- [Performance characteristics of SSD and HDD storage classes](https://docs.aws.amazon.com/fsx/latest/LustreGuide/ssd-storage.html)
- [File system metadata performance](https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance.html#dne-metadata-performance)
- [Managing provisioned throughput capacity](https://docs.aws.amazon.com/fsx/latest/LustreGuide/managing-throughput-capacity.html)
- [Managing Lustre versions](https://docs.aws.amazon.com/fsx/latest/LustreGuide/managing-lustre-version.html)
- [Linking your file system to an Amazon S3 bucket](https://docs.aws.amazon.com/fsx/latest/LustreGuide/create-dra-linked-data-repo.html)
- [CreateFileSystemLustreConfiguration](https://docs.aws.amazon.com/fsx/latest/APIReference/API_CreateFileSystemLustreConfiguration.html)
- [Amazon FSx for Lustre pricing](https://aws.amazon.com/fsx/lustre/pricing/)
