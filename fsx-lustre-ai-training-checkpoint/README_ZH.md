# FSx for Lustre × 大模型预训练：Checkpoint / 元数据风暴 / 故障恢复实测

测试日期：2026-10-15（us-east-2）
目的：从 FSx for Lustre 的角度量化预训练中 **checkpoint 写入、训练启动（元数据风暴）、故障恢复读放大** 三类负载，并验证 EFA 对单客户端吞吐的影响，作为存储容量 / 吞吐档位 / 元数据 IOPS 规划依据。

> 说明：2026-10-16 复核后更正第 4 节 ENA 结论（单客户端 ↔ 单 OSS 实测约 9.5 Gbps，不是 5 Gbps）；多 EFA 网卡机型在多 OSS FS 上高并发写入断连的问题，根因与规避见 [`../fsx-lustre-efa-client-disconnect/`](../fsx-lustre-efa-client-disconnect/README_ZH.md)。GPUDirect Storage（GDS）尚未测试。

## 1. 结论速览

| 主题 | 结论 |
|---|---|
| **Checkpoint 写入** | 512 个分片并发写，DCP 同步保存跑到 **22.5 GB/s = FS 基线的 94%**，瓶颈是 FS 预置吞吐（容量 × 档位），不是客户端 |
| **条带** | 多分片（每 rank 一个文件）时，默认 PFL / 全条带 / 单条带相差 < 8%，**默认 PFL 即可**；少分片（每节点一个 48 GiB 大文件）吞吐下降约 25% |
| **异步保存** | `dcp.async_save` 把训练阻塞时间从 **37 s 降到 0.43 s（−98.8%）**，总落盘时间不变 |
| **EFA vs ENA** | 同一客户端、同一 FS：EFA 读 **182 Gbps**（200 Gbps 网卡的 91%），ENA（TCP）**74.4 Gbps**，**EFA 约 2.4 倍**；ENA 单客户端 ↔ 单 OSS 实测约 9.5 Gbps |
| **元数据风暴** | 1600 进程同时 `import torch` 等：环境放 Lustre P50 **19.2 s**，放本地盘 **7.7 s**（Lustre 慢 2.5 倍）；MDS CPU 仅 22%，瓶颈是逐文件元数据往返延迟 |
| **扩元数据 IOPS** | 12k → 24k 在线完成（约 12 分钟），**只对扩容后新建的目录生效**：重新复制的 venv P50 降到 14.9 s（快 23%），旧目录不变 |
| **大目录** | 16 客户端同时 `ls -l` 同一个 20 万文件目录：平均 39 s、最慢 54 s；拆成 20 × 1 万文件目录：平均 1.6 s。`statahead_xattr=1` 使 `ls -l` 快约 31% |
| **换拓扑恢复** | DCP load-time resharding（512→256 / 512→384）**FS 侧读放大 1.00×**；边界不对齐时恢复慢约 20% |
| **DP 副本重复读** | 不开 fully-parallel-load 时，DP 组内每个副本都读同一份权重 → **FS 读放大 = DP 副本数（实测 15×）**；开启后 1.0×（⚠️ 用 DCP + gloo 模拟，未真跑 Megatron） |

## 2. 测试环境

| 项 | 规格 |
|---|---|
| 主文件系统 | PERSISTENT_2 SSD，**24,000 GiB @ 1000 MB/s/TiB**（基线约 24 GB/s），**EFA 开启**，Lustre 2.15，元数据 USER_PROVISIONED **12,000 IOPS**（中途在线扩到 24,000）。实际 **5 个 OST / 5 个 OSS**（与文档 "EFA 1000 档每 OSS 4.8 TiB" 一致） |
| 单客户端测试用 FS | 72,000 GiB @1000（15 OST，基线约 72 GB/s），EFA，元数据 AUTOMATIC |
| 客户端 | **16 × c8gn.16xlarge**（Graviton4，64 vCPU，128 GiB，200 Gbps，1 个 EFA），AL2023 kernel 6.12，lustre-client 2.15.6，按官方 `configure-efa-fsx-lustre-client/setup.sh` 配置，LNet 走 `@efa` |
| 软件 | PyTorch 2.14.1+cpu（gloo），transformers 5.19.0，numpy 2.4.6，fio 3.32 |

> 机型说明：c6in.32xlarge / c7gn.16xlarge 等在 3 个 AZ 均无容量，改用网络规格相同（200 Gbps + EFA）的 c8gn.16xlarge。CPU 机型无法测 pinned memory 与 GDS。

## 3. Checkpoint 写入

规模：16 节点 × 32 rank = **512 rank**，每 rank 1.5 GiB（模拟 ZeRO 分片：bf16 权重 + fp32 主权重 + Adam m + v = 14 B/参数），**每个 checkpoint 768 GiB**，生成 512 个 `.distcp` + 1 个 `.metadata`。每次测试前全部节点 drop_caches + ldlm lru clear。

| 场景 | 训练阻塞 | 完整落盘 | 聚合吞吐 | 占 FS 基线 |
|---|---|---|---|---|
| 同步 `dcp.save`，默认 PFL（2 次） | 36.7 / 36.5 s | 同左 | **22.5 GB/s** | 94% |
| 同步 `dcp.save`，全条带 `-c -1`（2 次） | 37.1 / 37.2 s | 同左 | 22.2 GB/s | 92% |
| 同步 `dcp.save`，单条带 `-c 1` | 34.4 s | 同左 | 24.0 GB/s | 100% |
| **异步 `dcp.async_save`，默认 stager**（2 次） | **0.43 s** | 37.5 / 37.1 s | 22.1 GB/s | 92% |
| 异步，`DefaultStager(use_shared_memory=True, use_async_staging=True)`（2 次） | 1.36 s | 38.7 / 38.4 s | 21.4 GB/s | 89% |
| 少分片：每节点 1 个 48 GiB `torch.save` 文件，默认 PFL（2 次） | 47.4 s | 同左 | 17.4 GB/s | 72% |
| 少分片：每节点 1 个 48 GiB 文件，全条带（2 次） | 50.2 / 46.8 s | 同左 | 16.4–17.6 GB/s | 70% |

**结论**
1. **多分片 DCP 能把 FS 写满**（基线的 92–100%）。按此比例推算：10.6 TB 的 checkpoint 要在 2 分钟内写完，需要约 90 GB/s，即约 **90 TiB @1000 MB/s/TiB**。
2. **多分片时条带方式基本无影响**（< 8%）：512 个文件本身已均匀分布到所有 OST。
3. **少分片损失约 25% 吞吐**：每节点只有一个写线程，并发不足以打满 OSS。
4. **异步保存使训练阻塞 −98.8%**。torch 2.14 `async_save` 默认 stager 为 `DefaultStager(StagingOptions(False,False,False,False))`（不 pin、不用共享内存、同步 staging）；打开 shared-memory + async staging 反而阻塞 1.36 s（多一次拷贝到 /dev/shm）。CPU 机型上 `pin_memory` 不可用，pinned memory 路径未测。
5. **无 OST 热点**：5 个 OST 的 DiskWriteBytes 峰值均为 2.78 GB/s；`NetworkThroughputUtilization` 最高约 11%。注意 CloudWatch 为 1 分钟粒度，单次写入只有约 36 s，利用率被平均摊低。
6. CloudWatch `DataWriteBytes` 与客户端统计一致（每次 768 GiB）。

## 4. 单客户端链路：EFA vs ENA

FS：72 TiB / 15 OSS（基线 72 GB/s），避免单客户端先被 FS 卡住。fio：16 MiB 块，O_DIRECT，libaio iodepth 8，每 job 一个 8 GiB 文件，目录全条带。

| 客户端 / 链路 | 写 | 读 | 文档上限 |
|---|---|---|---|
| **c8gn.16xlarge + EFA**（numjobs 16/32/64） | 20.2 / 21.7 / **21.8 GB/s（175 Gbps）** | 20.3 / **22.7** / 22.1 GB/s（**182 Gbps**） | EFA 700 Gbps；本机网卡 200 Gbps，已达网卡 91% |
| **c8gn.16xlarge + ENA（TCP）**，同一台机器、同一 FS | 8.6 / 8.5 GB/s（68 Gbps） | **9.3 GB/s（74.4 Gbps）** | ENA 100 Gbps；文档写单客户端 ↔ 单 OSS 5 Gbps（实测约 9.5 Gbps，见下） |

**结论**
1. **EFA 比 ENA 高约 2.4 倍**（读 182 vs 74 Gbps），唯一变量是 LNet 走 efa 还是 tcp。
2. **ENA 单机吞吐 ≈ min(约 9.5 Gbps × OSS 数, 约 74 Gbps)**（2026-10-16 复核，c8gn.16xlarge，lustre 2.15.6）：
   - 单 OST / 单 OSS 读写都是 **9.53 Gbps**（numjobs 1/8/32 相同，两个 FS 各复现一次；网卡计数 9.2–9.3 Gbps）。数据只走 1 条 TCP 连接，`conns_per_peer=4` 无变化。
   - 2 OSS = 19.06 Gbps（线性）；15 OSS = 74.4 Gbps（单客户端饱和，客户端 CPU 93% 空闲、ENA allowance 计数为 0，瓶颈未定位）。
   - 对照：同子网 EC2 ↔ EC2 iperf3 单流 4.97 Gbps，符合 EC2 单流 5 Gbps 限制；客户端 ↔ FSx OSS 不受该限制。文档"单客户端 ↔ 单 OSS 5 Gbps"可作保守值。
   - ⚠️ 本文初版写"15 OSS × 5 Gbps ≈ 74.4 Gbps，即每 OSS 限 5 Gbps"是数字巧合，已更正。

## 5. 元数据风暴（训练启动）

场景：16 节点 × 100 进程 = **1600 个进程同时启动**（统一 GO 时刻对齐）。每个进程：`import torch, transformers, numpy` → `json.load` 50 个配置 → `Tokenizer.from_file`（2 MB）→ 对 8 个 64 MiB `.npy` 做 `np.load(mmap_mode='r')` 并读元素。Lustre 上 venv 34,504 个文件、约 1.1 GB。每次前所有节点 drop_caches + lru clear，时间从 GO 起算。

| 场景 | 进程数 | P50 | P90 | P99 | Max | MDS（CloudWatch 1 分钟平均） |
|---|---|---|---|---|---|---|
| **本地 EBS gp3**（2 次） | 1600 | **7.7 s** | 8.0 s | 8.0–8.3 s | 8.3 s | — |
| **Lustre，MD 12,000 IOPS**（2 次） | 1600 | **19.2 / 19.5 s** | 20.9 / 20.5 s | 21.2 / 21.8 s | 21.3 / 22.0 s | MetadataOperations 约 5.2 万/s，FileOpen 约 5.0k/s，Stat 约 3.6k/s，MDS CPU 22% |
| Lustre，MD 24,000，**旧目录**（扩容前建的 venv，仍在 MDT0）（2 次） | 1600 | 19.5 / 19.8 s | 20.8 / 21.0 s | 21.5 / 22.5 s | 22.7 s | MDS0000 CPU 22% |
| **Lustre，MD 24,000，新目录**（扩容后复制，分布在 MDT0 + MDT1）（2 次） | 1600 | **14.9 / 14.9 s** | 17.0 / 17.3 s | 17.7 / 18.4 s | 18.6 s | 两个 MDS 负载 9.5% / 14.3% |
| 本地 | 256 | 5.5 s | 5.6 s | 5.6 s | 5.6 s | |
| Lustre 12k | 256 | 10.2 s | 11.8 s | 13.3 s | 13.3 s | |
| 本地 | 16 | 4.9 s | 4.9 s | 4.9 s | 4.9 s | |
| Lustre 12k | 16 | 6.9 s | 8.8 s | 10.4 s | 10.4 s | |

客户端 llite 统计（单节点 100 进程）：open 57.7 万次，getattr 235 万次，getxattr 214 万次。Lustre 多出的时间基本都在 import 阶段（import P50 18.6 s vs 本地 7.3 s）。

**结论**
1. **1600 进程冷启动，Lustre 比本地盘慢约 2.5 倍**；进程数从 16 增到 1600，Lustre P50 从 6.9 s 涨到 19.2 s，本地只从 4.9 s 涨到 7.7 s。
2. **MDS 未被打满**（CPU 22%）。推测（未实测）：瓶颈是每个进程 import 时逐个 stat/open 的串行往返延迟，而非 IOPS 配额。CloudWatch 是 1 分钟 Sum，突发只有约 20 s，真实峰值速率约为表中数字的 3 倍。
3. **扩 MD IOPS 只对新目录生效**：IOPS 超过 12000 会新增 MDS，但扩容前已有的目录元数据仍在原 MDS 上。**扩容后需要重新复制一次 Python 环境 / 数据索引目录**。
4. 扩容（12000 → 24000）**在线完成，约 12 分钟**，期间读测试无异常。
5. **最实用的优化**：训练环境放本地盘或容器镜像（如 Enroot `.sqsh` 放 Lustre、运行时解压到本地 NVMe），本地 P50 比 Lustre 24k 档还快 1.9 倍，且不消耗 MDS。

### 附：大目录 vs 分目录（200K 空文件）

| 操作 | 单目录 200K 文件 | 20 个目录 × 10K 文件 |
|---|---|---|
| 16 客户端并行创建（墙钟） | 27.6 s | 31.0 s |
| 单客户端 `ls -l`，statahead_xattr=0 | 33.0 s | 1.6 s（10K 条，折合 200K 约 32 s） |
| 单客户端 `ls -l`，statahead_xattr=1 | **22.7 s（快 31%）** | 1.1 s（快 32%） |
| **16 客户端同时 `ls -l`**（xattr=1） | **平均 39.4 s，最慢 53.8 s** | 平均 1.6 s，最慢 2.2 s |
| 随机 stat 10K 个文件 | 2.83 s | 2.78 s |

- 单客户端 `ls` 耗时与条目数成正比；**差别出现在并发**：多客户端同时扫同一大目录时争父目录锁，最慢者恶化到 54 s。与文档"每目录 < 100K 文件"的建议一致。
- `statahead_xattr=1`（FSx performance-tips 页唯一推荐的客户端调优）在多客户端下仍使 `ls -l` 快约 31%。注意该参数重启后会恢复为 0，需开机脚本重新设置（脚本中需设置 PATH 并等待 Lustre 挂载完成）。

## 6. 故障恢复读放大

数据：第 3 节写出的 768 GiB DCP checkpoint（world = 512）。"客户端读字节"为 16 节点 llite `read_bytes` 之和，并与 CloudWatch `DataReadBytes` 核对。

| 恢复场景 | world | 恢复耗时 | 聚合读 | 客户端读字节 | CloudWatch DataReadBytes | **FS 读放大** |
|---|---|---|---|---|---|---|
| 同拓扑 `dcp.load`，PFL（2 次） | 512 | 34.2 s | 24.1 GB/s | 798 GiB | 768 GiB | **1.00×**（多出的 30 GiB 为客户端预读，未到 FS） |
| 同拓扑，全条带 | 512 | 34.2 s | 24.1 GB/s | 798 GiB | — | 1.00× |
| 换拓扑 512→256，按 key 重新分配 | 256 | 31.3 s | 26.4 GB/s | 798 GiB | — | **1.00×** |
| **DTensor 重分片** Shard(0) 512→256（边界对齐） | 256 | 34.5 s | 23.9 GB/s | 798 GiB | 768 GiB | **1.00×** |
| DTensor 重分片 512→512（对照） | 512 | 32.1 s | 25.7 GB/s | 798 GiB | 768 GiB | 1.00× |
| **DTensor 重分片 512→384**（边界不对齐） | 384 | **40.1 s** | 20.6 GB/s | **1197 GiB** | **768 GiB** | **FS 1.00×；客户端页缓存层 1.56×** |
| 少分片：每节点 48 GiB 单文件 torch.load | 16 读者 | 33.1 s | 24.9 GB/s | 768 GiB | — | 1.00× |
| **模拟：不开 fully-parallel-load**（DP=15，每副本完整读同一份模型分片） | 480 | 7.5 s | 103.8 GB/s（含缓存命中） | 748 GiB | **720 GiB** | **15×**（唯一数据 48 GiB） |
| **模拟：开启 fully-parallel-load**（DP 组内每成员读 1/N，再 broadcast） | 480 | 12.4 s | — | **49.9 GiB** | **48.4 GiB** | **1.0×** |

**结论**
1. **DCP load-time resharding 在 FS 侧无读放大**：同拓扑、减半、不对齐的 512→384，CloudWatch DataReadBytes 都等于 checkpoint 大小。DCP 按新旧分片重叠区间做偏移读。
2. 边界不对齐时，客户端统计多出 1.56 倍，来自同节点多个 rank 读同一旧文件相邻区间时命中本机页缓存，未发到 OSS；代价是恢复时间 +20%（40 s vs 32–34 s）。
3. **真正的读放大来自 DP 副本重复读**：Megatron 默认 `--ckpt-fully-parallel-load` 为 False，DP 组内每个 rank 都读同一份权重 → FS 读放大 = DP 副本数；开启后回到 1.0×。⚠️ **本项为 DCP + gloo 模拟，未真跑 Megatron-Core**（其 dist_checkpointing 依赖 CUDA/NCCL）。
4. 本规模下开启 fully-parallel 墙钟反而更慢（12.4 s vs 7.5 s），因为 gloo 走 TCP 广播的成本高于直接读 Lustre（且不开的那组有大量同节点缓存命中）。推测（未实测）：真实 GPU 集群用 NCCL 走 EFA / NVLink 广播会明显获益；当 DP 副本数 × 模型分片 > FS 吞吐 × 可接受恢复时间时，不开 fully-parallel 会直接打满 FS。

## 7. 存储规划要点（基于实测）

| 设计项 | 建议 |
|---|---|
| 吞吐档位 / 容量 | checkpoint 写入可达 FS 基线的 ~94%：**所需容量（TiB）≈ checkpoint 大小 ÷ 允许写入时间 ÷ 档位**；再与"保留 N 份 checkpoint + 数据集"所需容量取大 |
| 同步 vs 异步 | 推动使用异步保存：训练阻塞降到秒级以下，存储只需在保存间隔内写完 |
| 分片 | 保持每 rank 一个分片（DCP 默认）；默认 PFL 即可，避免"每节点一个大文件" |
| EFA | 总吞吐 > 10 GBps 建议开（官方建议）；OSS 数少时 ENA 单机仅约 9.5 Gbps × OSS 数，EFA 尤为重要；EFA 只能在创建时开；多 OSS FS + 大机型 EFA 客户端需设 `osc.*.max_rpcs_in_flight=8`（见 fsx-lustre-efa-client-disconnect） |
| 训练环境 | 放本地盘 / 容器镜像，不要把 venv/conda 直接放 Lustre |
| 元数据 IOPS | 创建时必须带 MetadataConfiguration；扩容后重新复制热点目录 |
| 目录 | 每目录 < 100K 文件；客户端开 `statahead_xattr=1`（开机脚本持久化） |
| 恢复 | 开启 fully-parallel-load（或等效机制），避免 DP 副本数倍的读放大 |

## 8. 复现命令

脚本见 [`scripts/`](./scripts/)：`ckpt_bench.py`（DCP 写/读/重分片/DP 重复读）、`run_dist.sh`、`md_prep.py` / `md_worker.py` / `md_storm.sh` / `md_stats.py`（元数据风暴）、`bigdir.sh`、`fio1.sh`。

```bash
# 客户端（AL2023），按 FSx 官方脚本安装 Lustre 客户端 + EFA 模块并配置 LNet
curl -O https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/install-fsx-lustre-client.zip && unzip install-fsx-lustre-client.zip
cd install-fsx-lustre-client && sudo ./bin/install-fsx-lustre-client.sh --install-lustre --install-efa
curl -O https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/configure-efa-fsx-lustre-client.zip && unzip configure-efa-fsx-lustre-client.zip
cd configure-efa-fsx-lustre-client && sudo ./setup.sh
sudo mount -t lustre -o relatime,flock <FS_DNS>@tcp:/<MOUNT_NAME> /fsx

# FS：PERSISTENT_2，1000 MB/s/TiB，EFA，元数据 USER_PROVISIONED
aws fsx create-file-system --file-system-type LUSTRE --file-system-type-version 2.15 --storage-type SSD --storage-capacity 24000 \
  --subnet-ids <SUBNET> --security-group-ids <EFA_SELF_REF_SG> \
  --lustre-configuration '{"DeploymentType":"PERSISTENT_2","PerUnitStorageThroughput":1000,"EfaEnabled":true,"MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":12000}}'

# Checkpoint 写入 / 恢复（每节点执行；16 节点 × 32 rank）
OMP_NUM_THREADS=1 torchrun --nnodes=16 --nproc-per-node=32 --node-rank=$NR --master-addr=<NODE0_IP> --master-port=29511 \
  scripts/ckpt_bench.py --mode <save|async|torchsave|load|load_reshard|dsave|dload|dp_readall|dp_bcast> \
  --dir /fsx/ckpt/<pfl|full|c1>/<name> --gib-per-rank 1.5 [--stager shm] [--saved-world 512]
lfs setstripe -c -1 /fsx/ckpt/full     # 全条带目录；/fsx/ckpt/pfl 继承 FS 默认 PFL

# 单客户端吞吐
fio --name=s --directory=<dir> --rw=<write|read> --bs=16M --size=8G --numjobs=<16|32|64> --ioengine=libaio --iodepth=8 --direct=1 --group_reporting

# 元数据风暴（每节点 100 进程，统一 GO 时刻）
GO=<epoch> scripts/md_storm.sh <VENV> <DATADIR> 100 <OUT>
python3 scripts/md_stats.py <OUT> <GO>

# 扩元数据 IOPS（在线）
aws fsx update-file-system --file-system-id <FS_ID> --lustre-configuration '{"MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":24000}}'
```

## 9. 限制

- GPUDirect Storage 未测（无 p5 容量）。ENA 单客户端约 74 Gbps 饱和的原因未定位。
- 客户端为 Graviton4 CPU 机型（gloo），异步保存的 pinned memory 路径未测；第 6 节 Megatron 相关两行为模拟。
- CloudWatch 为 1 分钟粒度，单次写入约 36 s，利用率类指标被平均摊低。
- 每项只测 1–2 次。

## 参考文档

- FSx for Lustre performance（单客户端吞吐、存储布局、PFL）：https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance.html
- FSx for Lustre performance tips（statahead_xattr、目录 < 100K）：https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance-tips.html
- 每 OSS 容量（IP addresses for file systems）：https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-fsx-lustre.html#ip-addesses-for-fs
- EFA-enabled 文件系统：https://docs.aws.amazon.com/fsx/latest/LustreGuide/efa-file-systems.html
- PyTorch Distributed Checkpoint：https://docs.pytorch.org/docs/stable/distributed.checkpoint.html
