# 04 - Fine-tuning（微调）+ 模型剪枝

## 一、什么是 Fine-tuning

Fine-tuning（微调）是在**预训练好的 Foundation Model 基础上**，用**特定任务/领域的数据进一步训练**，让模型适配特定需求。

```
预训练模型（通用能力）
    │
    ▼ + 领域数据 + 训练
    │
微调后的模型（通用 + 特定领域能力）
```

### 为什么需要 Fine-tuning

| 场景 | Prompt Engineering 够不够 | 需要 Fine-tuning |
|------|--------------------------|-----------------|
| 回答通用问题 | ✅ 够了 | ❌ |
| 特定输出格式（JSON/XML） | ✅ JSON Mode 搞定 | ❌ |
| 特定领域知识 | ✅ RAG 搞定 | ❌ |
| 特定语言风格/品牌调性 | ⚠️ System Prompt 有限 | ✅ |
| 高频调用省 token | ⚠️ Few-shot 每次都带示例太贵 | ✅ 微调后不需要 few-shot |
| 模型完全不会的新能力 | ❌ Prompt 搞不定 | ✅ |
| 极致延迟要求 | ⚠️ 长 prompt 慢 | ✅ 微调小模型替代大模型 |

---

## 二、Full Fine-tuning vs PEFT

### 2.1 Full Fine-tuning（全量微调）

**更新模型的所有参数**。效果最好，但成本极高。

```
原始模型：70B 参数（全部可训练）
训练数据：几千~几万条标注数据
GPU 需求：8×H100 (640 GB HBM) 起步
训练时间：几小时~几天
存储需求：模型权重 140 GB + 优化器状态 280 GB + 梯度 140 GB = ~560 GB
```

**问题**：
- GPU 显存必须装得下全部参数 + 优化器状态
- 每个任务存一份完整模型（70B = 140 GB/份）
- 灾难性遗忘（Catastrophic Forgetting）：微调后可能丢失预训练的通用能力

### 2.2 PEFT（Parameter-Efficient Fine-Tuning，参数高效微调）

**只训练一小部分参数（<1%）**，冻结大部分预训练权重。效果接近 Full Fine-tuning，成本低一个数量级。

| 方法 | 原理 | 可训练参数 |
|------|------|-----------|
| **LoRA** | 低秩分解，在权重矩阵旁加小矩阵 | ~0.1%-1% |
| **QLoRA** | 4-bit 量化 + LoRA | ~0.1%-1%（+ 量化存储省 75%） |
| **Prefix Tuning** | 在每层 attention 前加可学习的前缀向量 | ~0.1% |
| **Adapter Tuning** | 在 Transformer 层之间插入小型 adapter 模块 | ~1%-3% |
| **Prompt Tuning** | 学习 soft prompt embedding（不是人写的 prompt） | <0.01% |

---

## 三、LoRA / QLoRA 详解

### 3.1 LoRA（Low-Rank Adaptation）

**核心思想**：预训练权重矩阵 W 的"变化量" ΔW 是**低秩的**——不需要一个完整的 d×d 矩阵来表示变化，用两个小矩阵 A(d×r) 和 B(r×d) 的乘积就够了（r << d）。

```
原始前向传播：  y = Wx
LoRA 前向传播：  y = Wx + BAx     （W 冻结，只训练 A 和 B）

其中：
W: d×d 的原始权重矩阵（冻结，不更新）
A: d×r 的低秩矩阵（可训练）
B: r×d 的低秩矩阵（可训练）
r: 秩（rank），通常 4/8/16/32/64，远小于 d（4096/8192）
```

**参数量对比**：

```
以 LLaMA-2 70B 为例：
原始 Attention 层的 Wq 矩阵：8192 × 8192 = 67,108,864 个参数

LoRA (rank=16):
A: 8192 × 16 = 131,072
B: 16 × 8192 = 131,072
合计：262,144 个参数（是原来的 0.39%）

对所有 Attention 矩阵 (Wq/Wk/Wv/Wo) 加 LoRA：
4 × 262,144 × 80 层 = 83,886,080 ≈ 84M 可训练参数

vs 原模型 70B 参数 → LoRA 只训练 0.12% 的参数
```

**LoRA Adapter 大小**：
- rank=16, 70B 模型：~84 MB
- rank=64, 70B 模型：~336 MB
- 对比 Full Fine-tuning 的 140 GB 完整权重

### 3.2 QLoRA（Quantized LoRA）

QLoRA = **4-bit 量化** + LoRA。把冻结的基础模型权重从 fp16 量化到 4-bit（NF4 格式），显存占用减少 75%，然后在上面加 LoRA adapter。

```
Full Fine-tuning 70B：需要 8×H100 (640 GB HBM)
LoRA 70B：            需要 4×A100 (320 GB HBM)
QLoRA 70B：           需要 1×A100 (80 GB HBM)  ← 单卡可微调 70B！
```

| 方法 | 基础模型精度 | 可训练参数精度 | 70B 显存需求 | 效果 |
|------|-------------|--------------|-------------|------|
| Full FT | fp16 (140 GB) | fp16 | ~560 GB | 100%（基准） |
| LoRA | fp16 (140 GB) | fp16 | ~160 GB | ~98% |
| QLoRA | NF4 (35 GB) | fp16 | ~48 GB | ~97% |

---

## 四、SFT（Supervised Fine-Tuning）

SFT 是最常见的微调方式：用**人工标注的"问题-回答"对**作为训练数据。

### 4.1 数据格式

```json
[
  {
    "instruction": "解释 FSx Lustre 的 DRA 功能",
    "input": "",
    "output": "Data Repository Association (DRA) 是 FSx Lustre 与 S3 之间的数据通道..."
  },
  {
    "instruction": "比较 EBS gp3 和 io2 的性能",
    "input": "用户有一个 MySQL 数据库，需要 10000 IOPS",
    "output": "对于 10000 IOPS 的需求，gp3 和 io2 都能满足，但成本差异显著..."
  }
]
```

### 4.2 SFT 流程

```
1. 数据准备
   └─ 收集/标注 1000~50000 条高质量问答对
   └─ 数据清洗：去重、去低质量、格式统一

2. 选择基础模型
   └─ 开源：LLaMA-3.1 70B, Mistral 7B, Gemma 2
   └─ 闭源：Gemini（Vertex AI Tuning）, GPT-4o（OpenAI Fine-tuning）

3. 配置训练参数
   └─ Learning rate: 1e-5 ~ 5e-5
   └─ Epochs: 2-5（小数据集可以多跑几轮）
   └─ Batch size: 4-32（受显存限制）
   └─ LoRA rank: 8-64
   └─ LoRA target modules: q_proj, v_proj（最基本）或全部 attention 矩阵

4. 训练
   └─ 工具：HuggingFace Transformers + PEFT 库 / Vertex AI Tuning / SageMaker

5. 评估
   └─ 自动指标 + 人工评估
   └─ 对比基础模型和微调后模型

6. 部署
   └─ 合并 LoRA adapter 到基础模型（可选）
   └─ 或动态加载 adapter（一个基础模型 + 多个 adapter 适配不同任务）
```

### 4.3 SFT 数据质量 >> 数据量

关键原则：**数据质量远比数量重要。** 1000 条高质量数据 > 10 万条低质量数据。

| 数据量 | 适用场景 | 效果预期 |
|--------|---------|---------|
| 50-200 条 | 快速实验/PoC | 能看到方向性改善 |
| 500-2000 条 | 单一任务精调 | 明显的任务适配 |
| 2000-10000 条 | 生产级 SFT | 稳定的高质量输出 |
| 10000+ 条 | 多任务/复杂领域 | 全面覆盖 |

---

## 五、RLHF（Reinforcement Learning from Human Feedback）

RLHF 是在 SFT 之后的第二阶段训练，让模型的输出更"对齐"人类偏好（更有帮助、更安全、更诚实）。

### 训练流程

```
阶段 1：SFT
    └─ 用标注数据监督微调，让模型学会基本的指令遵循

阶段 2：训练 Reward Model（奖励模型）
    └─ 对同一个问题，模型生成多个回答（A, B, C, D）
    └─ 人类标注员对这些回答排序（A > C > B > D）
    └─ 用排序数据训练一个 Reward Model（输入：问题+回答 → 输出：分数）

阶段 3：PPO 优化（Proximal Policy Optimization）
    └─ 用 Reward Model 作为"打分器"
    └─ 模型生成回答 → Reward Model 打分 → 高分奖励、低分惩罚
    └─ 用 PPO 算法更新模型参数，让模型倾向于生成高分回答
    └─ 同时加 KL 散度约束，防止模型过度偏离原始 SFT 模型
```

**RLHF 的替代方案**：
| 方法 | 特点 |
|------|------|
| **DPO（Direct Preference Optimization）** | 不需要训练单独的 Reward Model，直接从偏好数据优化策略。更简单、更稳定。LLaMA-3 用的就是 DPO。 |
| **RLAIF（RL from AI Feedback）** | 用 AI 代替人类标注偏好数据，降低标注成本。Google 用于 Gemini 的部分训练。 |
| **Constitutional AI** | Anthropic 的方法，用一组"宪法"原则让 AI 自我评估和修正。Claude 系列用的。 |

---

## 六、决策树：Prompt Engineering vs RAG vs Fine-tuning

```
你的需求是什么？
│
├── 需要最新/外部知识？
│   ├── 是 → RAG（检索增强生成）
│   │   └─ 进一步：RAG 效果不够？→ RAG + Fine-tuning（先 RAG 检索，再用微调模型生成）
│   └── 否 → 继续判断
│
├── 需要特定输出格式/风格？
│   ├── 简单格式（JSON/列表） → Prompt Engineering（JSON Mode + System Prompt）
│   └── 复杂风格（品牌调性/特定行文） → Fine-tuning（SFT）
│
├── 任务复杂度？
│   ├── 简单（分类/抽取/翻译） → Prompt Engineering（Zero/Few-shot）
│   ├── 中等（推理/分析） → Prompt Engineering（CoT）+ 可能 RAG
│   └── 复杂（模型根本不会） → Fine-tuning
│
├── 调用频率和成本？
│   ├── 低频（内部工具）→ Prompt Engineering（能用就行，省开发成本）
│   └── 高频（面向用户 API）→ Fine-tuning 小模型替代大模型（省推理成本）
│       例：用微调后的 Gemini Flash 替代 few-shot 的 Gemini Pro
│
└── 以上都不满足？
    └── Fine-tuning（SFT + 可能 RLHF/DPO）
```

---

## 七、模型剪枝（Pruning）

剪枝是通过**移除模型中不重要的权重或结构**来减小模型大小、加速推理。

### 7.1 三种剪枝策略

| 策略 | 原理 | 效果 | 实现难度 |
|------|------|------|---------|
| **非结构化剪枝** | 把绝对值小的单个权重置零 | 参数级稀疏（90%+ 置零），但硬件加速困难 | 低 |
| **结构化剪枝** | 移除整个 attention head / FFN 神经元 / 整层 | 直接减少计算量，GPU 友好 | 中 |
| **SparseGPT / Wanda** | 2023 年新方法，一次 forward pass 就能完成剪枝 | 50% 非结构化稀疏几乎无损 | 中 |

### 7.2 SparseGPT

传统剪枝：训练→剪枝→重训练→再剪枝→……迭代很多轮。

SparseGPT：**不需要重训练**，只需要一次 forward pass + 校准数据，就能把模型剪到 50% 稀疏度（一半的权重为零），且精度损失极小。

```
LLaMA-2 70B 原始：70B 参数，140 GB (fp16)
SparseGPT 50% 稀疏 + INT4 量化：~17.5 GB
推理速度：约 2-3x 加速（需要稀疏计算硬件支持）
```

### 7.3 剪枝 vs 量化 vs 蒸馏

| 方法 | 原理 | 模型大小减少 | 精度影响 | 适用阶段 |
|------|------|------------|---------|---------|
| 量化 | 降低数值精度 (fp16→int8→int4) | 2-8x | 小 | 部署时 |
| 剪枝 | 移除不重要的权重/结构 | 2-10x | 小-中 | 训练后/部署时 |
| 蒸馏 | 用大模型教小模型 | 自定义 | 中 | 训练时 |
| **组合** | 蒸馏 + 剪枝 + 量化 | 10-50x | 中 | 全流程 |

---

## 八、存储视角加餐 ⭐

### 8.1 LoRA Adapter vs 全量 Checkpoint 的存储

| 维度 | LoRA Adapter | 全量微调 Checkpoint |
|------|-------------|-------------------|
| 单份大小（70B 模型） | 84 MB（rank=16）~336 MB（rank=64） | 140 GB（权重）+ 280 GB（优化器）= 420 GB |
| 100 个任务/版本 | 8.4 GB ~ 33.6 GB | **42 TB** |
| 存储选型 | S3/GCS Standard，低成本 | S3/GCS，但容量惊人 |
| 加载时间 | 秒级（adapter 小） | 分钟级（全量权重） |

### 8.2 两种部署策略

**策略一：合并部署（Merge）**

```
基础模型 (140 GB) + LoRA adapter (84 MB) → merge → 新的完整模型 (140 GB)
优点：推理时无额外开销，等价于普通模型
缺点：每个任务存一份完整模型，存储翻倍
```

**策略二：动态加载（Serve）**

```
一个基础模型 (140 GB) + N 个 adapter (N × 84 MB)
推理时按请求动态加载对应 adapter
优点：存储极省（基础模型只存一份）
缺点：切换 adapter 有延迟，需要 adapter 调度
```

**多 LoRA 服务框架**：vLLM、LoRAX、S-LoRA 支持在一个 GPU 上同时服务多个 LoRA adapter，通过 batch 合并请求提升吞吐。

### 8.3 微调训练的存储需求

| 场景 | 存储需求 | 选型 |
|------|---------|------|
| 训练数据（JSONL） | 几 MB ~ 几 GB | S3/GCS |
| 基础模型权重 | 几十 GB ~ 几百 GB | S3 → 下载到本地 NVMe / FSx Lustre |
| 训练 Checkpoint | 几百 MB（LoRA）~ 几百 GB（全量） | 本地 NVMe → 异步上传 S3/GCS |
| 最终输出 adapter | 几十 MB ~ 几百 MB | S3/GCS → 部署服务器 |

---

## 九、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| 托管 SFT | **Vertex AI Tuning**（Gemini SFT，按 token 计费） | **Bedrock Custom Models**（Claude/Llama Fine-tuning） |
| 托管 RLHF | Vertex AI Tuning（Gemini RLHF，预览） | Bedrock 暂不支持 RLHF |
| 自定义训练 | **Vertex AI Training**（自带 GPU 集群） | **SageMaker Training**（Spot Instance 降本） |
| 训练框架 | HuggingFace Transformers / DeepSpeed / Vertex AI SDK | HuggingFace / DeepSpeed / SageMaker SDK |
| 训练数据存储 | GCS | S3 |
| 模型存储 | GCS / Vertex AI Model Registry | S3 / SageMaker Model Registry |
| 训练 GPU | A3 (H100), A2 (A100), TPU v5p | p5 (H100), p4d (A100), Trn1 (Trainium) |
| LoRA 支持 | Vertex AI Tuning 内置 PEFT | SageMaker + HuggingFace PEFT 库 |

**Vertex AI Tuning 特点**：
- 一键式 SFT for Gemini：上传 JSONL → 选超参 → 训练 → 部署
- 自动 PEFT（内部可能用 LoRA），不需要管 GPU 配置
- 按训练 token 计费，不按 GPU 小时

**SageMaker Training 特点**：
- 更灵活：可以用任何框架（HuggingFace / DeepSpeed / Megatron-LM）
- Spot Instance 可省 60-90% GPU 成本
- SageMaker Distributed Training 支持 Model Parallel / Data Parallel
- 训练数据自动从 S3 拉到训练实例

---

## 十、面试话术

### Q: 什么时候用 Fine-tuning？LoRA 的原理是什么？

> **答题模板**：
> 
> Fine-tuning 的使用场景我用排除法判断：先看 Prompt Engineering 够不够 → 再看 RAG 够不够 → 都不行才上 Fine-tuning。
> 
> 具体来说，三种场景需要 Fine-tuning：一是需要**特定风格/格式**（品牌调性、严格的输出 schema），system prompt 搞不定；二是**高频调用省成本**——few-shot 每次带 5 个示例占 2000 token，每天调 100 万次就很贵，fine-tune 后可以去掉 few-shot；三是模型**完全不具备的能力**（特定领域的专业判断）。
> 
> LoRA 的原理是**低秩分解**：预训练权重矩阵 W 不动（冻结），在旁边加两个小矩阵 A(d×r) 和 B(r×d)，前向传播变成 y = Wx + BAx。r 通常取 8-64，远小于 d（4096-8192），所以可训练参数只有原来的 0.1%-1%。70B 模型的 LoRA adapter 只有 84-336 MB。
> 
> QLoRA 更进一步，把冻结的 W 从 fp16 量化到 NF4（4-bit），显存从 160 GB 降到 48 GB，单张 A100 就能微调 70B 模型。
> 
> 从**存储角度**看，LoRA 的最大优势是：100 个任务的 adapter 总共只要 8.4-33.6 GB，而全量微调要 42 TB（100×420GB）。部署时可以一个基础模型 + N 个 adapter 动态加载（vLLM/S-LoRA），极大节省存储和模型管理成本。

### Q: RLHF 是什么？为什么需要它？

> **答题模板**：
> 
> RLHF 是 SFT 之后的对齐阶段，目标是让模型输出更符合人类偏好——更有帮助、更安全、更诚实。
> 
> 三步走：第一步，SFT 让模型学会基本的指令遵循。第二步，用人类对多个回答的排序数据训练 Reward Model（打分器）。第三步，用 PPO 算法让模型朝着高 Reward 方向优化，同时 KL 约束防止偏离太远。
> 
> 为什么 SFT 不够？因为 SFT 只学了"怎么回答"，没学"什么是好的回答"。同一个问题可以有很多种正确但质量不同的回答，RLHF 帮模型学会区分"好"和"更好"。
> 
> 现在更流行的替代方案是 **DPO**（Direct Preference Optimization），不需要训练单独的 Reward Model，直接从偏好对数据优化模型，更简单更稳定。LLaMA-3 用的就是 DPO。
> 
> 在 GCP 上，Vertex AI Tuning 支持 Gemini 的 RLHF（预览阶段）。AWS Bedrock 目前只支持 SFT，不支持 RLHF。

---

*下一篇：[05-pre-training.md](05-pre-training.md) — Pre-training（预训练）*
