# 内核解压存储性能对比 —— 四路对比（EFS / S3 Files / JuiceFS / EBS）

在同一台 EC2 客户端上，对四种存储后端进行单线程 `tar xf` 解压 Linux 内核源码的性能对比，并追加 git clone 性能与月成本对比。

## 测试环境

| 项目 | 值 |
|---|---|
| 区域 | us-east-2（俄亥俄） |
| 客户端 | 1× c7i.4xlarge（16 vCPU / 32 GiB），Amazon Linux 2023 |
| Redis 节点（JuiceFS 元数据） | 1× c7i.4xlarge |
| 解压负载 | `tar xf linux-7.2.5.tar.xz`（最新稳定版内核），单线程 |
| 解压文件数 | 101,062 个 / 每种存储 |
| 方法 | 每轮前清空 page cache（`echo 3 > drop_caches`），记录墙钟时间 |

存储后端：
- **EFS (Elastic)** —— Elastic 吞吐模式，NFSv4.1（Phase 1 基准）
- **EFS (Bursting)** —— Bursting 突发吞吐模式，NFSv4.1
- **EBS gp3** —— 本地系统盘，预置 8000 IOPS / 500 MB/s（仅作参考，太快不适合当基准）
- **S3 Files** —— 新服务，NFSv4.2，挂载到开启版本控制的 S3 桶（prefix `s3files/`）
- **JuiceFS** —— Redis 元数据（第二台 EC2）+ S3 数据后端，FUSE 挂载

## 结果 —— Phase 1：`tar xf` 解压（基准 = EFS）

EFS 为基准；EBS 因太快仅作观察参考。

| 存储 | 配置 | 解压耗时 | 文件数 | 相对 EFS |
|---|---|---|---|---|
| EFS (Elastic) | Elastic 吞吐, NFSv4.1 | **39分52秒** (2392s) | 101,062 | 1×（基准） |
| EFS (Bursting) | Bursting 吞吐, NFSv4.1 | **41分37秒** (2497s) | 101,062 | ~1.04× |
| S3 Files | NFSv4.2, 版本控制桶 | **40分08秒** (2408s) | 101,062 | ~1.01× |
| JuiceFS | Redis 元数据 + S3 数据, FUSE | **1小时00分17秒** (3617s) | 101,062 | ~1.51× |
| EBS gp3（仅参考，非基准） | 本地, 8000 IOPS / 500 MB/s | **10.4 秒** | 101,062 | ~0.004× |

## 结果 —— Phase 2：`git clone`（基准 = S3 Files）

串行单线程 `git clone` **NixOS/nixpkgs**（92,712 文件，浅克隆）到各存储后端。每次克隆前清空 page cache。以 S3 Files 为基准，EBS 仅作观察参考。

| 存储 | git clone 耗时 | 文件数 | 相对 S3 Files |
|---|---|---|---|
| S3 Files | **17分16秒** (1035.7s) | 92,712 | 1×（基准） |
| EFS (Elastic) | **16分49秒** (1009.2s) | 92,712 | ~0.97× |
| EFS (Bursting) | **16分32秒** (992.0s) | 92,725 | ~0.96× |
| JuiceFS | **33分02秒** (1981.8s) | 92,712 | ~1.91× |
| EBS gp3（仅参考，非基准） | **5.0 秒** | 92,712 | ~0.005× |

## 要点

本地 EBS 秒级完成这棵 ~10 万文件的目录树；所有网络存储都慢 2 个数量级以上——因为单线程会把每个小文件的 create 串行化，每次都对应一次元数据网络往返，**瓶颈是逐文件延迟，不是带宽**。

- **Phase 1（`tar xf`，基准 = EFS）**：EFS 与 S3 Files 咬得很紧（S3 Files ≈ 1.01× EFS）；JuiceFS 最慢（约 60 分钟，≈ 1.51× EFS），因为每个文件解压时还要经 Redis→S3 路径写一次对象。EBS 快 2 个数量级（10 秒），但仅作参考。
- **Phase 2（`git clone`）**：EFS（Elastic 与 Bursting）与 S3 Files 几乎一致（约 16~17 分钟）；JuiceFS 约为 S3 Files 基准的 1.9 倍。clone 比 tar 快，是因为 git 流式写 pack、fsync 停顿更少，但海量小文件的元数据开销在所有网络存储上仍是主导瓶颈。
- **EFS Bursting vs Elastic**：对这种小而短的负载，Bursting 性能与 Elastic 基本一致（解压 ≈ 1.04× Elastic，clone ≈ 0.96×）——全新/空的 EFS 起步就带满额突发信用，本次吞吐没被限速。但 Bursting **更便宜**：$150/月（纯存储，无单独吞吐费）vs Elastic 的 $195/月。代价：Bursting 的 baseline 吞吐仅为每 GB 存储 50 KB/s，在持续高吞吐的大规模场景下（突发信用耗尽后）会被严重限速，而 Elastic 按需弹性扩展吞吐。**小规模/突发型负载 Bursting 成本占优；持续重 I/O 场景 Elastic（或 Provisioned）更稳妥。**

## Phase 3：月成本估算 —— 每月存储/写入 500 GB（us-east-2）

所有费率取自 AWS Pricing API 官方 us-east-2 价格（2026 年 9 月）：

| 组件 | 费率（us-east-2） |
|---|---|
| EFS Standard 存储 | $0.30 / GB·月 |
| EFS Elastic 吞吐 —— 写 | $0.06 / GB |
| EFS Elastic 吞吐 —— 读 | $0.03 / GB |
| S3 Standard 存储（前 50 TB） | $0.023 / GB·月 |
| S3 Files 高性能存储层 | $0.30 / GB·月 |
| S3 Files 计量 写 / 读 | $0.06 / $0.03 每 GB |
| S3 PUT/COPY/POST/LIST（Tier1） | $0.005 / 1,000 次 |
| S3 GET 及其他（Tier2） | $0.0004 / 1,000 次 |
| c7i.4xlarge Linux 按需 | $0.714 / 小时 |
| EBS gp3 存储 | $0.08 / GB·月 |

**假设：** 每月存储并写入 500 GB；每月读取 500 GB（1 次全量读）；S3 Files 高性能层活跃集 = 全部 500 GB；JuiceFS 使用默认 4 MiB 块 → 500 GB ≈ **128,000 个对象**（写 128k PUT + 读 128k GET）；JuiceFS 的 Redis 独占一台 c7i.4xlarge 全天候运行（720 小时）+ 30 GB gp3 系统盘。

| 存储 | 存储费 | 吞吐 / 请求费 | 计算(Redis) | **月总计** |
|---|---|---|---|---|
| EFS (Elastic) | $150.00 | $45.00（写 30 + 读 15） | — | **$195.00** |
| EFS (Bursting) | $150.00 | —（已含在存储费中） | — | **$150.00** |
| S3 Files | $161.50（$11.5 S3 + $150 高性能层） | $45.69（写30 + 读15 + 请求0.69） | — | **$207.19** |
| JuiceFS | $11.50（S3 Standard） | $0.69（128k PUT + 128k GET） | $516.48（$514.08 EC2 + $2.40 EBS） | **$528.67** |

**关键 —— 500 GB 下最便宜的选择 & JuiceFS 的 TCO 反转：** 只看「存储 + IO」，JuiceFS 便宜到离谱（约 $12/月——只付 S3 Standard），EFS（$195）也略优于 S3 Files（$207）。但**独占的 Redis EC2 是 JuiceFS 的隐性 TCO 大头**：一台 c7i.4xlarge 全天候运行每月增加约 $514，把 JuiceFS 顶到 **$529/月——成为三者中最贵**，约为全托管 EFS 的 2.7 倍。托管的 EFS 与 S3 Files 没有这个「计算底座」成本，所以在中小规模（500 GB）决定性胜出。JuiceFS 的经济性只有在容量大得多时才转为有利——那时固定的 Redis/计算成本被摊薄到许多 TB 上，其廉价的 S3 Standard 存储（$0.023/GB·月 vs $0.30）才占主导；而且那种场景你会合理调优（或共用）元数据节点，而不是独占一台 c7i.4xlarge。**500 GB 规模，EFS 是最划算的理性选择；JuiceFS 只有在无视其必需的元数据服务器时才「最便宜」。**
