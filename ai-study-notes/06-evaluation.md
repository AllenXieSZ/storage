# 06 - Evaluation（模型评估 / RAG 评估）

## 一、为什么评估很重要

"如果你不能衡量它，你就不能改进它。"——模型好不好，不能靠"感觉"，必须用指标量化。

LLM 评估比传统 ML 难得多：传统 ML 有明确的正确答案（分类标签、回归数值），LLM 的输出是自由文本——同一个问题可以有无数种"正确"的回答。

---

## 二、传统 ML 指标（基础知识）

### 2.1 分类指标

| 指标 | 公式 | 含义 | 适用场景 |
|------|------|------|---------|
| **Accuracy** | (TP+TN) / (TP+TN+FP+FN) | 整体正确率 | 类别平衡时 |
| **Precision** | TP / (TP+FP) | 预测为正的里面真正为正的比例 | 关注"误报"：垃圾邮件检测 |
| **Recall** | TP / (TP+FN) | 真正为正的里面被预测出来的比例 | 关注"漏报"：疾病筛查 |
| **F1 Score** | 2 × P × R / (P + R) | Precision 和 Recall 的调和平均 | 两者都重要时 |

```
              实际正例    实际负例
预测正例       TP          FP（误报/假阳性）
预测负例       FN（漏报）   TN

Precision = "我说是的，真的是吗？"
Recall    = "真正是的，我找到了几个？"
```

### 2.2 AUC-ROC

**ROC 曲线**：横轴 FPR（False Positive Rate），纵轴 TPR（True Positive Rate = Recall），在不同阈值下画出来的曲线。

**AUC**（Area Under the ROC Curve）：ROC 曲线下的面积，0.5 = 随机猜，1.0 = 完美。

用途：评估**二分类模型在不同阈值下的综合表现**，不受类别不平衡影响。

### 2.3 文本生成指标

| 指标 | 用途 | 原理 |
|------|------|------|
| **BLEU** | 机器翻译 | 比较生成文本和参考文本的 n-gram 重合度 |
| **ROUGE** | 文本摘要 | 比较 n-gram recall（参考文本的 n-gram 有多少出现在生成文本中） |
| **METEOR** | 翻译 | BLEU 改进版，考虑同义词和词序 |
| **BERTScore** | 通用 | 用 BERT embedding 计算语义相似度（不限于 n-gram 匹配） |

**BLEU 和 ROUGE 的局限**：只看字面重合，不管语义。"我很开心"和"我非常快乐"BLEU 分数很低，但语义一样。这就是为什么 LLM 评估需要更高级的方法。

---

## 三、LLM 评估三层体系

### 3.1 第一层：自动指标（Automatic Metrics）

| 指标 | 说明 | 适用 |
|------|------|------|
| Perplexity (PPL) | 模型对测试文本的"困惑度"，越低越好 | 预训练模型内在质量 |
| Exact Match (EM) | 输出和参考答案完全匹配 | 问答（有唯一标准答案时） |
| F1 (token-level) | 输出和参考答案的 token 级 F1 | 问答 |
| BLEU/ROUGE | 见上 | 翻译/摘要 |
| Pass@k (代码) | 生成 k 个代码方案，至少一个通过测试 | 代码生成 |

**标准评估基准**：

| 基准 | 评估内容 | 任务数 |
|------|---------|--------|
| MMLU | 多学科知识（57 个学科） | 14042 道选择题 |
| HumanEval | 代码生成 | 164 道编程题 |
| GSM8K | 数学推理 | 8.5K 道小学应用题 |
| HellaSwag | 常识推理 | 10K 道 |
| TruthfulQA | 真实性（抗幻觉） | 817 道 |
| MATH | 数学竞赛题 | 12.5K 道 |

### 3.2 第二层：LLM-as-a-Judge（用 LLM 评 LLM）

用一个强大的 LLM（如 GPT-4）作为"评委"，给其他模型的输出打分。

```python
# LLM-as-a-Judge 示例 prompt
judge_prompt = """
你是一个公正的评估专家。请评估以下回答的质量。

问题：{question}
回答：{answer}

评分标准：
1. 准确性 (1-5)：信息是否正确
2. 完整性 (1-5)：是否覆盖了关键点
3. 清晰度 (1-5)：是否容易理解
4. 相关性 (1-5)：是否切题

请给出每个维度的分数和理由，以及总评。
输出 JSON 格式：
{{"accuracy": N, "completeness": N, "clarity": N, "relevance": N, "total": N, "reasoning": "..."}}
"""
```

**三种 Judge 模式**：
| 模式 | 说明 | 适用 |
|------|------|------|
| **Single Rating** | Judge 给单个回答打分（1-5 或 1-10） | 评估单模型质量 |
| **Pairwise Comparison** | Judge 比较两个回答，选更好的一个 | 模型 A vs B 对比 |
| **Reference-guided** | 给 Judge 一个参考答案，评判回答与参考的一致性 | 有标准答案时 |

### 3.3 LLM-as-a-Judge 的偏见

| 偏见类型 | 说明 | 缓解 |
|---------|------|------|
| **Position Bias** | Judge 倾向于选择特定位置的回答（如总是选第一个） | 随机化回答顺序，多次评估取平均 |
| **Verbosity Bias** | Judge 倾向于给更长的回答更高分（"长 = 好"） | prompt 里明确"简洁不扣分" |
| **Self-Enhancement Bias** | GPT-4 做 Judge 时倾向于给 GPT-4 的回答更高分 | 用不同模型做 Judge，或用开源 Judge 模型 |
| **Format Bias** | Judge 偏爱特定格式（如 Markdown 表格、编号列表） | prompt 里明确"不要因格式加分" |

### 3.4 第三层：人工评估

最可靠但最贵。由领域专家根据评分标准逐条评估。

| 人工评估维度 | 说明 |
|-------------|------|
| Helpfulness | 回答对用户有多大帮助 |
| Harmlessness | 回答是否安全无害 |
| Honesty | 回答是否诚实（不确定时是否承认不知道） |
| Instruction Following | 是否遵循了用户的具体指令 |

**三层体系的成本-精度权衡**：

```
                                精度
                                 ↑
                   人工评估 ●─────── 最高精度，最高成本
                                    │
                                    │
            LLM-as-a-Judge ●─────── 中等精度，中等成本
                                    │
                                    │
              自动指标 ●─────────── 最低精度（文本生成场景），最低成本
                                 ↓
                              成本 →
```

---

## 四、RAG 评估

RAG 系统的评估不只是评模型输出，还要评**检索质量**。

### 4.1 RAG 评估三维度

```
用户问题 ─── 检索 ──→ 检索到的上下文 ─── 生成 ──→ 最终回答
    │                     │                         │
    │                     │                         │
    │    ┌────────────────┤                         │
    │    │ Context         │                         │
    │    │ Relevance       │                         │
    │    │ (上下文相关性)   │                         │
    │    └────────────────┘                         │
    │                     │    ┌────────────────────┤
    │                     │    │ Faithfulness        │
    │                     │    │ (忠实度)             │
    │                     │    │ 回答基于上下文？      │
    │                     │    └────────────────────┘
    │                                               │
    │    ┌──────────────────────────────────────────┤
    │    │ Answer Relevance                          │
    │    │ (答案相关性)                               │
    │    │ 回答切题吗？                               │
    │    └──────────────────────────────────────────┘
```

| 维度 | 评估什么 | 低分意味着 |
|------|---------|-----------|
| **Context Relevance** | 检索到的文档是否与问题相关 | 检索系统有问题（embedding 不好 / 索引参数不对） |
| **Faithfulness** | 回答是否忠实于检索到的上下文（不编造） | 模型在"幻觉"——生成了上下文里没有的信息 |
| **Answer Relevance** | 回答是否回答了用户的问题 | 模型跑题了 |

### 4.2 RAGAS 框架

RAGAS（Retrieval Augmented Generation Assessment）是目前最流行的 RAG 评估框架，定义了四个核心指标：

| 指标 | 计算方法 | 值域 | 说明 |
|------|---------|------|------|
| **Faithfulness** | 从回答中提取 claims → 检查每个 claim 是否有上下文支持 | 0-1 | 1 = 所有 claim 都有上下文支持 |
| **Answer Relevancy** | 用 LLM 从回答反推可能的问题 → 和原问题算相似度 | 0-1 | 1 = 完全切题 |
| **Context Precision** | 检索到的 Top-K 文档中，相关文档排在前面 | 0-1 | 1 = 相关文档全排最前 |
| **Context Recall** | 参考答案中的信息有多少被检索到的上下文覆盖 | 0-1 | 1 = 信息全覆盖 |

```python
# RAGAS 使用示例
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from datasets import Dataset

# 准备评估数据
eval_data = Dataset.from_dict({
    "question": ["FSx Lustre 的 DRA 是什么？"],
    "answer": ["DRA 是 FSx Lustre 与 S3 之间的数据关联..."],
    "contexts": [["FSx Lustre supports Data Repository Associations (DRA)..."]],
    "ground_truth": ["DRA (Data Repository Association) 是 FSx Lustre 的功能..."]
})

# 运行评估
result = evaluate(
    eval_data,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall]
)
print(result)
# {'faithfulness': 0.92, 'answer_relevancy': 0.88, 'context_precision': 0.95, 'context_recall': 0.85}
```

### 4.3 RAG 评估最佳实践

| 实践 | 说明 |
|------|------|
| 构建评估数据集 | 至少 100-500 条 question + ground_truth + context |
| 自动化评估 | CI/CD 中集成 RAGAS，每次改动自动跑评估 |
| 分维度定位问题 | Faithfulness 低→模型幻觉，Context Recall 低→检索问题 |
| 对比基准 | 改了 embedding / chunk strategy / prompt 后，对比评估结果 |
| 人工抽查 | 自动评估之外，定期人工检查 20-50 条 |

---

## 五、存储视角加餐 ⭐

### 5.1 评估数据集版本管理

| 需求 | 存储方案 |
|------|---------|
| 评估数据集版本控制 | Git LFS / DVC（Data Version Control）+ S3/GCS 后端 |
| 评估结果存储 | BigQuery / Athena（S3 上的 Parquet），方便做趋势分析和 SQL 查询 |
| 评估日志/中间产物 | CloudWatch Logs / Cloud Logging，或直接存 S3 JSON 文件 |
| A/B 测试结果 | BigQuery / Redshift，带时间戳的结构化数据 |

### 5.2 评估结果趋势分析

```
评估结果表（BigQuery/Athena）：
┌──────────┬────────┬─────────────┬──────────────┬──────────────────┬────────┐
│ run_id   │ date   │ model       │ faithfulness │ answer_relevancy │ recall │
├──────────┼────────┼─────────────┼──────────────┼──────────────────┼────────┤
│ run_001  │ 11/01  │ gemini-pro  │ 0.85         │ 0.82             │ 0.78   │
│ run_002  │ 11/05  │ gemini-pro  │ 0.88         │ 0.85             │ 0.80   │  ← 改了 chunk size
│ run_003  │ 11/10  │ gemini-pro  │ 0.92         │ 0.88             │ 0.85   │  ← 改了 embedding 模型
│ run_004  │ 11/15  │ gemini-flash│ 0.90         │ 0.87             │ 0.85   │  ← 换了便宜模型
└──────────┴────────┴─────────────┴──────────────┴──────────────────┴────────┘

→ 用 SQL 做趋势分析：faithfulness 从 0.85 → 0.92，上升趋势
→ run_004 换 Flash 后 faithfulness 略降但可接受 → 省成本值得
```

### 5.3 大规模评估的成本

| 评估方式 | 100 条评估 | 1000 条评估 | 说明 |
|---------|-----------|-----------|------|
| 自动指标（BLEU/ROUGE） | ~$0（本地计算） | ~$0 | 几乎免费 |
| LLM-as-a-Judge (GPT-4o) | ~$2-5 | ~$20-50 | 主要是 token 成本 |
| LLM-as-a-Judge (Gemini Flash) | ~$0.5-1 | ~$5-10 | Flash 便宜很多 |
| 人工评估 | ~$200-500 | ~$2000-5000 | 按标注员工时计 |

---

## 六、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| LLM 自动评估 | **Vertex AI Gen AI Evaluation**（内置 faithfulness/safety 等指标） | **Bedrock Model Evaluation**（内置评估任务） |
| 模型对比 | **Vertex AI AutoSxS**（Side-by-Side 自动对比两个模型） | Bedrock Model Evaluation（pairwise） |
| RAG 评估 | Vertex AI Evaluation + RAGAS（开源） | Bedrock Knowledge Base Evaluation + RAGAS |
| 偏见检测 | Vertex AI Fairness Indicators, What-If Tool | **SageMaker Clarify**（bias detection） |
| 评估数据存储 | BigQuery, GCS | S3 + Athena, Redshift |
| 评估流水线 | Vertex AI Pipelines（Kubeflow 底层） | SageMaker Pipelines |
| 人工评估平台 | Vertex AI Labeling (数据标注) | **SageMaker Ground Truth**（人工标注） |

**Vertex AI Gen AI Evaluation 特点**：
- 一行代码运行评估：`evaluate(model, dataset, metrics=[...])` 
- 内置指标：Fluency, Coherence, Safety, Groundedness, Fulfillment
- 支持自定义 Judge prompt
- 结果自动存到 GCS，可视化在 Vertex AI 控制台

**Bedrock Model Evaluation 特点**：
- 支持 automatic evaluation（BERTScore/ROUGE 等）和 human evaluation
- Pairwise comparison：A 模型 vs B 模型自动对比
- 与 Bedrock Guardrails 集成（安全评估）

---

## 七、面试话术

### Q: 你怎么评估一个 RAG 系统的质量？

> **答题模板**：
> 
> RAG 评估我分三个维度，对应 RAGAS 框架的核心指标：
> 
> 第一，**检索质量**（Context Relevance / Context Precision / Context Recall）。检索出来的文档是否与问题相关？相关文档是否排在前面？Ground truth 需要的信息是否被检索到了？如果这一步就不行，后面生成再好也没用——"garbage in, garbage out"。
> 
> 第二，**忠实度**（Faithfulness）。模型的回答是否基于检索到的上下文？有没有"编造"上下文里不存在的信息？这是检测幻觉的关键指标。计算方法是从回答中提取每个 claim，逐条检查是否有上下文支持。
> 
> 第三，**答案相关性**（Answer Relevancy）。回答是否真正回答了用户的问题？不跑题、不说废话。
> 
> 实际操作：用 RAGAS 框架 + LLM-as-a-Judge 做自动评估，集成到 CI/CD 中——每次改 embedding 模型、chunk strategy、prompt template 后自动跑评估，对比前后分数。同时每周人工抽查 20-50 条做校准。
> 
> 如果 Faithfulness 低 → 模型在幻觉，考虑降 temperature、加 grounding 约束。如果 Context Recall 低 → 检索问题，考虑换 embedding 模型或调 chunk size。

### Q: LLM-as-a-Judge 有什么问题？怎么缓解？

> **答题模板**：
> 
> 四大偏见：
> 
> **Position Bias**——Judge 倾向于选择特定位置的回答。缓解：随机化回答顺序，每条评估跑两次（AB/BA），结果不一致的标记为 tie。
> 
> **Verbosity Bias**——更长的回答得分更高。缓解：prompt 里明确"简洁不扣分，冗长要扣分"。
> 
> **Self-Enhancement Bias**——GPT-4 做 Judge 时偏爱 GPT-4 的回答。缓解：用不同模型做 Judge（比如用 Claude 评 GPT，用 GPT 评 Claude），或用开源 Judge 模型（如 Prometheus）。
> 
> **Format Bias**——偏爱 Markdown 表格/编号列表等格式。缓解：prompt 里明确"不要因格式差异加减分"。
> 
> 终极方案：LLM-as-a-Judge 做初筛 + 人工评估做校准。用 Cohen's Kappa 检查 LLM Judge 和人工的一致性，一致性高（>0.7）说明 LLM Judge 可信。

---

*下一篇：[07-grounding.md](07-grounding.md) — Grounding / 幻觉控制*
