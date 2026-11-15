# 05 - Pre-training（预训练）

## 一、预训练 vs 微调 vs 推理

| 阶段 | 目标 | 数据量 | 计算量 | 成本 | 频率 |
|------|------|--------|--------|------|------|
| **预训练** | 学习通用语言/世界知识 | 万亿 token（TB 级） | 10²⁴-10²⁵ FLOPs | 千万~亿美元 | 一次（或几次增量） |
| **微调（SFT/RLHF）** | 适配特定任务/对齐人类偏好 | 千~万条样本（MB-GB 级） | 10¹⁸-10²¹ FLOPs | 千~万美元 | 偶尔 |
| **推理** | 实际使用模型 | 单条输入 | 10¹²-10¹⁵ FLOPs/次 | 按 token 计费 | 持续 |

**关键区别**：
- 预训练是"从零学起"，微调是"基于已有知识定制"
- 预训练的成本是微调的 1000 倍以上
- 只有 Google/Meta/OpenAI/Anthropic 这类有大量 GPU 的公司才做预训练
- 大多数企业用户只需要微调和推理

---

## 二、训练数据规模

### 2.1 主流训练数据集

| 数据集 | 大小 | Token 数 | 用于 |
|--------|------|---------|------|
| Common Crawl（一个月快照） | 200-300 TB（原始 HTML） | - | 清洗后用于各种模型 |
| The Pile (EleutherAI) | 825 GB（清洗后） | 800B tokens | GPT-NeoX 等开源模型 |
| RedPajama v1 | 5 TB | 1.2T tokens | RedPajama 模型 |
| RedPajama v2 | 30 TB | 30T tokens（去重前） | 研究用 |
| RefinedWeb (Falcon) | ~600 GB | 600B tokens | Falcon 系列 |
| Dolma (AI2) | ~3 TB | 3T tokens | OLMo 系列 |
| LLaMA-3.1 训练数据 | 未公开 | **15T tokens** | LLaMA-3.1 |

### 2.2 数据来源构成（以 LLaMA-2 为参考）

| 来源 | 占比 | 说明 |
|------|------|------|
| Web 文本 (Common Crawl) | ~67% | 清洗去重后的网页文本 |
| 代码 (GitHub) | ~4.5% | 开源代码仓库 |
| 书籍 | ~4.5% | Books3 等 |
| Wikipedia | ~4.5% | 多语言 Wikipedia |
| 学术论文 (ArXiv) | ~2.5% | 学术 PDF 转文本 |
| StackExchange | ~2% | 问答数据 |
| 其他 | ~15% | 杂项 |

---

## 三、训练成本

### 3.1 成本估算公式

```
训练 FLOPs ≈ 6 × N × D
其中：N = 模型参数量，D = 训练 token 数

GPU 小时 ≈ 训练 FLOPs / (GPU 峰值 FLOPS × MFU)
其中：MFU = Model FLOPs Utilization（通常 30%-55%）

成本 ≈ GPU 小时 × 单价
```

### 3.2 实际案例

| 模型 | 参数量 | 训练 token | GPU | GPU 数量 | 训练时间 | 估算成本 |
|------|--------|-----------|-----|---------|---------|---------|
| LLaMA-2 70B | 70B | 2T | A100 80GB | 2048 | ~25 天 | ~$2M |
| LLaMA-3.1 405B | 405B | 15T | H100 80GB | 16384 | ~54 天 | ~$30M+ |
| GPT-4（传言） | ~1.8T MoE | ~13T | A100 | ~25000 | ~100 天 | ~$100M |
| Gemini Ultra | 未公开 | 未公开 | TPU v4/v5 | ~几万 | 未公开 | ~$50-100M（估） |

**H100 的算力**：
- FP16 Tensor Core：989.5 TFLOPS（SXM）
- 单卡价格：~$25,000-30,000（购买）/ ~$2-3/hr（云按需）
- 一张 H100 满载一年电费（700W × 8760h × $0.1/kWh）≈ $613

### 3.3 总体成本构成

| 成本项 | 占比 | 说明 |
|--------|------|------|
| GPU/TPU 计算 | **70-80%** | 最大头 |
| 电力 | 10-15% | 数据中心电费 |
| 人力（研究员+工程师） | 5-10% | 高薪人才 |
| 数据获取/清洗 | 3-5% | 网络爬虫、标注 |
| 存储 | 2-3% | 训练数据 + checkpoint |
| 网络 | 1-2% | GPU 间通信（InfiniBand/RoCE） |

---

## 四、数据清洗 Pipeline

原始网络数据**非常脏**，必须经过多步清洗：

```
原始 Common Crawl (~200-300 TB)
    │
    ▼ 1. URL 过滤
    │   └─ 去除色情/暴力/垃圾网站 URL（黑名单）
    │
    ▼ 2. 语言识别
    │   └─ FastText/CLD3 识别语言，按需保留（如只留英文+中文）
    │
    ▼ 3. 文本提取
    │   └─ HTML → 纯文本（trafilatura/readability）
    │   └─ 去除导航栏、广告、页脚等 boilerplate
    │
    ▼ 4. 质量过滤
    │   └─ 文本长度过滤（<50 字的丢弃）
    │   └─ 重复行比例过滤（>30% 重复行→垃圾页面）
    │   └─ 困惑度过滤（用小语言模型计算 perplexity，异常高的丢弃）
    │   └─ 特殊字符比例过滤（>20% 非字母字符→代码/乱码）
    │
    ▼ 5. 去重（Deduplication）
    │   └─ 精确去重：SHA256 哈希去除完全相同的文档
    │   └─ 模糊去重：MinHash + LSH 去除高度相似（>80%）的文档
    │   └─ 子串去重：Suffix Array 去除大段重复内容
    │   └─ 去重通常去掉 50-70% 的数据
    │
    ▼ 6. 去毒（Toxicity Filtering）
    │   └─ 分类器识别仇恨言论/暴力/色情内容
    │   └─ PII（个人身份信息）脱敏
    │
    ▼ 7. 混合采样
    │   └─ 按来源（web/book/code/wiki）设定采样比例
    │   └─ 高质量来源（Wiki/书籍）upsampling
    │
    ▼ 清洗后数据 (~5-30 TB, ~1-15T tokens)
```

**数据清洗的存储含义**：
- 原始数据 200-300 TB → 清洗后 5-30 TB，存储减 10-60x
- 中间产物（每步的输出）也需要几十 TB 临时存储
- 去重阶段的 MinHash 索引需要大量内存（几百 GB）
- Pipeline 运行需要高吞吐顺序读写

---

## 五、Tokenizer 训练

Tokenizer 在预训练**之前**训练，决定了模型"怎么看文本"。

### 5.1 训练流程

```
1. 取训练数据的子集（10-100 GB 文本）
2. 选择 tokenizer 算法（BPE / WordPiece / SentencePiece）
3. 设定目标词汇表大小（32K / 50K / 128K / 256K）
4. 在子集上运行分词训练
5. 输出：词汇表文件 (vocab) + 合并规则文件 (merges)
6. 验证：检查 tokenization 效果、覆盖率、OOV 率
```

### 5.2 词汇表大小选型

| 词汇表大小 | 优点 | 缺点 | 代表模型 |
|------------|------|------|---------|
| 32K | Embedding 矩阵小，训练快 | 长词/罕见词被切碎多 | GPT-2 (50K)，LLaMA-1 (32K) |
| 64K-128K | 平衡 | - | LLaMA-2 (32K)，LLaMA-3 (**128K**) |
| 256K | 切割少，每 token 代表更多文本 | Embedding 矩阵大 | Gemini (**256K**) |

**LLaMA-3 把词汇表从 32K 扩大到 128K 的原因**：
- 每个 token 代表更多字符 → 同样文本用更少 token → 生成更快
- 多语言覆盖更好（中日韩字符不用频繁切割）
- 代价是 Embedding 矩阵从 32K×d 变成 128K×d（存储增加 4x）

---

## 六、分布式训练策略

70B~1T 级别的模型，单卡（80GB HBM）放不下，必须用分布式训练。

### 6.1 Data Parallelism（数据并行）

```
                    训练数据
                 ┌─────┼─────┐
                 ▼     ▼     ▼
              Batch1 Batch2 Batch3
                 │     │     │
              GPU 0  GPU 1  GPU 2    每张 GPU 上有完整模型副本
                 │     │     │
              grad0  grad1  grad2
                 └─────┼─────┘
                  All-Reduce          同步所有 GPU 的梯度
                       │
                    更新权重
```

- 每张 GPU 持有**完整模型副本**
- 不同 GPU 处理不同数据 batch
- 梯度 All-Reduce 同步
- **限制**：单卡必须装得下完整模型 → 不适合大模型

### 6.2 Tensor Parallelism（张量并行 / 模型并行）

把**单个层的权重矩阵**切分到多张 GPU 上：

```
权重矩阵 W (8192 × 8192)
├── GPU 0: W 的前 4096 列
├── GPU 1: W 的后 4096 列
每次前向/后向都需要 GPU 间通信（All-Reduce）
```

- 单层内切分 → GPU 间通信频繁 → 要求 GPU 在同一节点（NVLink 高带宽）
- 通常 **节点内** 用 Tensor Parallel（8 路 NVLink）

### 6.3 Pipeline Parallelism（流水线并行）

把模型的**不同层**分配到不同 GPU 上：

```
GPU 0: Layer 0-19
GPU 1: Layer 20-39
GPU 2: Layer 40-59
GPU 3: Layer 60-79

数据像流水线一样流过各 GPU：
Micro-batch 1: [GPU0] → [GPU1] → [GPU2] → [GPU3]
Micro-batch 2:         [GPU0] → [GPU1] → [GPU2] → [GPU3]
Micro-batch 3:                  [GPU0] → [GPU1] → [GPU2] → ...
```

- 不同层在不同 GPU → GPU 间通信少（只在层的边界传 activation）
- **Pipeline Bubble**：第一个 micro-batch 到最后一张 GPU 前，中间 GPU 空闲
- 通常 **节点间** 用 Pipeline Parallel（网络延迟容忍度更高）

### 6.4 3D 并行（实际大模型训练的标配）

```
实际训练 = Data Parallel × Tensor Parallel × Pipeline Parallel

例：LLaMA-3.1 405B 在 16384 张 H100 上训练：
- Tensor Parallel = 8（一个节点内 8 张 GPU 切一层）
- Pipeline Parallel = 16（16 个节点串成流水线放不同层）
- Data Parallel = 128（128 组流水线处理不同数据）

16384 = 8 × 16 × 128
```

### 6.5 FSDP / ZeRO（显存优化）

传统 Data Parallel：每张 GPU 存完整模型副本 → 浪费显存。

**ZeRO（Zero Redundancy Optimizer）** by DeepSpeed，三个阶段逐步优化：

| 阶段 | 切分内容 | 显存节省 | 通信开销 |
|------|---------|---------|---------|
| ZeRO Stage 1 | 优化器状态 | ~4x | 与 DP 相同 |
| ZeRO Stage 2 | + 梯度 | ~8x | 略增 |
| ZeRO Stage 3 | + 模型权重 | **~N×**（N=GPU 数） | 增加（需要 All-Gather 权重） |

**FSDP（Fully Sharded Data Parallel）**：PyTorch 原生的 ZeRO Stage 3 实现。

```
ZeRO Stage 3 / FSDP：

GPU 0: 模型参数的 1/N + 优化器的 1/N + 梯度的 1/N
GPU 1: 模型参数的 2/N + 优化器的 2/N + 梯度的 2/N
...
GPU N: 模型参数的 N/N + 优化器的 N/N + 梯度的 N/N

前向传播时：All-Gather 收集完整参数 → 计算 → 释放非本地分片
反向传播时：All-Gather + Reduce-Scatter
```

---

## 七、存储视角加餐 ⭐⭐（最贴合存储架构师）

### 7.1 训练数据的 IO 模式

| 特征 | 说明 |
|------|------|
| 读写模式 | **几乎全是顺序读**，写极少 |
| 并发 | 几千张 GPU 的 data loader 并行读同一数据集 |
| 文件大小 | 预处理后通常是大文件（tokenized 的 binary 文件，每个几 GB~几十 GB） |
| 吞吐需求 | **几十 GB/s 聚合读吞吐**（几千 GPU 同时读） |
| 延迟需求 | 不敏感（sequential read，prefetch 能掩盖延迟） |
| 数据访问频率 | 每个 epoch 全量扫描一遍，多 epoch 重复读 |

### 7.2 Checkpoint IO 模式

| 特征 | 说明 |
|------|------|
| 频率 | 每隔 N 步（如 1000 步）保存一次 |
| 大小 | 单个 checkpoint：**几十 GB~几百 GB** |
| 模式 | **所有 GPU 同时突发写**，要求短时间内完成 |
| 吞吐需求 | **10-100 GB/s 突发写**（越快越好，减少训练中断） |
| 恢复 | 训练中断后，从最新 checkpoint 全量读恢复 |
| 保留策略 | 通常保留最近 3-5 个 checkpoint + 关键里程碑 |

### 7.3 存储选型对比

| 存储方案 | 训练数据读 | Checkpoint 写 | 成本 | 适用 |
|---------|-----------|--------------|------|------|
| **FSx Lustre** | ★★★★★（并行高吞吐） | ★★★★★（并行写强） | $$$ | AWS AI 训练首选 |
| **S3 Express One Zone** | ★★★★（低延迟对象存储） | ★★★★（单次写快） | $$$$ | 新选项，Checkpoint 直写 |
| **S3 + Mountpoint-S3** | ★★★（顺序读够用） | ★★（写性能受限） | $ | 训练数据读可以，Checkpoint 写不推荐 |
| **EFS** | ★★★（General Purpose，元数据受限） | ★★★ | $$ | 小规模可以，大规模吞吐不够 |
| **GCS** | ★★★★（GCS FUSE） | ★★★★（GCS FUSE） | $$ | GCP 首选 |
| **GCS FUSE** | ★★★★（POSIX 接口 + GCS 后端） | ★★★★ | $$ | GCP 训练标配 |
| **Filestore (GCP NFS)** | ★★★★ | ★★★★ | $$$ | GCP 高性能 NFS |
| **本地 NVMe (实例存储)** | ★★★★★（最快） | ★★★★★ | - | 但不持久化，需要异步上传 |

### 7.4 FSx Lustre 在 AI 训练中的角色

```
┌──────────────────────────────────────────────────┐
│                  S3 Bucket                        │
│   训练数据（TB 级）+ Checkpoint 归档              │
└──────────────┬────────────────┬───────────────────┘
               │                │
         Auto Import       Auto Export (DRA)
               │                │
┌──────────────▼────────────────▼───────────────────┐
│              FSx Lustre 文件系统                    │
│   PERSISTENT_2, 1000 MB/s/TiB                     │
│   训练数据缓存 + Checkpoint 写入                   │
└──────────────┬────────────────────────────────────┘
               │ POSIX mount（高性能，多客户端并行）
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 GPU Node   GPU Node   GPU Node
 (8×H100)   (8×H100)   (8×H100)
```

**FSx Lustre + S3 DRA（Data Repository Association）**：
- **Auto Import**：S3 上的训练数据**自动同步**到 Lustre，GPU 节点直接 POSIX 读
- **Auto Export**：Checkpoint 写到 Lustre 后**自动导出**到 S3 归档
- 优势：GPU 节点看到的是高性能 POSIX 文件系统，数据的持久化在 S3

### 7.5 Checkpoint 优化技术

| 技术 | 说明 |
|------|------|
| Asynchronous Checkpoint | 后台异步写 checkpoint，不阻塞训练 |
| Incremental Checkpoint | 只保存变化的部分（delta），减少写量 |
| Sharded Checkpoint | FSDP/ZeRO 下每张 GPU 写自己的 shard，并行写提升吞吐 |
| Checkpoint to S3 Express | 直接写 S3 Express One Zone，跳过中间文件系统 |
| Nebula (NVIDIA) | NVIDIA 的异步多级 checkpoint 库，NVMe→共享文件系统→S3 三级 |

---

## 八、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| 托管训练平台 | **Vertex AI Training** | **SageMaker Training** |
| AI 加速器 | **TPU v5p/v5e**, A3 (H100), A2 (A100) | p5 (H100), p4d (A100), **Trn1 (Trainium)**, Trn2 |
| 推理加速器 | TPU v5e, L4, Vertex AI Prediction | Inf2 (**Inferentia 2**), SageMaker Inference |
| 高吞吐训练存储 | GCS + **GCS FUSE**, **Filestore** (NFS), Lustre on GKE | **FSx Lustre** (DRA), S3 Express One Zone |
| 对象存储 | **GCS** | **S3**, S3 Express One Zone |
| 训练数据管道 | Vertex AI Datasets, Dataflow | SageMaker Data Wrangler, Glue |
| 分布式训练框架 | Vertex AI + JAX/PyTorch FSDP + TPU Pods | SageMaker Distributed (DDP/SMMP) + DeepSpeed |
| GPU 集群网络 | **GPUDirect-TCPXO** (A3-mega), ICI (TPU) | **EFA** (Elastic Fabric Adapter) + GPUDirect RDMA |

**GCP TPU 特点**：
- TPU v5p：8960 chips per pod，BF16 459 TFLOPS/chip
- ICI（Inter-Chip Interconnect）：TPU 间专用高带宽互联，不走以太网
- JAX 是 Google 推荐的 TPU 训练框架（XLA 编译，张量自动分片）

**AWS Trainium 特点**：
- 自研 AI 芯片，比 H100 便宜 ~40%
- 需要 Neuron SDK（不是标准 CUDA），PyTorch 兼容层（torch-neuronx）
- Trn1.32xlarge：16 个 Trainium 芯片，512 GB HBM

---

## 九、面试话术

### Q: 解释 LLM 预训练的存储需求，你会怎么设计存储架构？

> **答题模板**：
> 
> LLM 预训练有两大存储需求：**训练数据读**和 **checkpoint 写**，IO 模式完全不同。
> 
> 训练数据是 TB 级（LLaMA-3.1 用了 15T tokens，清洗后数据约 30-50 TB），IO 模式是几千张 GPU 并行顺序读，聚合吞吐需要几十 GB/s。这是典型的高吞吐大块顺序读场景。
> 
> Checkpoint 是每隔 N 步全量 dump 模型权重+优化器状态，70B 模型单个 checkpoint 约 560 GB。IO 模式是突发写，要求在最短时间内完成（减少 GPU 空闲），写吞吐要求 10-100 GB/s。
> 
> **AWS 上我会这样设计**：
> - 训练数据放 S3（持久化、低成本），通过 **FSx Lustre + DRA Auto Import** 缓存到 Lustre 文件系统
> - FSx Lustre 选 PERSISTENT_2 类型，1000 MB/s/TiB 吞吐，按训练数据量定 Lustre 容量
> - GPU 节点通过 POSIX mount 读 Lustre，高吞吐并行读
> - Checkpoint 也写到 Lustre，DRA Auto Export 自动归档到 S3
> - 或者对于 checkpoint 直接用 S3 Express One Zone（低延迟对象存储，跳过 Lustre 中间层）
> 
> **GCP 上**：
> - 训练数据放 GCS，通过 GCS FUSE mount 到计算节点
> - TPU 训练用 GCS 直接 I/O（TPU + JAX 对 GCS 有原生优化）
> - Checkpoint 写 GCS
> 
> 关键设计原则：**计算和存储解耦**——训练数据和 checkpoint 的持久化在对象存储（S3/GCS），高性能访问通过缓存层（Lustre/GCS FUSE），GPU 节点是无状态的（可以随时换、随时扩）。

### Q: 分布式训练有哪些并行策略？它们对网络/存储有什么要求？

> **答题模板**：
> 
> 三种核心并行策略，通常组合使用（3D 并行）：
> 
> **Data Parallel**：每张 GPU 存完整模型副本，处理不同数据。需要 All-Reduce 同步梯度，网络需求中等（每步同步一次梯度，大小 = 模型参数量 × 精度字节数）。存储需求：每个 GPU 的 data loader 并行读训练数据 → 需要高吞吐并行读（FSx Lustre 强项）。
> 
> **Tensor Parallel**：单层权重矩阵切到多张 GPU。每次前向/后向都要 GPU 间通信 → 要求极高带宽、极低延迟 → 只能在同节点内用 NVLink（900 GB/s for H100）。存储无额外需求。
> 
> **Pipeline Parallel**：不同层分到不同节点。只在层的边界传 activation → 跨节点可以走 EFA/InfiniBand。存储无额外需求。
> 
> **FSDP/ZeRO**：把模型/优化器/梯度切片分到所有 GPU，显存减 Nx，但前向传播时需要 All-Gather 恢复完整权重 → 网络通信增加。对存储的影响：checkpoint 变成 sharded（每张 GPU 写自己的 shard），写并行度提升，但文件数增多。
> 
> 总结：Tensor Parallel 对网络要求最高（节点内 NVLink），Data Parallel 对存储要求最高（并行读训练数据 + checkpoint 写），Pipeline Parallel 介于两者之间。

---

*下一篇：[06-evaluation.md](06-evaluation.md) — Evaluation（模型评估/RAG 评估）*
