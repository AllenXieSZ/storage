# 内核解压存储基准测试 — 5 路 AWS NFS 对比

在 **五种 AWS 存储后端**上单线程 `tar xf` 解压 Linux 内核源码（元数据密集型：~85,000 个小文件，总计 1.8 GB），包括 FSx for NetApp ONTAP 和 FSx for OpenZFS。

## 测试环境

| 项目 | 值 |
|---|---|
| Region | us-east-2 (Ohio) |
| 客户端 | MySQL-Master (i-0dffb881b2a90daa2, c6i.xlarge, 2 vCPU / 8 GiB, us-east-2c) |
| 负载 | `tar xf /tmp/linux-6.19.tar.xz` — 单线程解压 |
| 文件数 | 每次 ~85,000 个 |
| 数据量 | ~1.8 GB |
| 方法 | 每次测试前 `sync && echo 3 > /proc/sys/vm/drop_caches`；`/usr/bin/time` 取 wall-clock |
| 日期 | 2026-04-27 |

### 存储后端配置

| 存储 | 类型 | 挂载协议 | 挂载参数 |
|---|---|---|---|
| **本地 EBS gp3** | 块存储（本地） | xfs | 默认（仅做参考） |
| **FSx for NetApp ONTAP** | NFS 文件服务器 | NFS v4.1 | rsize/wsize=64K ⚠️ **未优化** |
| **FSx for OpenZFS** | NFS 文件服务器 | NFS v3 | nconnect=16, rsize/wsize=1M ✅ 按 User Guide 优化 |
| **S3 Files** | NFS 网关接 S3 | NFS v4.2 | 默认 s3files mount helper |
| **EFS** | 托管 NFS | NFS v4.1 | rsize/wsize=1M, TLS |

**关于 ONTAP 挂载参数的说明：** ONTAP 使用默认 rsize/wsize=64K（未调优到 1M）。尽管有此劣势，它仍然比经过完整优化的 OpenZFS 快约 50 秒——说明 ONTAP 的元数据处理能力本身更优。若用优化参数重测，差距预计会更大。

## 结果

| 存储 | 解压耗时 | 相对 ONTAP | 挂载参数 |
|---|---|---|---|
| 本地 EBS gp3 | **17.3 秒** | 0.02×（参考） | — |
| **FSx for NetApp ONTAP** | **14 分 13.6 秒** (853.6s) | **1.00×**（基线） | NFS v4.1, rsize/wsize=64K ⚠️ |
| **FSx for OpenZFS** | **15 分 0.8 秒** (900.8s) | 1.06× | NFS v3, nconnect=16, rsize/wsize=1M ✅ |
| **S3 Files** | **32 分 41.2 秒** (1961.2s) | 2.30× | NFS v4.2 |
| **EFS** | **36 分 7.2 秒** (2167.2s) | 2.54× | NFS v4.1, rsize/wsize=1M, TLS |

### 可重复性验证

OpenZFS 跑了两次：15 分 0.8 秒 和 15 分 3.5 秒（偏差 < 0.3%），确认结果可重复。

## 关键发现

### 1. 瓶颈 100% 是 NFS 元数据 round-trip，不是带宽

五种 NFS 后端的 `user+sys` CPU 时间都只有 ~35 秒——与本地 EBS 解压几乎一致。剩下的十几分钟 wall-clock 全在等 NFS 元数据往返：每个 `mkdir`、`open(O_CREAT)`、`write`、`close` 都需要同步等服务端确认才能开始下一个操作，~85,000 个文件逐个串行。

### 2. ONTAP 在未优化挂载参数下仍然最快

FSx ONTAP 用默认 rsize/wsize=64K（未调优）挂载，仍比用 User Guide 全套优化（NFS v3 + nconnect=16 + rsize/wsize=1M）的 OpenZFS **快约 50 秒**。这说明 ONTAP 的 WAFL 文件系统和元数据缓存在高频小文件创建场景下本身就更高效。

### 3. S3 Files 和 EFS 比 ONTAP/OpenZFS 慢约 2 倍

S3 Files 和 EFS 的耗时大约是 FSx 系列的两倍。在元数据密集型负载（大量小文件）下，这两个服务的单次操作延迟明显更高。

### 4. nconnect=16 对单线程 tar 无帮助

OpenZFS 开了 `nconnect=16`（16 条并行 TCP 连接），但 `tar` 是单线程的，元数据操作串行执行，一次只用一条连接。`nconnect` 对多线程并发 I/O 有帮助，对串行元数据密集型负载没用。

### 5. 本地 EBS 快 ~50 倍——这正是核心结论

EBS 17.3 秒 vs NFS 14 分钟以上（~50 倍差距），清晰展示了网络元数据往返的代价。对于元数据密集型负载（包安装、源码树解压、大量小文件的构建系统），建议：

- **在本地 EBS 上解压/构建**，完成后再同步到共享存储
- **使用缓存层**（如 FSx for Lustre PCC、JuiceFS 客户端缓存）在本地吸收元数据开销
- **重构负载**，用更少更大的文件（tar 包、容器镜像）替代海量小文件

## 分层总结

| 层级 | 存储 | 相对速度 | 适用场景 |
|---|---|---|---|
| **第一梯队** | EBS gp3（本地） | 快 50× | 本地构建/解压，完成后同步 |
| **第二梯队** | FSx ONTAP, FSx OpenZFS | 1.0–1.06× | 混合负载下最佳共享 NFS |
| **第三梯队** | S3 Files, EFS | 2.3–2.5× | 通用共享存储；避免元数据密集模式 |

## 注意事项

1. **ONTAP 未做挂载优化** — rsize/wsize=64K vs OpenZFS 的 1M。公平重测（1M）下 ONTAP 预计更快。
2. **三个后端（EFS/S3 Files/ONTAP）在同一台 2vCPU 客户端上并行跑**，可能有轻微 CPU 争抢。但 CPU user+sys 仅 ~35s vs 14 分钟以上的 wall time，瓶颈显然在网络不在 CPU。
3. **仅单客户端、单线程** — 未测多客户端并发扩展性。
4. **内核版本：** Linux 6.19（~85K 文件）。更新内核文件数可能略有不同。

## 本仓库相关测试

- [`kernel-untar-bench-4way`](../kernel-untar-bench-4way/) — EFS / S3 Files / JuiceFS / EBS 四路对比（不同内核版本、不同客户端）
- [`kernel-untar-bench-5client-concurrent`](../kernel-untar-bench-5client-concurrent/) — 5 客户端并发测试（EFS / S3 Files / JuiceFS）
- [`kernel-untar-bench-mountopt`](../kernel-untar-bench-mountopt/) — 挂载参数优化影响
- [`kernel-untar-bench-phase3-npm`](../kernel-untar-bench-phase3-npm/) — npm install 基准测试
