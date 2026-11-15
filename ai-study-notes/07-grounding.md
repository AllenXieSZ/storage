# 07 - Grounding / 幻觉控制

## 一、什么是幻觉（Hallucination）

LLM 幻觉是指模型**生成看起来流畅、自信，但实际上不正确或无依据的内容**。

### 1.1 两种幻觉

| 类型 | 定义 | 例子 |
|------|------|------|
| **Intrinsic Hallucination（内在幻觉）** | 生成的内容**与输入/上下文矛盾** | 文档说"FSx Lustre 最大吞吐 1000MB/s/TiB"，模型回答"2000MB/s/TiB" |
| **Extrinsic Hallucination（外在幻觉）** | 生成的内容**无法从输入/上下文验证**（可能对也可能错） | 问"FSx Lustre 性能"，模型回答了一个真实但文档里没有的细节 |

**直觉理解**：
- Intrinsic = "我给了你信息，你还说错了"（更严重）
- Extrinsic = "你说的这个我没法验证"（可能对，但不可靠）

### 1.2 幻觉的四大根因

| 根因 | 解释 |
|------|------|
| **训练数据噪声** | 互联网数据本身就有错误信息，模型学到了错误知识 |
| **知识截止** | 模型只知道训练数据截止日期前的信息，之后的事实回答不了 |
| **过度自信** | 模型被训练为"总是给出流畅的回答"，即使不确定也不会说"我不知道" |
| **概率采样** | 生成是概率性的（token by token），高 temperature 增加随机性 → 更容易偏离事实 |

---

## 二、三种 Grounding 策略

Grounding = **让模型的回答有据可依**，把输出"锚定"在可验证的信息源上。

### 2.1 RAG（Retrieval-Augmented Generation）

在推理时**检索外部知识库**，把检索到的文档塞入 prompt，让模型基于这些文档回答。

```
用户问题 → Embedding → 向量搜索 → Top-K 文档 → 塞入 prompt → LLM 生成回答
```

**优点**：知识可更新（改向量库就行）、可溯源（回答基于哪些文档）
**缺点**：检索质量有限、增加延迟、需要维护向量库

详细内容见 [02-embeddings.md](02-embeddings.md)（向量搜索）和 [03-prompt-engineering.md](03-prompt-engineering.md)（RAG vs 长上下文）。

### 2.2 Google Search Grounding

Google Gemini 独有能力：让模型在生成回答时**实时调用 Google Search**，用搜索结果作为依据。

```python
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, Tool, grounding

model = GenerativeModel("gemini-1.5-pro-002")

# 创建 Google Search Grounding 工具
google_search_tool = Tool.from_google_search_retrieval(
    grounding.GoogleSearchRetrieval(
        # MODE_DYNAMIC: 模型自己决定是否需要搜索
        dynamic_retrieval_config=grounding.DynamicRetrievalConfig(
            mode="MODE_DYNAMIC",
            dynamic_threshold=0.7  # confidence < 0.7 时触发搜索
        )
    )
)

response = model.generate_content(
    "2024 年 AWS re:Invent 有哪些存储相关的新发布？",
    tools=[google_search_tool]
)

# 检查 grounding metadata
grounding_metadata = response.candidates[0].grounding_metadata
print(f"Search queries: {grounding_metadata.search_queries}")
print(f"Grounding chunks: {grounding_metadata.grounding_chunks}")
print(f"Grounding supports: {grounding_metadata.grounding_supports}")
```

**关键参数**：

| 参数 | 说明 |
|------|------|
| `MODE_DYNAMIC` | 模型根据 confidence 自动决定是否搜索 |
| `MODE_UNSPECIFIED` | 每次都搜索 |
| `dynamic_threshold` | 0.0-1.0，越低越容易触发搜索。0.7 = 只有不太确定时才搜 |
| `grounding_chunks` | 搜索结果的来源 URL 列表（用于 citation） |
| `grounding_supports` | 回答中哪些部分被哪些 chunk 支持 |

**Google Search Grounding vs RAG**：

| 维度 | Google Search Grounding | RAG |
|------|------------------------|-----|
| 知识范围 | 整个互联网 | 你的知识库 |
| 实时性 | 实时（Google 索引） | 取决于向量库更新频率 |
| 成本 | 按搜索次数计费 | 向量库运维 + embedding API |
| 控制度 | 低（Google 决定搜什么） | 高（你控制知识库内容） |
| 私有数据 | ❌ 搜不到私有文档 | ✅ 私有知识库 |
| 适用 | 公开信息查询、时效性强 | 企业私有知识问答 |

### 2.3 Tool Use / Function Calling

让模型**调用外部工具/API** 获取实时数据，而不是从"记忆"中回答。

```python
# Gemini Function Calling 示例
import vertexai
from vertexai.generative_models import GenerativeModel, FunctionDeclaration, Tool

# 定义工具
get_storage_pricing = FunctionDeclaration(
    name="get_storage_pricing",
    description="获取 AWS/GCP 存储服务的实时价格",
    parameters={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "存储服务名（如 S3, EBS, FSx Lustre）"},
            "region": {"type": "string", "description": "区域（如 us-east-1）"},
        },
        "required": ["service", "region"]
    }
)

storage_tools = Tool(function_declarations=[get_storage_pricing])
model = GenerativeModel("gemini-1.5-pro-002", tools=[storage_tools])

response = model.generate_content("FSx Lustre 在 Ohio 的 PERSISTENT_2 每 GB 多少钱？")
# 模型会返回 function_call，你执行函数后把结果传回
```

---

## 三、四层防御体系

### 3.1 层次架构

```
┌────────────────────────────────────────────────────┐
│ Layer 4: UI 层                                      │
│ • 显示 citation（来源链接）                           │
│ • "AI 生成内容"标签                                  │
│ • 让用户能验证                                       │
├────────────────────────────────────────────────────┤
│ Layer 3: 后处理验证                                   │
│ • Claim Extraction（从回答中提取每个断言）            │
│ • Verification（用搜索/知识库验证每个断言）           │
│ • Citation Generation（给每个断言加来源引用）         │
├────────────────────────────────────────────────────┤
│ Layer 2: 解码参数控制                                 │
│ • Temperature 调低（0.0-0.3，减少随机性）            │
│ • Top-p / Top-k 调低（减少低概率 token 的出现）       │
│ • Frequency/Presence Penalty（减少重复）             │
├────────────────────────────────────────────────────┤
│ Layer 1: Prompt 工程                                  │
│ • System Prompt："只基于提供的文档回答"               │
│ • "如果不确定，说'我不确定'而不是编造"                │
│ • 提供上下文文档（RAG / Grounding）                  │
└────────────────────────────────────────────────────┘
```

### 3.2 后处理验证流程详解

```
模型生成的回答：
"FSx Lustre PERSISTENT_2 的基线吞吐是 125/250/500/1000 MB/s/TiB，
支持 DRA 自动导入导出，最大容量 100 PB。"

Step 1: Claim Extraction（用 LLM 提取断言）
├── Claim 1: "PERSISTENT_2 基线吞吐是 125/250/500/1000 MB/s/TiB"
├── Claim 2: "支持 DRA 自动导入导出"
└── Claim 3: "最大容量 100 PB"

Step 2: Verification（逐条验证）
├── Claim 1: ✅ 有文档支持（AWS FSx Lustre 文档）
├── Claim 2: ✅ 有文档支持
└── Claim 3: ❌ 文档说 "最大 2.4 PB per file system"（非 100 PB）

Step 3: Citation + Correction
├── Claim 1: [Source: AWS FSx Lustre Performance docs]
├── Claim 2: [Source: AWS FSx Lustre DRA docs]
└── Claim 3: 标记为不确定 / 修正为 "最大 2.4 PB per file system"

最终输出给用户的回答（带 citation + 修正）
```

### 3.3 Google Grounding 技术栈全景

| 组件 | 功能 | 对应服务 |
|------|------|---------|
| Google Search Grounding | 用 Google Search 实时搜索作为 grounding | Gemini API（内置） |
| Vertex AI Search | 企业私有数据的搜索引擎（RAG） | Vertex AI Search（原 Enterprise Search） |
| Check Grounding API | 验证回答是否有依据 | Vertex AI API（`/groundedGenerationService/checkGrounding`） |
| Vertex AI RAG API | 一站式 RAG 管道（embedding + 索引 + 检索） | Vertex AI RAG Engine |
| Safety Filters | 过滤有害/不当内容 | Gemini Safety Settings |

---

## 四、幻觉度量指标

| 指标 | 定义 | 计算方法 | 值域 |
|------|------|---------|------|
| **Faithfulness** | 回答对上下文的忠实度 | 有上下文支持的 claims / 总 claims | 0-1（越高越好） |
| **Groundedness Score** | 回答中有据可依的比例 | Google Check Grounding API 输出 | 0-1 |
| **Hallucination Rate** | 幻觉率 | 含幻觉的回答数 / 总回答数 | 0-1（越低越好） |
| **Abstention Rate** | 拒答率 | 回答"我不知道"的次数 / 总问题数 | 0-1（适度为好） |

**Faithfulness 和 Hallucination Rate 的区别**：
- Faithfulness 是**细粒度**的（一个回答里多少 claims 有依据）
- Hallucination Rate 是**粗粒度**的（多少回答含幻觉——任何一个 claim 没依据就算）

**Abstention Rate 的平衡**：
- 太低（0%）= 什么都敢答 → 幻觉多
- 太高（50%）= 什么都说不知道 → 没用
- 理想：5-15%（只在真正不确定时拒答）

---

## 五、存储视角加餐 ⭐

### 5.1 Grounding 的存储架构

```
┌─────────────────────────────────────────┐
│             用户请求                      │
└──────────────┬──────────────────────────┘
               │
       ┌───────▼───────┐
       │   Router      │  判断走哪种 Grounding
       └───┬───┬───┬───┘
           │   │   │
    ┌──────▼┐ ┌▼───▼──┐  ┌──────────┐
    │ RAG   │ │Google │  │ Tool Use │
    │       │ │Search │  │ (API)    │
    └───┬───┘ └───┬───┘  └────┬─────┘
        │         │           │
┌───────▼─────────▼───────────▼──────────┐
│              存储层                      │
├─────────────────────────────────────────┤
│ 向量数据库  │ 文档存储    │  API 缓存    │
│ (pgvector/ │ (S3/GCS    │  (Redis/     │
│  Pinecone) │  原始文档)  │   Memcached) │
│ ~600 GB    │ ~几十 GB    │  ~几 GB      │
└─────────────────────────────────────────┘
```

### 5.2 知识库更新与存储

| 更新模式 | 频率 | 存储操作 | 适用 |
|---------|------|---------|------|
| 全量重建 | 每周/每月 | 删旧索引 + 重新 embedding + 构建新索引 | 数据量小（<100 万文档） |
| 增量更新 | 实时/每日 | 新文档 embedding → 增量插入索引 | 数据量大、更新频繁 |
| 版本化 | 按发布周期 | 维护多版本索引（v1/v2/v3），蓝绿切换 | 需要回滚能力 |

### 5.3 Citation 存储

为了让回答可追溯，需要存储 citation 信息：

```json
{
  "answer": "FSx Lustre PERSISTENT_2 支持 125/250/500/1000 MB/s/TiB...",
  "citations": [
    {
      "claim": "PERSISTENT_2 支持 125/250/500/1000 MB/s/TiB",
      "source_url": "https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance.html",
      "source_chunk_id": "chunk_123",
      "confidence": 0.95
    }
  ],
  "grounding_score": 0.92,
  "timestamp": "2026-11-15T03:00:00Z"
}
```

每次交互的 citation 记录 → BigQuery/Athena → 做质量趋势分析。

---

## 六、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| 搜索增强 Grounding | **Google Search Grounding**（Gemini 内置） | Bedrock Agent + **Web Search Connector** |
| 私有数据 RAG | **Vertex AI Search**, Vertex AI RAG API | **Bedrock Knowledge Bases**（自动 RAG 管道） |
| Grounding 验证 | **Check Grounding API** | 无直接对应（需自建 claim verification） |
| 向量搜索 | Vertex AI Vector Search | OpenSearch kNN |
| Tool Use / Function Calling | Gemini Function Calling | Bedrock Agent Action Groups |
| Safety Filter | Gemini Safety Settings | Bedrock Guardrails |
| 文档理解 | Document AI + Vertex AI Search | Textract + Bedrock Knowledge Bases |

---

## 七、面试话术

### Q: LLM 幻觉是什么？你怎么控制？

> **答题模板**：
> 
> LLM 幻觉分两种：**Intrinsic**（与给定上下文矛盾的错误内容）和 **Extrinsic**（无法从上下文验证的内容）。根因有四个：训练数据噪声、知识截止、过度自信（模型不会说"我不知道"）、概率采样的随机性。
> 
> 我用**四层防御**控制幻觉：
> 
> **第一层 Prompt**：System Prompt 里明确"只基于提供的文档回答，不确定时说'我不确定'"。
> 
> **第二层 解码参数**：Temperature 降到 0.0-0.3，减少随机性。对事实性要求高的场景甚至用 greedy decoding（temperature=0）。
> 
> **第三层 后处理验证**：Claim Extraction（从回答提取断言）→ Verification（用知识库/搜索验证每条断言）→ Citation（给每条断言标来源）。不能验证的断言删除或标记"待验证"。
> 
> **第四层 UI**：显示 citation 链接，让用户能点击验证。标注"AI 生成内容"。
> 
> 在 GCP 上，Gemini 的 **Google Search Grounding** 是最便捷的方案——设置 `MODE_DYNAMIC`，模型不确定时自动触发 Google 搜索，返回带 citation 的回答。**Check Grounding API** 可以事后验证回答的 groundedness score。

### Q: Google Search Grounding 和 RAG 怎么选？

> **答题模板**：
> 
> 核心区别是**知识来源**：Google Search Grounding 搜的是整个公开互联网，RAG 搜的是你的私有知识库。
> 
> **用 Google Search Grounding**：查询公开信息（竞品分析、行业趋势、最新新闻）、需要极致时效性（实时搜索）、不涉及私有数据。
> 
> **用 RAG**：回答基于企业私有文档（内部 Wiki/技术文档/客户数据）、需要完全控制知识库内容和质量、有合规要求不能让数据出组织。
> 
> **两者结合**：先用 RAG 搜私有知识库 → 如果 retrieval confidence 低 → 回退到 Google Search Grounding 搜公开信息。这在 Vertex AI 里可以通过 Agent Builder 编排实现。
> 
> 从**存储角度**看，RAG 需要维护向量数据库（1 亿文档约 600-800 GB）和原始文档存储（GCS/S3），Google Search Grounding 没有额外存储需求（Google 负责索引）。

---

*下一篇：[08-responsible-ai.md](08-responsible-ai.md) — Responsible AI / AI Safety*
