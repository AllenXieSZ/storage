# 大模型预训练完整流程：7 个阶段 × 存储视角

> **视角**：AWS Storage 架构师，从存储 IO 模式拆解预训练每个阶段的数据流、瓶颈与选型。

---

## 全局流程图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          大模型预训练 7 阶段                                      │
│                                                                                 │
│  ① 数据准备        ② Tokenization       ③ 数据加载与预取                         │
│  (收集/清洗/去重)   (分词/编码/打包)       (DataLoader/Shuffle/预取到 GPU)          │
│       ↓                   ↓                        ↓                            │
│                    ④ 前向传播 (Forward Pass)                                      │
│                    输入 → Embedding → L 层 Transformer → logits → Loss           │
│                              ↓                                                   │
│                    ⑤ 反向传播 (Backward Pass)                                     │
│                    Loss → 链式法则 → 每个参数的梯度                                │
│                              ↓                                                   │
│                    ⑥ 梯度同步与参数更新                                            │
│                    All-Reduce 多卡同步 → AdamW 优化器更新参数                      │
│                              ↓                                                   │
│                    ⑦ Checkpoint 保存与评估                                        │
│                    每 N 步写 checkpoint → 定期 eval → 归档到 S3                   │
│                                                                                 │
│  ④⑤⑥ 构成一个 training step，重复数百万次                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 阶段一：数据准备（Data Preparation）

### 做什么

把互联网上的原始文本变成干净、高质量的训练语料。

### 具体步骤

```
互联网爬取 (Common Crawl / 自有爬虫)
    ↓
语言检测 & 过滤（去掉非目标语言、乱码、广告页面）
    ↓
质量打分（用小模型/规则给每个文档打分，淘汰低质量内容）
    ↓
去重（MinHash / SimHash 近似去重 + 精确子串去重）
    ↓
敏感内容过滤（PII 脱敏、有害内容移除、版权过滤）
    ↓
领域混合（按比例混合：网页 50% / 代码 15% / 论文 10% / 书籍 10% / 对话 10% / 百科 5%）
    ↓
干净语料（15-30 TB 原始文本）
```

### 规模参考

| 模型 | 原始数据量 | 清洗后 | 最终训练 tokens |
|---|---|---|---|
| LLaMA-3 | — | — | 15.6T tokens |
| DeepSeek-V3 | — | — | 14.8T tokens |
| Falcon-180B | 5T tokens 原始 | 3.5T 清洗后 | 3.5T tokens |
| RedPajama | 30TB 原始文本 | — | 1.2T tokens |

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **数据量** | 原始爬取 PB 级 → 清洗后 30-100 TB 文本 |
| **IO 模式** | 大量小文件读（爬取的 HTML/WARC）→ 清洗/去重后输出大文件 |
| **去重** | 计算密集 + 全量扫描，MinHash 需要多轮 MapReduce |
| **瓶颈** | 小文件元数据（百亿级文件的 list/stat）→ Lustre MDT 压力 |
| **推荐** | 原始数据放 S3（低成本、无限容量），处理中间态放 Lustre 或 EBS（IOPS 敏感） |
| **成本** | 此阶段主要是 CPU + 存储成本，不需要 GPU |

---

## 阶段二：Tokenization（分词与编码）

### 做什么

把人类可读的文本转换成模型可处理的数字序列。

### 具体步骤

```
干净文本: "The cat sat on the mat"
    ↓
Tokenizer 分词 (BPE / SentencePiece / tiktoken)
    ↓
Token 序列: [464, 3797, 3332, 319, 262, 2603]
    ↓
打包成固定长度序列 (seq_len = 4096 / 8192)
    ↓
多个序列拼接，不够的接下一篇文档 (packing)
    ↓
存为二进制格式 (.bin / .arrow / .jsonl.zst)
```

### 主流 Tokenizer 对比

| Tokenizer | 词表大小 | 算法 | 代表模型 |
|---|---|---|---|
| GPT-2 BPE | 50,257 | Byte-Pair Encoding | GPT-2/3 |
| SentencePiece | 32,000 | BPE/Unigram | LLaMA-1/2 |
| tiktoken | 128,256 | BPE (字节级) | LLaMA-3、GPT-4 |
| DeepSeek tokenizer | 129,280 | BPE | DeepSeek-V3 |

**词表大小的影响**：
- 大词表（128K）→ 同样文本需要更少 token → 训练更快、推理更快、支持更多语言
- 代价：Embedding 层参数增大（128K × d vs 32K × d）

### Tokenization 后的数据格式

```
# 示例：Megatron-LM 格式
15T tokens × 2 bytes/token (uint16, 词表 <65536 用 2 字节) = ~30 TB
# 如果词表 >65536 (如 128K)，用 4 bytes/token (uint32) = ~60 TB
```

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **输入** | 30-100 TB 文本（大块顺序读） |
| **输出** | 30-60 TB 二进制 token 文件 |
| **IO 模式** | CPU 密集 + 顺序读写大文件，高吞吐低随机 |
| **并行** | 按文档/文件分片，多进程并行 tokenize |
| **瓶颈** | CPU（不需要 GPU），存储吞吐要跟上多进程写 |
| **推荐** | S3 读原始文本 → CPU 集群 tokenize → 输出到 S3 或 Lustre |
| **一次性** | tokenize 后的二进制文件可反复使用，不需要每次训练重做 |

---

## 阶段三：数据加载与预取（Data Loading & Prefetching）

### 做什么

训练时，高效地把 tokenize 后的数据从存储搬到 GPU 显存，不让 GPU 等数据。

### 具体机制

```
存储 (Lustre / S3)
    ↓  多 DataLoader worker 进程并行读取
    ↓  每个 worker 读取不同的数据分片
Page Cache / 用户态缓存
    ↓  按 batch 组装 (batch_size × seq_len 个 token)
    ↓  数据 Shuffle（epoch 间打乱顺序）
CPU 内存 (pinned memory)
    ↓  异步 DMA 传输 (PCIe / NVLink)
GPU 显存 (HBM)
    ↓  前向传播开始
```

### 数据并行下的分片

分布式训练时，数据在多个 GPU 间分片：

```
总 batch = global_batch_size = 4M tokens
8 节点 × 8 GPU = 64 GPU
每 GPU 的 micro_batch = 4M / 64 = 62,500 tokens
每 GPU 每步读取 seq_len=4096 → ~15 个序列
```

### Shuffle 策略

- **方案 A**：预先 shuffle 整个数据集，按顺序读 → 用存储空间换随机 IO
- **方案 B**：运行时随机索引读取 → 随机 IO，但不需要额外存储
- **实际做法**：Megatron-LM 用内存映射（mmap）+ index 文件 + 随机采样，避免大规模随机 IO

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **读取量** | 每步每 GPU 读取 ~250KB（15 × 4096 × 4 bytes），极小 |
| **但总聚合量** | 64 GPU × 250KB × 每秒约 3 步 ≈ ~48 MB/s（数据读取不是瓶颈） |
| **真正瓶颈场景** | 多模态训练（图像/视频 token）→ 每步读取 MB~GB 级 → 存储吞吐成瓶颈 |
| **mmap** | 大文件 mmap 后 OS 管页面缓存，首次读触发磁盘 IO，后续读命中缓存 |
| **prefetch** | DataLoader `num_workers=4-8` 个进程提前读下 N 个 batch → GPU 不等 |
| **Lustre 优势** | 条带化 + 多 OST → 聚合读带宽大，适合多节点同时读不同分片 |
| **S3 替代** | 用 S3 + streaming（HuggingFace datasets streaming）也可以，延迟略高但省存储 |

---

## 阶段四：前向传播（Forward Pass）

### 做什么

把一个 batch 的 token 正向通过整个模型，计算预测结果和损失值。

### 详细数据流

```
Token IDs [batch_size × seq_len]               ← 整数 tensor
    ↓
Embedding 层: 查表得到 [batch × seq × d]        ← d=4096（7B）/ 8192（70B）
    +
位置编码 (RoPE): 旋转 Q、K 的向量
    ↓
┌── Transformer Layer 1 ────────────────────────┐
│                                                │
│  LayerNorm                                     │
│      ↓                                         │
│  Self-Attention:                               │
│    Q = X × W_Q,  K = X × W_K,  V = X × W_V   │
│    scores = softmax(Q × K^T / √d_k)           │
│    output = scores × V                         │
│    output = output × W_O                       │
│      ↓                                         │
│  残差连接: output = output + X                  │
│      ↓                                         │
│  LayerNorm                                     │
│      ↓                                         │
│  FFN (Feed-Forward Network):                   │
│    gate = SiLU(X × W_gate)     ← SwiGLU       │
│    up = X × W_up                               │
│    output = (gate ⊙ up) × W_down               │
│      ↓                                         │
│  残差连接: output = output + X                  │
│                                                │
└── 重复 L 次 (32层/80层/126层) ────────────────┘
    ↓
最终 LayerNorm
    ↓
输出投影: [batch × seq × d] × W_vocab → [batch × seq × V]   ← V=词表大小
    ↓
logits（每个位置对词表中每个 token 的原始分数）
    ↓
与真实的下一个 token 计算交叉熵损失 (Cross-Entropy Loss)
    ↓
得到一个标量 Loss 值（如 2.31）
```

### 计算量

前向传播的 FLOPs（每个 token）≈ **2 × 参数量**

| 模型 | 参数量 | 每 token FLOPs (前向) | 每步 FLOPs (batch=4M tokens) |
|---|---|---|---|
| 7B | 7×10⁹ | 1.4×10¹⁰ | 5.6×10¹⁶ |
| 70B | 70×10⁹ | 1.4×10¹¹ | 5.6×10¹⁷ |
| 405B | 405×10⁹ | 8.1×10¹¹ | 3.2×10¹⁸ |

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **磁盘 IO** | **零**。前向传播完全在 GPU 显存内完成 |
| **显存 IO** | 大量 HBM 读写（权重矩阵乘法、激活值写入），是 GPU 内部带宽瓶颈 |
| **激活值** | 必须保存每层的中间结果供反向传播用 → 占显存 |
| **激活显存估算** | 约 12 × batch × seq × d × L bytes（简化，含注意力矩阵） |
| **Flash Attention** | 减少注意力矩阵的 HBM 读写 → 类似存储优化"减少 IO 往返" |
| **模型并行** | 模型太大放不进单卡 → 切分到多卡 → 产生**卡间通信 IO**（NVLink 900GB/s） |

---

## 阶段五：反向传播（Backward Pass）

### 做什么

从 Loss 出发，用链式法则反向计算每个参数应该怎么调整（梯度）。

### 详细流程

```
Loss (标量, 如 2.31)
    ↓
∂Loss/∂logits                              ← 输出层梯度
    ↓
∂Loss/∂W_vocab = ∂Loss/∂logits × activations^T    ← 输出投影权重的梯度
    ↓
┌── 反向穿过 Layer L → Layer 1 ──────────────────┐
│                                                  │
│  FFN 反向:                                       │
│    ∂Loss/∂W_down, ∂Loss/∂W_gate, ∂Loss/∂W_up    │
│    (需要前向保存的 gate、up 激活值)                 │
│      ↓                                           │
│  Attention 反向:                                  │
│    ∂Loss/∂W_Q, ∂Loss/∂W_K, ∂Loss/∂W_V, ∂Loss/∂W_O │
│    (需要前向保存的 Q、K、V、attention scores)       │
│      ↓                                           │
│  残差连接: 梯度直接加回                             │
│                                                  │
└── 重复 L 次 ─────────────────────────────────────┘
    ↓
∂Loss/∂Embedding
    ↓
所有参数都有了梯度 ∂Loss/∂W_i
```

### 计算量

反向传播 FLOPs ≈ **前向的 2 倍**。总的前向+反向 ≈ 6 × 参数量 × tokens/step。

### 激活重计算（Activation Checkpointing）

问题：保存所有层的激活值太占显存。解法：只保存部分层的激活，反向传播需要时**重新前向计算**。

```
前向时：只保存 Layer 1, 11, 21, 31 的激活（每 10 层存一个）
反向到 Layer 15 时：从 Layer 11 的激活重新前向算 Layer 12→15 的激活
```

- 显存节省 ~60-70%
- 代价：多算约 33% 的前向计算（用时间换空间）

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **磁盘 IO** | 正常情况**零**。激活在 GPU 显存 |
| **激活 Offload** | 显存不够时把激活卸载到 CPU 内存甚至 NVMe SSD → **产生 PCIe IO** |
| **Offload 带宽需求** | PCIe 5.0 x16 = 64 GB/s，需要匹配激活传输速率 |
| **DeepSpeed ZeRO-Offload** | 把优化器状态甚至部分参数卸载到 CPU → CPU 内存成"显存扩展" |
| **NVMe Offload** | DeepSpeed ZeRO-Infinity 支持把参数/梯度卸载到 NVMe SSD → 需要高 IOPS 的本地 SSD |

---

## 阶段六：梯度同步与参数更新

### 做什么

多卡训练时，每张卡算出的梯度需要**同步求平均**，然后用优化器更新参数。

### 数据并行（Data Parallelism）的梯度同步

```
GPU 0: ∂Loss/∂W (来自 micro_batch_0)
GPU 1: ∂Loss/∂W (来自 micro_batch_1)
  ...
GPU 63: ∂Loss/∂W (来自 micro_batch_63)
         ↓
    All-Reduce (Ring / Tree 拓扑)
    每个 GPU 得到 64 个梯度的平均值
         ↓
    所有 GPU 上的梯度相同
```

### 梯度累积（Gradient Accumulation）

显存放不下大 batch 时，把一个大 batch 分成多个 micro-batch，累积梯度后再同步：

```
micro_batch 1: 前向 → 反向 → 梯度存起来（不更新参数）
micro_batch 2: 前向 → 反向 → 梯度累加
  ...
micro_batch K: 前向 → 反向 → 梯度累加
    ↓
梯度 /= K（取平均）
    ↓
All-Reduce 同步
    ↓
优化器更新参数（这才是 1 个 step）
```

### AdamW 优化器更新

```python
# 对每个参数 W:
m = β1 × m + (1-β1) × grad          # 一阶矩（梯度滑动平均）
v = β2 × v + (1-β2) × grad²         # 二阶矩（梯度平方滑动平均）
m_hat = m / (1 - β1^t)               # 偏差修正
v_hat = v / (1 - β2^t)
W = W - lr × (m_hat / (√v_hat + ε) + weight_decay × W)  # 更新
```

**优化器状态体积**：每个参数需要额外存 m 和 v（都是 fp32）→ 优化器状态 = 2 × 参数量 × 4 bytes

| 模型 | 参数 (bf16) | 优化器状态 (fp32) | 梯度 (bf16) | 总训练显存 |
|---|---|---|---|---|
| 7B | 14 GB | 56 GB | 14 GB | ~84 GB + 激活 |
| 70B | 140 GB | 560 GB | 140 GB | ~840 GB + 激活 |
| 405B | 810 GB | 3240 GB | 810 GB | ~4.9 TB + 激活 |

### ZeRO（Zero Redundancy Optimizer）

解决多卡冗余存储：

| 阶段 | 分片内容 | 显存节省 |
|---|---|---|
| ZeRO-1 | 优化器状态分片（每卡只存 1/N） | ~4× |
| ZeRO-2 | + 梯度分片 | ~8× |
| ZeRO-3 | + 参数分片 | ~N× (线性于 GPU 数) |

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **网络 IO** | All-Reduce 是最大的网络 IO 操作：每步同步全部梯度 |
| **通信量** | 每步 All-Reduce 数据量 ≈ 2 × 模型参数大小（Ring All-Reduce） |
| **带宽需求** | 70B 模型 All-Reduce = 2 × 140GB = 280GB → 需要 EFA/InfiniBand（400Gbps+） |
| **计算-通信重叠** | 边算反向边发梯度（先算完的层先发）→ 隐藏通信延迟 |
| **ZeRO-Offload** | 优化器状态卸载到 CPU → 省 GPU 显存但增加 PCIe 带宽需求 |
| **ZeRO-Infinity** | 参数/梯度/优化器全卸载到 NVMe SSD → 需要高性能本地 NVMe |
| **EFA vs InfiniBand** | AWS 用 EFA（Elastic Fabric Adapter），p5.48xlarge 8×400Gbps=3.2Tbps 聚合 |

---

## 阶段七：Checkpoint 保存与评估

### 做什么

定期保存模型的完整状态（"存档"），用于灾难恢复和训练分支；定期评估模型质量。

### Checkpoint 内容

```
一个完整 Checkpoint 包含:
├── 模型参数 (bf16)           ← 70B 模型 = 140 GB
├── 优化器状态 (fp32, m + v)  ← 280 GB
├── 学习率调度器状态           ← 几 KB
├── 数据加载器状态             ← RNG seed + 已消费 sample 索引
├── 随机数种子                ← 可复现性
└── 训练 metadata             ← step 数、loss 值、配置等
     总计: ~420 GB (70B 模型)
```

### 分布式 Checkpoint（DCP）

大模型的 checkpoint 分布在多张 GPU 上，PyTorch DCP（Distributed Checkpoint）支持：

```
64 个 GPU 同时写各自的分片
    ↓
Lustre: 64 个分片文件并发写入不同 OST
    ↓
聚合写入吞吐: 22.5 GB/s (实测, FSx Lustre PERSISTENT_2)
    ↓
420 GB checkpoint 写入时间: ~19 秒
```

### 同步 vs 异步 Checkpoint

| 方式 | 阻塞训练 | 写入时间 | 优势 |
|---|---|---|---|
| **同步** | 全程阻塞（~19s） | 直接写 | 简单可靠 |
| **异步** | 仅 CPU 拷贝阻塞（~0.4s） | 后台写 | GPU 几乎不停 |

异步 checkpoint 流程：
```
训练 step N 完成
    → GPU 显存 snapshot → 拷贝到 CPU pinned memory (阻塞 ~0.4s)
    → GPU 立即继续 step N+1
    → 后台线程: CPU memory → 写 Lustre (不阻塞训练)
```

### Checkpoint 保留策略

```
训练时间线:
Step 0 ─── 1K ─── 2K ─── 3K ─── ... ─── 3900K
     │      │      │      │               │
     ▼      ▼      ▼      ▼               ▼
   ckpt   ckpt   ckpt   ckpt           ckpt
   (热)   (热)   (温)   (温)           (热)
            │            │
            ▼            ▼
          Lustre NVMe   → DRA 自动导出 → S3 (冷存储)
```

- **热**（最近 3-5 个）：保留在 Lustre NVMe tier，随时回滚
- **温**（最近 1-2 天）：Lustre HDD tier 或 S3 Standard
- **冷**（更早的）：S3 Glacier 或删除，按保留策略决定

### 定期评估（Evaluation）

每 N 步（如每 1000 步）在验证集上跑推理，不更新参数：

```
常见评估指标:
├── Validation Loss (验证集上的交叉熵损失)
├── Perplexity (困惑度 = e^loss，越低越好)
├── 下游任务 Benchmark:
│   ├── MMLU (多学科知识)
│   ├── HumanEval (代码生成)
│   ├── GSM8K (数学推理)
│   ├── HellaSwag (常识推理)
│   └── ...
└── 安全评估 (有害内容生成率)
```

### 🗄️ 存储视角

| 维度 | 特征 |
|---|---|
| **写入量** | 每次 checkpoint: 420 GB (70B) ~ 2.4 TB (405B) |
| **写入频率** | 每 500-2000 步一次 |
| **总存储量** | 3900 次 × 420 GB = **1.6 PB**（70B 全量保留） |
| **IO 模式** | 几百个文件并发大块顺序写 → Lustre 多 OST 并行 |
| **延迟敏感** | **极其敏感**：同步写阻塞训练 → 每秒阻塞 = GPU 空闲 = $$$$ |
| **可靠性要求** | checkpoint 写入必须原子/完整 → 写一半断电不能污染上一个好的 ckpt |
| **恢复速度** | NaN/故障后 ~420 GB 要尽快读回 64 张 GPU → 需要高读吞吐 |
| **归档** | 冷 checkpoint 通过 DRA 自动导出到 S3 → 存储成本从 $0.14/GB/月(Lustre) 降到 $0.023/GB/月(S3) |

### Checkpoint 写入是 FSx Lustre 在 AI 训练中的 #1 存储场景

```
GPU 利用率公式:

GPU 利用率 = 训练计算时间 / (训练计算时间 + checkpoint 写入时间 + 通信等待时间)

同步 checkpoint 19s / 每 1000 步(~每 5 分钟):
  效率损失 = 19 / (300 + 19) ≈ 6%

异步 checkpoint 0.4s:
  效率损失 = 0.4 / (300 + 0.4) ≈ 0.13%

405B 模型 3000 万 GPU 小时:
  6% 浪费 = 180 万 GPU 小时 = ~$600 万
  0.13% 浪费 = 3.9 万 GPU 小时 = ~$13 万
  差额: ~$590 万 —— 这就是高性能存储的 ROI
```

---

## 附：完整训练一步的时间分解

以 70B 模型、64 × H100 GPU、global batch = 4M tokens 为例（估算）：

```
┌──────────────────────────────────────────────────────────┐
│               一个 Training Step (~5 秒)                  │
│                                                          │
│  ③ 数据加载    0.01s  ████                      (预取覆盖) │
│  ④ 前向传播    1.5s   ████████████████████████            │
│  ⑤ 反向传播    3.0s   ████████████████████████████████████│
│  ⑥ All-Reduce 0.3s   ██████        (与反向重叠)           │
│  ⑥ AdamW 更新  0.2s   ████                               │
│  ⑦ Checkpoint  0.4s   ██████     (异步, 每 1000 步)       │
│                                                          │
│  总计: ~5s/step                                           │
│  吞吐: 4M tokens / 5s = 800K tokens/s                    │
│  GPU 利用率: MFU ~40-50%                                  │
└──────────────────────────────────────────────────────────┘
```

### IO 来源分布

| IO 类型 | 来源 | 带宽需求 | 阶段 |
|---|---|---|---|
| **存储读** | 训练数据预取 | ~50 MB/s (文本), ~GB/s (多模态) | ③ |
| **GPU 显存读写** | 权重/激活/梯度 | ~3 TB/s (HBM3) | ④⑤ |
| **卡间通信** | All-Reduce 梯度同步 | 400 Gbps+ (EFA) | ⑥ |
| **存储写** | Checkpoint | 20+ GB/s (Lustre) | ⑦ |
| **存储写** | Checkpoint 归档 | ~GB/s (DRA→S3) | ⑦ 后台 |

---

## 参考资料

- [LLaMA-3 技术报告](https://arxiv.org/abs/2407.21783) — 完整训练流程与超参数
- [Megatron-LM](https://github.com/NVIDIA/Megatron-LM) — NVIDIA 大模型训练框架
- [DeepSpeed ZeRO](https://arxiv.org/abs/1910.02054) — 分布式优化器与 offload
- [PyTorch DCP](https://pytorch.org/docs/stable/distributed.checkpoint.html) — 分布式 checkpoint
- [Flash Attention](https://arxiv.org/abs/2205.14135) — IO-aware 注意力优化
- [AWS FSx for Lustre](https://docs.aws.amazon.com/fsx/latest/LustreGuide/) — AI 训练存储
- [Chinchilla Scaling Law](https://arxiv.org/abs/2203.15556) — 最优参数量与数据量
