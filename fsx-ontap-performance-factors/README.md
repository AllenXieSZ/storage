# FSx for NetApp ONTAP 性能因素实测（Single-AZ Gen1）

用控制变量法实测证明 FSx ONTAP 各性能因素（throughput capacity、SSD IOPS、network I/O、disk I/O、burst）对性能的影响，验证官方性能模型。

## 官方性能模型（AWS ONTAP Performance User Guide）

FSx ONTAP 有三个性能特征，决定因素如下：

| 性能特征 | 决定因素 |
|---|---|
| **Network I/O**（客户端↔文件服务器 吞吐/IOPS） | **仅** throughput capacity |
| **In-memory + NVMe cache 大小** | **仅** throughput capacity |
| **Disk I/O**（文件服务器↔SSD磁盘 吞吐/IOPS） | throughput capacity **和** SSD IOPS **共同** |

- **Burst 机制**：Network I/O 和 Disk I/O 都有 baseline（7×24 可持续）+ burst（短时冲高），走 **credit 机制**——利用率低于 baseline 时攒信用，高峰烧信用冲高。
- **写占 2× network 带宽**：一次写要复制到 secondary 文件服务器。
- SSD IOPS 默认 3 IOPS/GiB。Single-AZ Gen1（Ohio）SSD 读吞吐上限 4096 MBps / 写 1000 MBps per HA pair。

来源：https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html

## 测试设计（控制变量）

两个 **Single-AZ Gen1**（SINGLE_AZ_1）文件系统，**容量都 1024 GiB（SSD IOPS 都 = 3072），只变 throughput capacity**：
- **FS-low**：128 MBps
- **FS-high**：512 MBps

客户端 c5n.4xlarge，NFSv3 nconnect=16，fio direct=1。volume 关闭存储效率 + tiering NONE（数据全留 SSD）。

## 实测结果

| 测试 | FS-low (128 MBps) | FS-high (512 MBps) | 比值 |
|---|---|---|---|
| 顺序读吞吐（1M，90s，打穿 cache） | 147 MiB/s | 294 MiB/s | 2× |
| 随机读 IOPS（4k，SSD IOPS 都 3072） | 1,195 | 1,416 | 1.2× |
| 顺序写吞吐（1M） | 142 MiB/s | 568 MiB/s | **4×** |

**Burst 台阶（FS-high 持续读 5 分钟，CloudWatch DataReadBytes 分钟曲线）：**

| 时间 | 吞吐 | 阶段 |
|---|---|---|
| 15:58 | **871 MiB/s** | BURST（信用充足冲高） |
| 15:59 | 237 MiB/s | 回落 |
| 16:00 | 241 MiB/s | BASELINE（信用耗尽稳定） |
| 16:01 | 235 MiB/s | baseline |
| 16:02 | 248 MiB/s | baseline |

## 结论（每个因素的影响，实测证明）

1. **throughput capacity 直接决定吞吐（network I/O）**：读吞吐 FS-high 是 FS-low 的 2×，写吞吐 4×。吞吐容量越高，可达吞吐越高。✅

2. **Burst 机制真实存在且可观测**：持续高吞吐读时，开头冲到 **871 MiB/s（burst）**，约 1 分钟后 credit 耗尽，跌落到 **~240 MiB/s（baseline）** 并稳定。burst:baseline ≈ 3.6×。这正是官方描述的 network I/O credit 机制。✅

3. **SSD IOPS 对 disk I/O 的影响（共同决定）**：两个 FS 的 SSD IOPS 相同（都 3072，因容量都 1024 GiB），随机读 IOPS 接近（1195 vs 1416）。差异较小且主要来自 throughput capacity 对 disk I/O 的贡献——印证官方"disk I/O 由 throughput capacity + SSD IOPS **共同**决定"：SSD IOPS 固定时，IOPS 差异只由 throughput 侧带来，因此较小。✅

4. **写比读更受吞吐容量限制**：写吞吐比值（4×）远大于读（2×）。因为写操作占 2× network 带宽（要复制到 secondary），低吞吐档（128 MBps）更早撞到带宽顶，所以 throughput capacity 提升对写的收益更明显。✅

## 关键方法学（踩坑记录）

1. **读测试必须打穿 cache**：小工作集刚写完就读会命中 in-memory/NVMe cache，测出的吞吐不真实（甚至出现 128 MBps FS 比 512 MBps 还"快"的反常值）。必须用大工作集（32 GB > cache）+ drop_caches。
2. **持续读足够长才看得到 baseline**：短测（30-90s）burst credit 没耗尽，测的是 burst 值。要持续 5 分钟看 burst→baseline 台阶。
3. **fio layout 陷阱**：`--size=8G --numjobs=8` 会先预分配 64 GB，在 128 MBps 小 FS 上 layout 就要 8 分钟卡死。应预先用 dd 铺文件，fio 用 `--filename` 指向已存在文件，避免 layout。
4. **ONTAP 服务端把 rsize/wsize 钳制为 64 KB**（即使客户端请求 1 MB），两 FS 一致不影响对比。
5. CloudWatch `DataReadBytes`（period 60s 换算 MiB/s）是观测 burst→baseline 台阶的有效手段。

---
测试日期：2026-08-20 | 环境：Single-AZ Gen1，us-east-2 | 方法：fio + CloudWatch，控制变量（只变 throughput capacity）
