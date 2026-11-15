# 01 - Foundation Models / LLM（大语言模型）

## 一、什么是 Foundation Model

Foundation Model（基础模型）是在**大规模数据上预训练**、可以**适配下游多种任务**的大型模型。"基础"的含义是：这个模型是后续所有应用的地基——不管你要做翻译、摘要、问答、代码生成，都从这个预训练好的模型出发，而不是每个任务从零训一个模型。

LLM（Large Language Model，大语言模型）是 Foundation Model 里专注于自然语言的一类，代表模型有 GPT-4、Gemini、Claude、LLaMA 等。

### 核心特征

| 特征 | 说明 |
|------|------|
| 大规模预训练 | 在万亿 token 级别的文本上训练 |
| 通用能力 | 一个模型搞定翻译/摘要/问答/代码等多种任务 |
| 涌现能力（Emergent Abilities） | 模型达到一定规模后突然出现的新能力（如 few-shot learning、chain-of-thought reasoning），小模型没有，大模型"突然就会了" |
| 适配灵活 | 通过 prompt engineering、fine-tuning、RAG 等方式适配具体任务 |

---

## 二、Transformer 架构

Transformer 是 2017 年 Google 论文《Attention Is All You Need》提出的架构，**取代了 RNN/LSTM**，成为当前所有主流 LLM 的基础。

### 2.1 为什么 Transformer 取代了 RNN

| 维度 | RNN/LSTM | Transformer |
|------|----------|-------------|
| 计算方式 | 串行（一个 token 接一个 token 处理） | 并行（所有 token 同时处理） |
| 长距离依赖 | 衰减严重，长文本记不住开头 | 自注意力直接连接任意两个位置 |
| 训练速度 | 慢（无法并行） | 快（GPU 并行友好） |
| 扩展性 | 难以扩展到几百亿参数 | 可扩展到万亿参数 |

### 2.2 三种 Transformer 变体

```
┌─────────────────────────────────────────────────────────┐
│                    Transformer 架构                       │
├──────────────────┬──────────────────┬────────────────────┤
│  Encoder-Only    │  Decoder-Only    │  Encoder-Decoder   │
│  (理解型)         │  (生成型)         │  (转换型)           │
│                  │                  │                    │
│  BERT            │  GPT 系列        │  T5                │
│  RoBERTa         │  LLaMA           │  BART              │
│  ALBERT          │  Gemini          │  mT5               │
│                  │  Claude          │  Flan-T5           │
│                  │  Mistral         │                    │
│                  │                  │                    │
│  双向注意力       │  单向注意力(因果) │  编码双向+解码单向  │
│  适合分类/NER/    │  适合文本生成/    │  适合翻译/摘要/     │
│  相似度计算       │  对话/代码        │  问答               │
└──────────────────┴──────────────────┴────────────────────┘
```

**Encoder-Only（编码器）**：双向注意力，能同时看到一个词的前后文。适合"理解"任务（分类、命名实体识别）。代表：BERT。

**Decoder-Only（解码器）**：因果注意力（causal attention），只能看到当前词之前的内容。适合"生成"任务。当前主流 LLM（GPT-4、Gemini、Claude、LLaMA）**全是 Decoder-Only**，因为生成能力最强、scaling 效果最好。

**Encoder-Decoder**：编码器理解输入，解码器生成输出。适合"输入→输出"的转换任务（翻译、摘要）。代表：T5。

### 2.3 自注意力机制（Self-Attention）

自注意力是 Transformer 的核心创新。简单说：**让每个 token "看看"序列里其他所有 token，决定应该关注谁。**

计算过程：

1. 每个 token 通过三个线性变换生成三个向量：**Q**（Query）、**K**（Key）、**V**（Value）
2. 计算注意力分数：`Attention(Q, K, V) = softmax(QK^T / √d_k) × V`
3. `QK^T` 算出每对 token 之间的"相关性分数"
4. `÷ √d_k` 是缩放因子，防止点积太大导致 softmax 饱和
5. softmax 归一化成概率分布
6. 用这个概率加权求和 V，得到每个位置的输出

**Multi-Head Attention（多头注意力）**：不是只做一次注意力，而是并行做 h 次（比如 h=32），每次用不同的 Q/K/V 投影。不同的"头"可以学到不同类型的关注模式（有的关注语法，有的关注语义，有的关注位置关系），最后 concat 起来。

```
举例：句子 "The cat sat on the mat"
Head 1 可能学到：sat → cat（主语-谓语关系）
Head 2 可能学到：sat → mat（动作-地点关系）
Head 3 可能学到：the → cat, the → mat（冠词-名词关系）
```

---

## 三、预训练目标

不同架构配不同的预训练目标：

### 3.1 MLM（Masked Language Modeling）— 给 Encoder

把输入序列中 15% 的 token 随机 mask 掉，让模型预测被 mask 的 token。

```
输入：The [MASK] sat on the [MASK]
目标：The  cat   sat on the  mat
```

因为是双向的，模型能同时利用左右上下文来预测。BERT 就是用 MLM 训练的。

### 3.2 CLM（Causal Language Modeling）— 给 Decoder

给定前面的 token，预测下一个 token。这就是 GPT 系列的训练目标，也叫 **next-token prediction**。

```
输入：The cat sat on the
目标：                  mat
```

看起来简单，但 scaling law 证明：**只要模型够大、数据够多，这个简单目标就能涌现出强大的能力。**

### 3.3 Seq2Seq（Sequence-to-Sequence）— 给 Encoder-Decoder

输入一个序列，输出另一个序列。T5 把所有 NLP 任务统一为 text-to-text 格式：

```
输入：translate English to French: The cat sat on the mat
输出：Le chat s'est assis sur le tapis
```

---

## 四、Token 与 Tokenizer

### 4.1 什么是 Token

Token 是模型处理文本的**最小单位**。不是"字"也不是"词"——而是 tokenizer 切出来的子词片段。

```
例子（GPT-4 tokenizer）：
"Embedding" → ["Embed", "ding"]       （2 个 token）
"人工智能"  → ["人工", "智能"]          （2 个 token）
"unbelievable" → ["un", "believ", "able"]  （3 个 token）
```

**为什么用 token 而不是字/词？**
- 用字：词汇表太大（中文几万字），且丢失词级语义
- 用词：OOV（Out-of-Vocabulary）问题，新词/罕见词处理不了
- 用子词（subword）：兼顾词汇表大小和覆盖率，高频词整词保留，低频词拆成子词

### 4.2 三种主流 Tokenizer

| Tokenizer | 算法 | 使用模型 | 特点 |
|-----------|------|----------|------|
| **BPE**（Byte Pair Encoding） | 统计高频字节对，迭代合并 | GPT 系列, LLaMA, Mistral | 最流行，从字节出发自底向上合并 |
| **WordPiece** | 类似 BPE，但用似然增益选合并 | BERT, DistilBERT | Google 原创，BERT 家族标配 |
| **SentencePiece** | 统一的文本→token 处理器 | T5, mT5, PaLM, Gemini | 语言无关，不需要预分词（对中日韩友好） |

**BPE 算法核心步骤**：
1. 初始化：把每个字符（或字节）作为初始词汇表
2. 统计：统计所有相邻 token 对的频率
3. 合并：把频率最高的一对合并为新 token
4. 重复步骤 2-3 直到词汇表达到目标大小（如 32K/50K/100K）

### 4.3 Token 与计费/成本

云服务的 LLM API 按 token 计费：

| 模型 | 输入价格 | 输出价格 |
|------|----------|----------|
| GPT-4o | $2.50/1M tokens | $10.00/1M tokens |
| Gemini 1.5 Pro | $1.25/1M tokens | $5.00/1M tokens |
| Claude 3.5 Sonnet | $3.00/1M tokens | $15.00/1M tokens |

**经验法则**：英文 1 token ≈ 4 个字符 ≈ 0.75 个单词；中文 1 token ≈ 1-2 个汉字。

---

## 五、参数量与模型规模

### 5.1 什么是"参数"

模型里的每一个**可学习的数字**就是一个参数。参数存在于：
- **权重矩阵 W**（最大头）：Attention 层的 Wq/Wk/Wv/Wo、FFN 层的 W1/W2
- **偏置向量 b**（相对小）
- **Layer Norm 参数**（更小）

当我们说"7B 模型"就是 70 亿个参数，"70B"就是 700 亿个参数。

### 5.2 参数量计算（以标准 Transformer Decoder 为例）

一个 Transformer Decoder 层的参数量：
- Attention：`4 × d² + 4d`（Wq/Wk/Wv/Wo 各 d×d，加偏置）
- FFN：`2 × d × 4d + 4d + d = 8d² + 5d`（两个线性层，隐藏维度通常 4d）
- Layer Norm：`4d`
- **单层合计** ≈ `12d²`（忽略低阶项）

整个模型：`N 层 × 12d² + V × d`（V=词汇表大小的 embedding 矩阵）

| 模型 | 参数量 | 层数 | 隐藏维度 d | 注意力头数 |
|------|--------|------|-----------|-----------|
| LLaMA-2 7B | 6.7B | 32 | 4096 | 32 |
| LLaMA-2 70B | 68.9B | 80 | 8192 | 64 |
| LLaMA-3.1 405B | 405B | 126 | 16384 | 128 |
| Gemini 1.5 Pro | 未公开（推测数百 B 级 MoE） | - | - | - |
| GPT-4 | 未公开（传言 ~1.8T MoE） | - | - | - |

### 5.3 参数量与存储

| 精度 | 每参数字节数 | 7B 模型大小 | 70B 模型大小 | 405B 模型大小 |
|------|-------------|------------|-------------|--------------|
| FP32 | 4 bytes | 28 GB | 280 GB | 1.62 TB |
| FP16/BF16 | 2 bytes | 14 GB | 140 GB | 810 GB |
| INT8 | 1 byte | 7 GB | 70 GB | 405 GB |
| INT4（GPTQ/AWQ） | 0.5 bytes | 3.5 GB | 35 GB | ~203 GB |

---

## 六、MoE（Mixture of Experts）

### 6.1 核心思想

传统 Dense 模型：**每个输入都经过所有参数**（100% 参数参与计算）。
MoE 模型：**每个输入只激活一部分"专家"**（比如 8 个专家只激活 2 个，~25% 参数参与计算）。

这意味着 MoE 的**总参数量可以很大**（提升模型容量/知识存储），但**每次推理的计算量等价于小模型**。

### 6.2 架构

```
                     输入 token
                         │
                    ┌─────┴─────┐
                    │  Router   │  ← 门控网络，决定激活哪些专家
                    │ (Gating)  │
                    └─────┬─────┘
              ┌───────┬───┴───┬───────┐
              ▼       ▼       ▼       ▼
          Expert 1  Expert 2  ...  Expert N    ← 每个专家是一个独立的 FFN
              │       │               │
              ▼       ▼               ▼
         只取 Top-K 个专家的输出加权求和（K=1 或 2）
```

**Router/Gate**：一个小型线性层 + softmax，输出每个专家的"打分"，选 Top-K 激活。

### 6.3 代表模型

| 模型 | 总参数 | 每次激活参数 | 专家数 | Top-K |
|------|--------|-------------|--------|-------|
| Mixtral 8x7B | 46.7B | ~12.9B | 8 | 2 |
| Mixtral 8x22B | 176B | ~44B | 8 | 2 |
| Gemini 1.5 Pro | 未公开 | 未公开 | 未公开 | 未公开 |
| GPT-4（传言） | ~1.8T | ~280B | 16 | 2 |
| DeepSeek-V2 | 236B | 21B | 160 | 6 |

### 6.4 MoE 的存储挑战

**总参数大 = 模型文件大**。Mixtral 8x7B 虽然推理等价 13B Dense，但权重文件大小接近 47B Dense 的量。存储和加载的开销与总参数成正比，不是激活参数。

---

## 七、Scaling Laws

2020 年 OpenAI 论文《Scaling Laws for Neural Language Models》揭示了三角关系：

### 模型性能（Loss）由三个因素决定：

```
性能 ∝ f(参数量 N, 数据量 D, 计算量 C)

其中：C ≈ 6ND（6 × 参数量 × 训练 token 数）
```

| 因素 | 含义 | 实际数字 |
|------|------|---------|
| N（参数量） | 模型有多少个可学习的数字 | 7B → 70B → 405B → 1T+ |
| D（数据量） | 训练用了多少 token | 1T → 2T → 15T tokens |
| C（计算量） | 用了多少 FLOPs（浮点运算次数） | 10²¹ → 10²⁴ → 10²⁵ FLOPs |

### Chinchilla Scaling Law（2022 DeepMind）

关键结论：**参数量和数据量应该等比例扩展。** 之前的做法（大模型+少数据）不是最优的。

| 模型大小 | 最优训练 token 数 | 实际案例 |
|----------|------------------|---------|
| 1B | 20B tokens | - |
| 10B | 200B tokens | - |
| 70B | 1.4T tokens | LLaMA-2 70B 用了 2T tokens |
| 400B | 8T tokens | LLaMA-3.1 405B 用了 15T tokens |

> **注意**：实际训练往往超出 Chinchilla 最优比例（over-training），因为推理成本更重要——训练一次的成本固定，但推理是持续的。用更多数据训练的小模型，推理时更便宜。

---

## 八、存储视角加餐 ⭐

### 8.1 模型权重存储

| 存储场景 | 数据特征 | 存储选型 |
|----------|---------|---------|
| 模型仓库（HuggingFace 等） | 几 GB~几百 GB，下载频次低 | S3 / GCS，Standard 层 |
| 推理加载 | 启动时一次性读取全部权重到 GPU | 高吞吐顺序读，EBS io2（预热）/ S3 Express / GCS |
| 量化后模型 | fp16→int8 减半，int4 再减半 | 存储减半意味着加载时间减半 |

**量化对存储的影响**：
```
LLaMA-2 70B 模型权重：
FP32: 280 GB → FP16: 140 GB → INT8: 70 GB → INT4: 35 GB

存储成本（S3 Standard，每月）：
FP32: $6.44 → FP16: $3.22 → INT8: $1.61 → INT4: $0.81
```

### 8.2 Checkpoint 存储

训练过程中，每隔 N 步保存一次 checkpoint（全量模型权重 + 优化器状态 + 学习率调度器）：

| 组件 | 大小（70B 模型，FP16 训练） |
|------|--------------------------|
| 模型权重 | 140 GB |
| 优化器状态（Adam：m + v） | 280 GB（两个 FP32 拷贝） |
| 梯度 | 140 GB |
| **单个 checkpoint 合计** | **~560 GB** |

如果每 1000 步保存一次，训练 10 万步 = 100 个 checkpoint = **~56 TB**。

**Checkpoint IO 模式**：
- **写**：所有 GPU 同时 dump 到共享文件系统，突发大吞吐（几十 GB/次，要求 10+GB/s 写速度）
- **读**：恢复训练时一次性全量读
- **存储选型**：FSx Lustre（高吞吐并行写）、GCS FUSE + GCS（大块顺序 IO 友好）、S3 Express One Zone（低延迟对象存储）

### 8.3 训练数据存储

| 数据集 | 大小 | 说明 |
|--------|------|------|
| Common Crawl（一个月的快照） | ~200-300 TB（原始） | 需清洗去重后约几十 TB |
| The Pile（EleutherAI） | ~825 GB（清洗后） | 800B tokens |
| RedPajama | ~5 TB（清洗后） | 1.2T tokens |
| LLaMA-3.1 训练数据 | 未公开（推测 ~30-50 TB 清洗后） | 15T tokens |

**训练数据 IO 模式**：
- 大量**顺序读**（data loader 按 batch 顺序读取）
- 每个 epoch 全量扫描一遍
- 多 GPU 并行读取同一数据集
- **存储选型**：FSx Lustre（最佳，高吞吐并行读）、GCS + GCS FUSE（够用）、S3 + Mountpoint-S3（读取场景 OK）

### 8.4 GPU 显存层次

```
┌─────────────────────────────┐
│        SRAM (Register)       │  ← ~20 MB/GPU，最快（TB/s级），片上
├─────────────────────────────┤
│        L2 Cache              │  ← ~50 MB (H100), 片上共享
├─────────────────────────────┤
│   HBM (High Bandwidth Memory)│  ← 80 GB (H100), 3.35 TB/s
├─────────────────────────────┤
│   NVLink / PCIe (跨 GPU)     │  ← 900 GB/s (NVLink H100) / 128 GB/s (PCIe 5.0)
├─────────────────────────────┤
│   系统内存 (CPU DRAM)         │  ← 几百 GB~几 TB，DDR5 ~50 GB/s/channel
├─────────────────────────────┤
│   存储 (NVMe/网络文件系统)    │  ← NVMe ~7 GB/s，网络存储取决于网络带宽
└─────────────────────────────┘
```

**H100 GPU 存储相关参数**：
| 参数 | H100 SXM | A100 SXM |
|------|----------|----------|
| HBM 容量 | 80 GB (HBM3) | 80 GB (HBM2e) |
| HBM 带宽 | 3.35 TB/s | 2.0 TB/s |
| NVLink 带宽 | 900 GB/s | 600 GB/s |
| PCIe 带宽 | 128 GB/s (Gen5) | 64 GB/s (Gen4) |

---

## 九、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| 基础模型托管/API | **Vertex AI Model Garden**, Gemini API | **Amazon Bedrock**, SageMaker JumpStart |
| 自有模型（Google） | Gemini 1.5 Pro/Flash, PaLM 2 | Titan (Text/Embeddings/Image) |
| 三方模型市场 | Model Garden（Claude, Llama, Mistral） | Bedrock（Claude, Llama, Mistral, Cohere） |
| 模型推理托管 | Vertex AI Prediction Endpoints | SageMaker Inference Endpoints |
| GPU 实例 | A3/A3-mega (H100), A2 (A100), TPU v5 | p5 (H100), p4d (A100), Trn1 (Trainium), Inf2 (Inferentia) |
| 模型存储 | GCS (训练数据/checkpoint) | S3 / S3 Express One Zone / FSx Lustre |
| 训练数据高吞吐读 | GCS FUSE, Filestore (NFS) | FSx Lustre (DRA auto-import from S3), EFS |
| Checkpoint 高吞吐写 | GCS (via GCS FUSE), Filestore | FSx Lustre, S3 Express One Zone |

---

## 十、面试话术

### Q: 请解释什么是 Foundation Model，它和传统 ML 模型有什么区别？

> **答题模板**：Foundation Model 是在大规模无标注数据上预训练的通用模型，通过 transfer learning 适配下游任务，核心区别有三点：
> 
> 第一，**训练范式不同**。传统 ML 是 task-specific：每个任务收标注数据、训一个专用模型。Foundation Model 是 pre-train → adapt：先在海量无标注数据上自监督预训练，再通过 prompt/fine-tune 适配。
> 
> 第二，**规模不同**。传统模型几百万参数，训练数据 GB 级。Foundation Model 几十到几千亿参数，训练数据 TB 级。
> 
> 第三，**涌现能力**。模型到一定规模后会突然出现小模型没有的能力（in-context learning、chain-of-thought reasoning），这是传统 ML 没有的现象。
> 
> 在 GCP 上，Vertex AI Model Garden 提供了 Gemini、PaLM 等 Foundation Model 的托管推理和微调服务。AWS 对应的是 Amazon Bedrock。
> 
> 从**存储角度**看，Foundation Model 的训练数据几百 TB（Common Crawl 级别），需要高吞吐顺序读存储（GCS / FSx Lustre）；模型权重几十到几百 GB，checkpoint 存储 TB 级，要求高吞吐突发写。

### Q: 解释 Transformer 的自注意力机制和 MoE 的区别？

> **答题模板**：这是两个不同层面的概念。
> 
> **自注意力**是 Transformer 的核心计算机制，让每个 token 能"关注"序列中的其他 token，通过 Q/K/V 矩阵运算计算加权注意力，解决了 RNN 的长距离依赖和并行化问题。
> 
> **MoE** 是一种模型架构设计，把 Transformer 里的 FFN 层替换成多个"专家"FFN + 一个 Router。每个 token 只路由到 Top-K 个专家（通常 K=2），使得**总参数量大但每次推理只用一部分参数**。Gemini 和 Mixtral 都用了 MoE。
> 
> 从**存储角度**看，MoE 的关键影响是：模型文件大小取决于**总参数量**而非激活参数量。Mixtral 8x7B 推理等价 13B Dense，但权重文件接近 47B 的大小——这意味着存储和加载成本是按总参数算的。

---

*下一篇：[02-embeddings.md](02-embeddings.md) — Embeddings（向量嵌入）*
