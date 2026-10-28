# FSx for Lustre 4K 随机读放大 — 穿透缓存实测验证

**测试日期：2026-10-27 | Region：us-east-2 (Ohio)**

## 核心结论

4K 随机读 miss OSS 内存缓存时，每个 4K 客户端请求导致 OSS 从磁盘读取 **256KB** — **~26 倍读放大**。磁盘吞吐利用率打到 90–102%，而客户端只拿到 ~80 MB/s（占 2,400 MB/s 保证吞吐的 3.3%）。

AWS 文档印证了这个设计：推荐使用 **>256KB 的传输大小**才能达到预期吞吐。

## 为什么是 256KB？

### AWS 文档原文

> *FSx Lustre file system allows customer to scale to millions of IOPS for read and write, but has no explicit SLA or provisioned data IOPS expectation. Today, we only measure performance by aggregate throughput. To achieve the expected throughput, customer application needs to drive enough parallelism and **using meaningful transfer size (>256k)**.*

256KB 是 FSx Lustre **磁盘层的最小有效 I/O 单元**。任何小于 256KB 的 I/O 仍然消耗 256KB 的磁盘吞吐。

### stripe_size (1MB) 的含义

| 概念 | 值 | 控制什么 |
|---|---|---|
| **stripe_size** | 1MB（默认 PFL） | 数据跨 OST 分布：每 1MB 切到下一个 OST |
| **磁盘 I/O 粒度** | **256KB** | OSS 从底层 SSD 读取的最小单元 |
| **ldiskfs 块大小** | 4KB | 文件系统分配粒度（不是 I/O 粒度） |

Lustre Wiki 原文：
> *stripe_size does not affect the allocation size of the file on disk (which is controlled by the underlying OST filesystem, typically 4KB for ldiskfs), but only the distribution of file data across OSTs.*

## 测试环境

| 组件 | 配置 |
|---|---|
| FSx Lustre | PERSISTENT_2, 4800 GiB SSD, 500 MB/s/TiB |
| 保证磁盘吞吐 | 4.8 TiB × 500 = **2,400 MB/s** |
| OSS 内存缓存 | ~65.76 GiB（13.7 GiB/TiB × 4.8 TiB） |
| OST | 4 个，stripe_count=-1，stripe_size=1M |
| OSS | 2 个（各服务 2 个 OST） |
| EC2 客户端 | c6i.4xlarge (16 vCPU, 32 GiB), AL2023 |
| Lustre 客户端 | 2.15.6 |
| 测试数据 | 4 × 50GB = 200GB（远超 66GB 缓存） |

## 测试方法

1. **缓存污染**：顺序读 bigfile_1/2/3（150GB），把 ~66GB OSS 缓存填满非测试文件的数据
2. **4K 随机读**：对 bigfile_0（50GB）做 fio 4K randread，8 组不同 QD，每组 60 秒
3. **收集 CloudWatch**：DataReadBytes（客户端侧）vs DiskReadBytes（磁盘侧）直接对比

## 结果

### fio 客户端性能

| 测试 | QD | IOPS | 吞吐 (MiB/s) | 平均延迟 (µs) | p99 (µs) |
|---|---|---|---|---|---|
| T1 | 1 | 836 | 3.3 | 1,182 | 1,499 |
| T2 | 16 | 21,560 | 84.2 | 730 | 1,647 |
| T3 | 64 | 23,605 | 92.2 | 2,700 | 18,481 |
| T4 | 128 | 23,643 | 92.4 | 5,402 | 35,914 |
| T5 | 128 | 23,574 | 92.1 | 5,417 | 35,914 |
| T6 | 256 | 23,579 | 92.1 | 10,843 | 69,730 |
| T7 | 512 | 23,517 | 91.9 | 21,755 | 131,596 |
| T8 | 1024 | 23,381 | 91.3 | 43,780 | 261,095 |

**IOPS 在 QD≥16 时即触顶 ~23,500，加 QD 只加延迟不加 IOPS。**

### CloudWatch 读放大实测（核心数据）

| 时间 (UTC) | 客户端 DataReadBytes | 磁盘 DiskReadBytes (4 OST) | **读放大** | 阶段 |
|---|---|---|---|---|
| 10:25 | 80.2 MB/s | 2,018 MB/s | **25.2×** | T1→T2 |
| 10:26 | 79.1 MB/s | 2,082 MB/s | **26.3×** | T2–T3 |
| 10:27 | 79.5 MB/s | 2,080 MB/s | **26.2×** | T3–T4 |
| 10:28 | 79.3 MB/s | 2,077 MB/s | **26.2×** | T4–T5 |
| 10:29 | 79.3 MB/s | 2,276 MB/s | **28.7×** | T5–T6 |
| 10:30 | 79.1 MB/s | 2,179 MB/s | **27.5×** | T6–T7 |
| 10:31 | 78.4 MB/s | 2,058 MB/s | **26.3×** | T7–T8 |

**稳态读放大：25.2×–28.7×，中位约 26×**

### 磁盘吞吐利用率 (FileServerDiskThroughputUtilization)

| 时间 | OSS0000 | OSS0002 |
|---|---|---|
| 10:26 | 92.94% | 93.38% |
| 10:29 | **101.25%** | **102.45%** |

**两个 OSS 都打到 90–102%**，磁盘吞吐完全饱和。同时 DiskIopsUtilization 仅 ~58%（瓶颈不是 IOPS 数量），NetworkThroughputUtilization < 1%（瓶颈不是网络）。

### 256KB 磁盘 I/O 粒度的推导

```
每 OST DiskReadBytes:    ~520 MB/s
每 OST DiskReadOps:      ~2,078 ops/s
每次磁盘 I/O 大小:      520 ÷ 2,078 = ~256 KB/op
```

## 与缓存命中测试的对比

| 指标 | 8GB 工作集（全缓存） | 50GB 工作集（穿透缓存） | 变化 |
|---|---|---|---|
| IOPS | 252,000 | 23,500 | **↓ 10.7×** |
| 客户端吞吐 | ~985 MB/s | ~80 MB/s | **↓ 12.3×** |
| 磁盘利用率 | < 0.01% | **90–102%** | 缓存→磁盘 |

**8GB 工作集的 252K IOPS 不反映真实磁盘性能——全是缓存在服务。**

## 不同 I/O 大小的有效吞吐（缓存 miss 时）

| 客户端 IO 大小 | 磁盘实际读 | 放大倍数 | 2,400 MB/s 有效利用 |
|---|---|---|---|
| 4K | 256K | 64× | ~38 MB/s (1.6%) |
| 16K | 256K | 16× | ~150 MB/s (6.3%) |
| 64K | 256K | 4× | ~600 MB/s (25%) |
| **256K** | **256K** | **1×（无放大）** | **2,400 MB/s (100%)** |
| 1M | 1M | 1× | 2,400 MB/s (100%) |

## OSS 内存缓存大小

| 吞吐档 | 缓存 (GiB/TiB) | 4.8 TiB 总缓存 |
|---|---|---|
| PERSISTENT-125 | 3.4 | 16.3 GiB |
| PERSISTENT-250 | 6.8 | 32.6 GiB |
| **PERSISTENT-500** | **13.7** | **65.8 GiB** |
| PERSISTENT-1000 | 27.3 | 131.0 GiB |

## 对比：FSx ONTAP 没有 256KB 读放大

**测试日期：2026-10-28** — 用相同方法测试 FSx ONTAP Gen2 SA2。

### ONTAP 磁盘 IO 粒度（CloudWatch 实测）

| 客户端 IO | Lustre 磁盘 IO | **ONTAP 磁盘 IO** | Lustre 放大 | **ONTAP 放大** |
|---|---|---|---|---|
| 4K | 256 KB | **~4 KB（低压）/ ~16 KB（高压）** | 64× | **1×–4×** |
| 8K | 256 KB | ~8 KB | 32× | ~1× |
| 16K | 256 KB | ~16 KB | 16× | ~1× |
| 32K | 256 KB | ~30 KB | 8× | ~1× |
| 256K | 256 KB | ~58–97 KB | 1× | ~1× |

**核心差异**：Lustre 磁盘 IO 粒度恒定 256KB；ONTAP 的 WAFL 基本按客户端请求大小读磁盘（高 IOPS 时有 4× readahead，4K→16KB）。

### ONTAP 顶配测试（6144 MBps, 5 TiB SSD, 200K Provisioned IOPS）

**缓存命中（8GB 工作集）：**

| 客户端数 | 聚合 IOPS | DiskIopsUtil |
|---|---|---|
| 1 台 | **188,692** | ~0% |
| 2 台 | **385,188** | ~0% |
| 4 台 | **776,024** | ~0% |

**穿透缓存（2TB 工作集）：**

| 客户端数 | 工作集 | 客户端聚合 IOPS | CW 磁盘 IOPS | **DiskIopsUtil** |
|---|---|---|---|---|
| 1 | 500 GB | 190,182 | ~13 | ~0%（仍全缓存！） |
| 2 | 1 TB | 381,103 | ~670 | ~0%（仍全缓存！） |
| 4 | 1 TB | 526,387 | 126,885 | **63.4%** |
| **4** | **2 TB** | **520,387** | **200,260** | **🔴 100.1%（触顶！）** |

### Lustre vs ONTAP 架构对比（4K 随机读）

| 指标 | FSx Lustre (P2-500, 4.8 TiB) | FSx ONTAP (6144 MBps, 5 TiB, 200K IOPS) |
|---|---|---|
| 磁盘 IO 粒度 | **256 KB**（恒定） | **~16 KB**（高负载时） |
| 4K 读放大 | **64×** | **4×** |
| 4K IOPS（缓存命中，4客户端） | ~252K（单客户端） | **776K** |
| 4K IOPS（穿透缓存） | **~23,500** | **~200,000**（磁盘）/ ~520,000（客户端含缓存） |
| 服务端缓存 | ~66 GB | **~1–2 TB** |
| 穿透缓存瓶颈 | 磁盘**吞吐**（256KB×IOPS 打满带宽） | 磁盘 **IOPS**（provisioned IOPS 上限） |
| 月费 | **~$696** | **~$9,000+** |

### Lustre 要达到 200K 4K IOPS 需要多大？

因为 256KB 读放大，200K IOPS 需要：

```
200,000 IOPS × 256 KB = 51,200 MB/s = 50 GB/s 磁盘吞吐
```

| Lustre 档位 | 磁盘吞吐/TiB | 需要容量 | 月费 |
|---|---|---|---|
| P2-125 | 125 MB/s | 400 TiB | ~$43,000 |
| P2-250 | 250 MB/s | 200 TiB | ~$24,576 |
| **P2-500** | 500 MB/s | **100 TiB** | **~$14,848** |
| **P2-1000** | 1000 MB/s | **50 TiB** | **~$14,848** |

### 4K 随机读成本效率总结

| 配置 | 4K IOPS (磁盘) | 月费 | $/千IOPS |
|---|---|---|---|
| **Lustre P2-500, 4.8 TiB** | 23,500 | $696 | **$29.6** |
| ONTAP 3072, 1 TiB (auto IOPS) | 3,062 | $1,618 | $528.7 |
| **ONTAP 6144, 5 TiB, 200K IOPS** | **200,000** | ~$9,000 | **$45.0** |
| Lustre P2-500, 100 TiB (追平200K) | ~200,000 | ~$14,848 | $74.2 |
| Lustre P2-1000, 50 TiB (追平200K) | ~200,000 | ~$14,848 | $74.2 |

**结论：**
- 小规模（<50K IOPS）：**Lustre 最便宜**（$29.6/千IOPS）
- 大规模（200K IOPS）：**ONTAP 更便宜**（$45 vs $74/千IOPS），因为不浪费吞吐在读放大上
- ONTAP 缓存（6144 档 ~1-2TB）可服务 776K+ IOPS——**工作集在缓存内时 ONTAP 完胜**
- Lustre 优势在顺序吞吐：50 TiB P2-1000 有 50 GB/s 大块读写能力
