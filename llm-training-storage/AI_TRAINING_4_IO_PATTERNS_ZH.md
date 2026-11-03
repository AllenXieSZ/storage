# AI 训练 4 大 IO 模式：不是所有训练都是顺序读

> **核心观点**：LLM 预训练是大块顺序 IO，但推荐系统、GNN、多模态、强化学习等训练场景会产生大量**随机小 IO**，对存储的要求完全不同。存储架构师必须理解负载特征才能选对方案。

---

## 全局对比

```
IO 模式谱系（从顺序到随机）:

大块顺序                                                 细粒度随机
◄─────────────────────────────────────────────────────────►
│                                                           │
│  LLM 预训练     多模态训练    推荐系统训练     GNN 训练    │
│  (文本token流)  (图片/视频)   (Embedding查表)  (图采样)    │
│                                                           │
│  顺序读大文件    随机读中文件   随机查表小IO     极度随机    │
│  带宽敏感        带宽+IOPS     IOPS 极度敏感    IOPS 极度  │
│  Lustre/S3      Lustre/EBS    NVMe SSD/内存    NVMe SSD   │
```

---

## 模式一：LLM 预训练 — 大块顺序读

### 训练数据读取方式

```
Tokenized 数据（30-60 TB 二进制文件）
    ↓
mmap 或 DataLoader 顺序读取
    ↓
每步每 GPU 读取 ~15 个序列 × 4096 tokens × 4 bytes ≈ 250 KB
    ↓
64 GPU 聚合: ~48 MB/s（极小，不是瓶颈）
```

### IO 特征

| 维度 | 特征 |
|---|---|
| **读取模式** | 纯顺序大块读（预 tokenize + 预 shuffle 后按顺序扫） |
| **IO 大小** | MB~GB 级连续块 |
| **随机性** | 极低（数据预打乱后按序读，或 mmap + OS 预取） |
| **瓶颈** | 通常**不是存储**，而是 GPU 计算和 All-Reduce 通信 |
| **IOPS 需求** | 低（几百~几千 IOPS） |
| **带宽需求** | 中（几十 MB/s ~ 几 GB/s，多 worker 并行预取即可覆盖） |
| **真正的存储瓶颈** | **Checkpoint 写入**（几百 GB 并发写）而非数据读取 |

### 推荐存储

- FSx Lustre（吞吐优化）、S3 + Streaming、EBS io2（单机微调时）
- 数据加载不是瓶颈 → 存储选型主要看 checkpoint 写入性能

---

## 模式二：推荐系统训练 — Embedding 查表随机小 IO

### 为什么是随机 IO

推荐系统（DLRM / Wide&Deep / DeepFM 等）的核心组件是**超大 Embedding 表**：

```
用户 ID     → 查 User Embedding 表（几亿行 × 128 维）
商品 ID     → 查 Item Embedding 表（几千万行 × 128 维）
品类/标签   → 查 Feature Embedding 表（几百万行 × 64 维）
城市/设备   → 查 Context Embedding 表
```

**一次前向传播的 IO 流程**：

```
一条训练样本: {user_id=382947, item_id=58291, category=[3,17,42], city=12, ...}
    ↓
查 User Embedding: 表第 382947 行 → 随机位置读取 128×4=512 bytes
查 Item Embedding: 表第 58291 行 → 另一个随机位置
查 Category Embedding: 3 个 ID → 3 次随机查
查 City Embedding: 1 次随机查
    ↓
总计: 每个样本 5-20 次随机 Embedding lookup
    ↓
一个 batch（如 65536 个样本）: 30 万~ 100 万次随机查表
    ↓
每秒几十个 batch → 每秒数千万次随机查表
```

### 关键数据

| 维度 | 特征 |
|---|---|
| **Embedding 表大小** | 几 GB ~ 几百 GB（Meta 的推荐模型 Embedding 表可达 TB 级） |
| **单次 lookup IO** | 64-512 bytes（极小） |
| **随机性** | **极高**——用户/商品 ID 分布广，几乎完全随机 |
| **每步 IO 次数** | 百万级随机读 |
| **瓶颈** | **IOPS 和随机读延迟**，而非吞吐 |
| **CPU/GPU 利用率** | 如果 Embedding 放慢存储上，GPU 大部分时间在等数据 |

### 业界解法

| 方案 | 原理 | 适用场景 |
|---|---|---|
| **全放 GPU 显存** | HBM 带宽 3TB/s，随机访问极快 | 表小（<80GB），单卡或 table-wise 分片 |
| **分布式 Embedding（TorchRec / HugeCTR）** | 表按行分片到多 GPU/多机，通过 All-to-All 通信交换查表结果 | 表大（>100GB），需多卡 |
| **CPU 内存 + UVA** | Embedding 表放 CPU 内存，GPU 通过 PCIe 按需拉取 | 表非常大（>1TB），PCIe 是瓶颈 |
| **NVMe SSD + 缓存** | 冷 Embedding 放 SSD，热门 ID 缓存在 GPU/CPU | 超大表 + 长尾分布（热门 ID 占多数访问） |
| **参数服务器（PS）** | 专门的 Embedding 服务器集群，训练节点通过网络查表 | 超大规模分布式（字节/Meta） |

### 🗄️ 存储视角

- **这个场景的存储需求跟 LLM 预训练完全不同**：不需要高吞吐，需要的是**超低延迟 + 高 IOPS 的随机读**
- Lustre 的优势（高顺序吞吐）在这里发挥不出来——Lustre 的随机小 IO 延迟较高
- **最佳方案**：Embedding 表尽量放 GPU 显存或 CPU 内存；放不下的部分用**本地 NVMe SSD**（如 p5d.48xlarge 的 8×3.84TB NVMe，随机读 IOPS 可达百万级）
- Meta 的论文（DLRM）提到他们的 Embedding 表分布在数百台服务器的内存中，通过自研参数服务器访问

**一句话**：LLM 训练看**带宽**（MB/s），推荐系统训练看 **IOPS**（次/秒）。

---

## 模式三：GNN 训练 — 图采样导致极度随机 IO

### 为什么是随机 IO

GNN（Graph Neural Network）训练的核心操作是**邻居采样（Neighbor Sampling）**：

```
图结构: 10 亿节点、100 亿条边（如社交网络/知识图谱/金融交易图）
节点特征: 每个节点有一个特征向量（如 256 维 float = 1 KB）
    ↓
训练一个 batch:
  1. 随机选 1024 个目标节点（seed nodes）
  2. 对每个节点采样 K 个邻居（如 K=15）→ 15360 个 1-hop 邻居
  3. 对每个 1-hop 邻居再采样 K 个 → 230400 个 2-hop 邻居
  4. 加载所有采样节点的特征向量
    ↓
总计: 约 25 万个节点的特征向量需要加载
     = 25 万次随机读取（节点 ID 完全随机分布在整张图上）
     = 25 万 × 1 KB = 250 MB / batch
```

### 为什么比推荐系统更极端

| 对比维度 | 推荐系统 Embedding | GNN 图特征 |
|---|---|---|
| 数据分布 | 有热度偏斜（热门商品缓存友好） | **更均匀**（图采样探索广泛邻居，缓存命中率低） |
| 每步访问量 | 万~百万次查表 | 几十万次特征加载（层数越多越爆炸） |
| 缓存效果 | 好（幂律分布） | **差**（每个 batch 的采样子图几乎不重复） |
| 数据总量 | GB~TB（Embedding 可压缩） | **可达 TB 级**（10 亿节点 × 1KB = 1TB 纯特征） |

### 关键论文数据

- **BGL (NSDI'23)**：GNN 训练中 GPU 利用率仅 20-30%，其余时间在等数据加载（图采样 + 特征拉取）
- **GNNDrive (arxiv 2601.01473)**：storage-based GNN 训练中，NVMe SSD 随机 IO 带宽只能发挥峰值的 10-30%（因为 IO 请求太小太随机）
- **FreshGNN (OpenReview)**：节点特征加载是最大性能瓶颈，提出用"历史 Embedding 缓存"减少重复加载

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **IO 模式** | **极度随机小 IO**——每个 batch 要随机读取 25 万个不连续的特征向量 |
| **IO 大小** | 256 bytes ~ 4 KB（单个节点特征） |
| **IOPS 需求** | 百万级（远超普通 SSD） |
| **带宽需求** | 也高（250 MB/batch × 每秒几个 batch = 几 GB/s） |
| **缓存效果** | 差——图采样的局部性很弱，page cache 命中率低 |
| **理想存储** | 最好全放内存（DRAM）；放不下用**多块高端 NVMe SSD RAID-0**（聚合百万 IOPS） |
| **网络存储** | 几乎不可用——FSx Lustre/EFS/NFS 的随机小 IO 延迟（~0.5-2ms）完全不能接受 |

**GNN 训练是对存储随机 IOPS 要求最极端的 AI 场景**——比推荐系统更极端，因为图采样的访问模式几乎没有热度偏斜。

---

## 模式四：多模态训练 — 中等随机 + 大 IO

### 训练数据特征

多模态模型（GPT-4V / Gemini / LLaVA 等）训练时需要同时加载文本、图片、视频：

```
一条训练样本:
├── 文本 token: ~2 KB（已 tokenize）
├── 图片: 224×224×3 = 150 KB（JPEG 压缩后 ~30-50 KB）
│   或 高分辨率: 1024×1024 = ~300 KB JPEG
├── 视频: 几秒钟的 clip = 几 MB ~ 几十 MB
└── 音频: 几秒 = 几十 KB ~ 几 MB
```

### IO 模式

```
训练数据集: 数十亿张图片/视频（存在 S3/对象存储，几 PB）
    ↓
DataLoader 每步:
  - batch_size=2048
  - 每个样本需要读一张图（~50 KB）+ 文本
  - 2048 × 50 KB = 100 MB / step
  - 每秒 2-3 步 = 200-300 MB/s
    ↓
视频训练更重:
  - 每个样本 = 一个视频 clip (~5 MB)
  - 2048 × 5 MB = 10 GB / step
  - 每秒 1 步 = 10 GB/s ← 存储带宽成瓶颈！
```

### 为什么有随机性

- 图片/视频文件分散存储在不同路径/不同 S3 prefix 下
- 每个 epoch 需要 shuffle → 随机顺序读取不同文件
- 不像 LLM 预训练的 tokenized 数据那样是一个连续大文件

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **IO 模式** | 中等随机——每步读几千个不同文件，但每个文件 KB~MB 级（不是 bytes 级） |
| **IO 大小** | 30 KB ~ 5 MB（图片/视频） |
| **IOPS 需求** | 中高（几千~几万 IOPS） |
| **带宽需求** | **高**——视频训练可达 10+ GB/s |
| **缓存效果** | 中等——有些图片可能跨 epoch 复用 |
| **推荐存储** | FSx Lustre（条带化分散 IO + 高吞吐）、S3 + 预取管线 |
| **常见优化** | WebDataset/TFRecord 打包（把多张图合并为大的 tar/tfrecord 文件 → 变回顺序读）|

**关键优化思路：把随机小文件打包成大文件**

```
原始: 10 亿个 JPEG 文件（每个 50KB）→ 10 亿次随机读 → 元数据地狱
打包: WebDataset .tar.gz shards（每个 1GB，含 ~20000 张图）→ 顺序读大文件
```

打包后多模态训练的 IO 模式接近 LLM 预训练（顺序读大文件）。**这个优化对存储选型影响巨大**——打包前需要高 IOPS 存储，打包后只需要高吞吐。

---

## 总结对比表

| 训练场景 | IO 模式 | IO 大小 | 关键指标 | 存储瓶颈 | 推荐存储 |
|---|---|---|---|---|---|
| **LLM 预训练** | 顺序大块读 | MB~GB | 吞吐 (GB/s) | Checkpoint 写入 | Lustre / S3 |
| **推荐系统** | 随机小 IO（Embedding 查表） | 64B~512B | **IOPS** (百万级) | Embedding 加载 | GPU 显存 / NVMe SSD |
| **GNN** | 极度随机小 IO（图采样） | 256B~4KB | **IOPS** (百万级) + 带宽 | 节点特征加载 | DRAM / NVMe RAID-0 |
| **多模态** | 中等随机中文件 | 30KB~5MB | 带宽 + IOPS | 图片/视频加载 | Lustre + 预打包 |

### AWS 存储选型映射

| 训练场景 | 首选 | 备选 | 不适合 |
|---|---|---|---|
| **LLM 预训练** | FSx Lustre PERSISTENT_2 | S3 + Mountpoint | EBS（单机吞吐上限低） |
| **推荐系统 Embedding** | 本地 NVMe (i3en/p5d) | EBS io2 Block Express | Lustre/EFS（随机延迟高） |
| **GNN 图采样** | 本地 NVMe (i4i/i3en) | 内存（r7i 大内存型） | 任何网络存储 |
| **多模态（打包后）** | FSx Lustre | S3 + DataLoader prefetch | — |
| **多模态（未打包）** | FSx Lustre + MDT 加速 | EBS io2 | S3（小文件 IOPS 低） |

### IO 大小 vs 随机性象限图

```
IO 大小 (大)
     ^
     │  LLM Checkpoint    多模态(视频)
     │  (MB-GB 顺序写)    (MB 中等随机)
     │
     │  LLM 数据读取       多模态(图片)
     │  (MB 顺序读)        (KB 中等随机)
     │
     │                     推荐系统(Embedding)  GNN(图采样)
     │                     (Bytes 高度随机)     (KB 极度随机)
     └──────────────────────────────────────────────────► 随机性 (高)
 (低)
```

---

## 参考资料

- [Meta DLRM](https://arxiv.org/abs/1906.00091) — 推荐系统中 Embedding 表的 IO 特征
- [TorchRec](https://docs.pytorch.org/tutorials/intermediate/torchrec_intro_tutorial.html) — PyTorch 推荐系统分布式 Embedding
- [NVIDIA cuEmbed](https://developer.nvidia.com/blog/accelerating-embedding-lookups-with-cuembed/) — GPU 加速 Embedding 查表
- [BGL (NSDI'23)](https://www.usenix.org/conference/nsdi23/presentation/liu-tianfeng) — GNN 训练 IO 优化
- [GNNDrive (arxiv 2601.01473)](https://arxiv.org/abs/2601.01473) — 存储级 GNN 训练加速
- [FreshGNN](https://openreview.net/forum?id=iyJjEkU0Ve) — 减少 GNN 特征加载的内存访问
- [WebDataset](https://github.com/webdataset/webdataset) — 多模态数据打包方案
- [AWS FSx for Lustre](https://docs.aws.amazon.com/fsx/latest/LustreGuide/) — 高吞吐训练存储
