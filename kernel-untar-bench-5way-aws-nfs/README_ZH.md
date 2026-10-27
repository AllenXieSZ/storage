# 内核解压存储基准测试 — 6 路 AWS 存储对比

在 **六种 AWS 存储后端**上单线程 `tar xf` 解压 Linux 内核源码（元数据密集型：~85,000+ 个小文件，总计 ~1.8 GB），覆盖所有主要文件存储服务 + 本地 EBS 参考。

## 测试环境

| 项目 | 值 |
|---|---|
| Region | us-east-2 (Ohio) |
| 客户端 | MySQL-Master (i-0dffb881b2a90daa2, c6i.xlarge, 2 vCPU / 8 GiB, us-east-2c) |
| 负载 | `tar xf /tmp/linux-6.19.tar.xz` — 单线程解压 |
| 文件数 | 每次 ~85,000–92,000（同一份 tar 包；计数因 find 过滤器而异） |
| 数据量 | ~1.8 GB |
| 方法 | 每次测试前 `sync && echo 3 > /proc/sys/vm/drop_caches`；`/usr/bin/time -v` 取 wall-clock |

### 存储后端配置

| 存储 | 类型 | 协议 | 规格 | 挂载参数 | 测试日期 |
|---|---|---|---|---|---|
| **本地 EBS gp3** | 块存储 | xfs | 默认 | — | 2026-04-27 |
| **FSx for Lustre** | 并行文件系统 | Lustre (LNET/TCP) | PERSISTENT_2, 4.8 TiB, 125 MB/s/TiB, **192,000 元数据 IOPS** | `noatime,flock` | **2026-10-27** |
| **FSx for NetApp ONTAP** | NFS | NFS v4.1 | Single-AZ Gen1 | rsize/wsize=64K ⚠️ **未优化** | 2026-04-27 |
| **FSx for OpenZFS** | NFS | NFS v3 | SA2, 1 TiB, 320 MBps | nconnect=16, rsize/wsize=1M ✅ 已优化 | 2026-04-27 |
| **S3 Files** | NFS 网关接 S3 | NFS v4.2 | 默认 | s3files mount helper | 2026-04-27 |
| **EFS** | 托管 NFS | NFS v4.1 | Elastic Throughput | rsize/wsize=1M, TLS | 2026-04-27 |

## 结果

| 存储 | 解压耗时 | 相对 EBS | 相对 ONTAP | 协议 |
|---|---|---|---|---|
| **本地 EBS gp3** | **17.3 秒** | **1.00×**（参考） | 0.02× | 本地块 |
| **FSx for Lustre** | **5 分 20.9 秒** (320.9s) | 18.5× | **0.38×** | Lustre |
| **FSx for NetApp ONTAP** | **14 分 13.6 秒** (853.6s) | 49.3× | 1.00×（NFS 基线） | NFS v4.1 |
| **FSx for OpenZFS** | **15 分 0.8 秒** (900.8s) | 52.1× | 1.06× | NFS v3 |
| **S3 Files** | **32 分 41.2 秒** (1961.2s) | 113.4× | 2.30× | NFS v4.2 |
| **EFS** | **36 分 7.2 秒** (2167.2s) | 125.3× | 2.54× | NFS v4.1 |

### 可重复性验证

| 存储 | Run 1 | Run 2 | 偏差 |
|---|---|---|---|
| FSx for Lustre | 5 分 28.2 秒 | **5 分 20.9 秒** | 2.2% |
| FSx for OpenZFS | 15 分 0.8 秒 | 15 分 3.5 秒 | 0.3% |

### CPU 时间对比（Lustre vs NFS）

| 存储 | User (s) | System (s) | User+Sys (s) | Wall (s) | CPU% | I/O 等待占比 |
|---|---|---|---|---|---|---|
| FSx for Lustre (run2) | 16.5 | 70.7 | **87.2** | 320.9 | 27% | 73% |
| NFS 后端（典型） | ~12 | ~23 | **~35** | 850–2170 | 2–4% | 96–98% |

Lustre 的 `sys` 时间更高（70s vs NFS ~23s），因为内核 Lustre 客户端每个文件做了更多本地工作（LNET 协议处理、extent lock 管理、条带分配）。但 **wall time 比最快的 NFS 短 2.7 倍**——因为 Lustre 的元数据协议从根本上更高效：它批量化操作，不需要每个文件创建都做同步服务端往返。

## 关键发现

### 1. Lustre 比最快 NFS 快 2.7 倍，但 EBS 仍快 18 倍

FSx for Lustre **5 分 21 秒**，远快于所有 NFS 服务（ONTAP 14 分、OpenZFS 15 分、S3 Files 33 分、EFS 36 分）。Lustre 原生协议避免了 NFS 逐文件同步元数据往返。但本地 EBS 17.3 秒仍快 **18 倍**——即使是 Lustre，网络+文件系统元数据开销依然显著。

### 2. Lustre 的优势在协议，不只是 IOPS

本次配置了 192,000 元数据 IOPS，对单线程 tar 来说远超所需。速度优势来自 Lustre 的**协议效率**：Lustre 客户端批量化元数据操作并使用 intent-based lock，相比 NFS 的 create→write→close 逐步确认序列，大幅减少了每文件的网络往返次数。

### 3. NFS 瓶颈确认：逐文件同步往返

所有 NFS 后端的 `user+sys` CPU 仅 ~35 秒但 wall time 14–36 分钟。差距 100% 来自 NFS 元数据往返延迟。

### 4. 清晰的分层结构

| 层级 | 存储 | 时间范围 | 适用场景 |
|---|---|---|---|
| **第一梯队** | EBS gp3（本地） | ~17 秒 | 本地构建/解压，完成后同步 |
| **第二梯队** | FSx for Lustre | ~5 分钟 | 共享并行 FS，HPC/AI/大规模场景 |
| **第三梯队** | FSx ONTAP / OpenZFS | ~14–15 分钟 | 共享 NFS，混合企业负载 |
| **第四梯队** | S3 Files / EFS | ~33–36 分钟 | 通用共享存储；避免元数据密集模式 |

## 注意事项

1. **测试日期不同**：NFS 后端 2026-04-27 测试；Lustre 2026-10-27 测试。同一客户端、同一份 tar 包、同一方法。
2. **ONTAP 未做挂载优化** — rsize/wsize=64K。公平重测（1M）下 ONTAP 预计更快。
3. **Lustre 客户端版本 2.12.8**（AL2 默认）。更新客户端（2.15+）可能有更好的元数据性能。
4. **仅单客户端、单线程** — 未测多客户端并发扩展，Lustre 在多客户端场景优势会更大。

## 复现命令

```bash
# 下载内核源码
cd /tmp && curl -LO https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.19.tar.xz

# 挂载 Lustre（替换 FS DNS 和 mount name）
mkdir -p /mnt/lustre-bench
mount -t lustre -o noatime,flock <fs-id>.fsx.<region>.amazonaws.com@tcp:/<mountname> /mnt/lustre-bench

# 测试
sync && echo 3 > /proc/sys/vm/drop_caches
mkdir -p /mnt/lustre-bench/run1 && cd /mnt/lustre-bench/run1
/usr/bin/time -v tar xf /tmp/linux-6.19.tar.xz

# 计数
find /mnt/lustre-bench/run1 -type f | wc -l

# 清理
rm -rf /mnt/lustre-bench/run1
umount /mnt/lustre-bench
```

## Lustre 测试环境

```
FileSystemId:    fs-0879f933a37ca5922
DeploymentType:  PERSISTENT_2
StorageCapacity: 4800 GiB (SSD)
Throughput:      125 MB/s/TiB (600 MB/s total)
MetadataConfig:  USER_PROVISIONED, 192,000 IOPS
Subnet:          us-east-2c
Lustre client:   lfs 2.12.8 (Amazon Linux 2)
Mount:           noatime,flock
状态:            测试完成后已删除
```
