# 03 - Prompt Engineering（提示词工程）

## 一、什么是 Prompt Engineering

Prompt Engineering 是**通过设计输入提示词（prompt）来引导 LLM 产生期望输出**的技术。它不修改模型权重，完全在推理阶段操作——改变的是"问法"而非"模型"。

为什么重要：同一个模型，不同的 prompt 可能得到天差地别的结果。好的 prompt 能让现有模型发挥出接近甚至超过微调的效果。

---

## 二、核心技术

### 2.1 Zero-shot Prompting

不给任何示例，直接让模型完成任务。依赖模型在预训练中学到的通用能力。

```
Prompt:
将以下文本分类为"正面"或"负面"：
"这家餐厅的菜品太好吃了，服务也非常周到，强烈推荐！"

Output:
正面
```

**适用场景**：任务简单、模型能力强（Gemini/GPT-4 级别）。对于复杂或领域特定的任务，zero-shot 效果可能不稳定。

### 2.2 Few-shot Prompting

在 prompt 里提供几个**输入-输出示例**，让模型"学会"任务模式。

```
Prompt:
将文本分类为"正面"、"负面"或"中性"。

例子：
文本："今天天气很好，心情不错" → 正面
文本："产品质量太差了，退货！" → 负面
文本："已收到，包装完好" → 中性

现在分类：
文本："菜品一般，但服务很好" →

Output:
中性
```

**关键点**：
- 3-5 个示例通常就够了（再多改善有限，还浪费 token）
- 示例要**覆盖所有类别**，且分布均衡
- 示例要**有代表性**，不能只给简单 case
- 示例顺序会影响结果（**position bias**，见后面"Lost in the Middle"）

### 2.3 Chain-of-Thought（CoT，思维链）

让模型**先展示推理过程，再给出答案**。通过在 prompt 中加入"Let's think step by step"或提供带推理过程的示例来激活。

```
Prompt（Without CoT）:
一个水池第一天有 5 升水，每天增加 3 升，第 7 天有多少升？

Output: 23 升   ← 可能直接算错

Prompt（With CoT）:
一个水池第一天有 5 升水，每天增加 3 升，第 7 天有多少升？
请一步一步思考。

Output:
第 1 天：5 升
第 2 天：5 + 3 = 8 升
第 3 天：8 + 3 = 11 升
第 4 天：11 + 3 = 14 升
第 5 天：14 + 3 = 17 升
第 6 天：17 + 3 = 20 升
第 7 天：20 + 3 = 23 升
答案：23 升
```

**为什么有效**：
1. 把复杂问题拆成小步骤，每步出错概率低
2. 中间步骤可见，方便检查和调试
3. 对数学、逻辑推理、代码调试类任务提升显著

**CoT 变体**：
| 变体 | 说明 |
|------|------|
| Zero-shot CoT | 直接加 "Let's think step by step"，无需示例 |
| Few-shot CoT | 提供带推理过程的示例 |
| Self-Consistency | 多次采样 CoT 答案，取多数票（投票） |
| Tree-of-Thought (ToT) | 每步生成多个分支，搜索最优路径 |

### 2.4 System Prompt / Output Formatting

**System Prompt** 设定模型的角色、行为规范和约束条件。在 API 调用中作为 `system` 消息传入。

```python
messages = [
    {
        "role": "system",
        "content": """你是一个 AWS 存储架构顾问，专注于 FSx 和 S3。
规则：
1. 回答必须基于 AWS 官方文档
2. 不确定的内容标注"待验证"
3. 回答格式为 JSON
4. 所有成本单位用美元/月"""
    },
    {
        "role": "user",
        "content": "比较 FSx Lustre 和 EFS 的吞吐性能"
    }
]
```

**JSON Mode**：强制模型输出合法 JSON，避免混入自然语言。

```python
# OpenAI
response = client.chat.completions.create(
    model="gpt-4o",
    response_format={"type": "json_object"},
    messages=[...]
)

# Gemini (Vertex AI)
generation_config = GenerationConfig(
    response_mime_type="application/json",
    response_schema={"type": "object", "properties": {...}}
)
```

### 2.5 Prompt Chaining（提示链）

把复杂任务拆成多个步骤，每步用一个独立 prompt，**前一步的输出作为下一步的输入**。

```
Step 1: 从用户问题中提取关键实体和意图
       输入 → "我想知道 FSx Lustre 在 us-east-2 的性能和成本"
       输出 → {service: "FSx Lustre", region: "us-east-2", aspects: ["performance", "cost"]}

Step 2: 根据提取的实体，查询知识库
       输入 → Step 1 的 JSON
       输出 → 相关文档片段

Step 3: 基于文档片段，生成结构化回答
       输入 → Step 2 的文档 + 原始问题
       输出 → 最终回答
```

**优势**：
- 每步 prompt 简单、可控，出错范围小
- 中间结果可检查/缓存
- 不同步骤可以用不同模型（简单步骤用便宜的 Flash，复杂步骤用 Pro）

### 2.6 ReAct（Reasoning + Acting）

ReAct 是让 LLM **交替进行推理（Thought）和行动（Action）**的框架，是 AI Agent 的技术基础。

```
用户：今天深圳的天气适合户外跑步吗？

Thought 1: 我需要查一下深圳今天的天气数据。
Action 1: search_weather(location="深圳", date="today")
Observation 1: 温度 28°C，湿度 75%，多云，PM2.5 = 35

Thought 2: 28°C 偏热但可以接受，湿度 75% 偏高会影响散热，
           空气质量良好（PM2.5 < 50）。需要评估综合条件。
Action 2: 无需更多工具调用

Thought 3: 综合判断——可以跑但要注意补水和防晒。
Final Answer: 今天深圳 28°C、湿度 75%，多云。可以户外跑步，
             但建议选择清晨或傍晚，注意补水，湿度较高会影响散热。
```

**ReAct 的关键**：
- 模型不只是"想"，还能"做"（调用工具/API）
- Thought 链保证推理可追踪
- 观察结果反馈到下一轮推理
- GCP 的 **Vertex AI Agent Builder** 和 AWS 的 **Bedrock Agent** 底层都是 ReAct 范式

### 2.7 Lost in the Middle 问题

2023 年 Stanford 论文发现：**当相关信息放在长上下文的中间位置时，LLM 检索/利用这些信息的能力显著下降。**

```
性能
  │
  │  ██                              ██
  │  ████                          ████
  │  ██████                      ██████
  │  ████████                  ████████
  │  ██████████              ██████████
  │  ████████████          ████████████
  │  ██████████████      ██████████████
  │  ████████████████  ████████████████
  └──────────────────────────────────────
     开头        中间位置        结尾
     
     "U 形曲线"——开头和结尾的信息利用率高，中间的被忽略
```

**实际影响**：
- RAG 系统返回 10 个文档片段，如果最相关的片段排在中间（第 5-7 个），模型可能忽略它
- 长上下文模型（128K/1M tokens）不是万能的，中间的信息仍可能"丢失"

**应对策略**：
1. **把最相关的信息放在 prompt 开头或结尾**（不要放中间）
2. RAG 的 reranking：检索后重排，把最重要的放在最前面
3. 控制 context 长度：宁可少放几个片段，不要堆砌

### 2.8 长上下文 vs RAG 的取舍

| 维度 | 长上下文（直接塞 prompt） | RAG（检索增强生成） |
|------|--------------------------|-------------------|
| 成本 | token 多 → 贵（128K tokens 的输入费可观） | 只塞相关片段，token 少 |
| 延迟 | 长 prompt → 推理慢 | 短 prompt → 推理快 |
| 精度 | 受 Lost in the Middle 影响 | 检索质量决定上限 |
| 实时性 | prompt 里的信息是静态的 | 向量库可以实时更新 |
| 适用场景 | 文档少（<100 页）、一次性分析 | 文档多（知识库级别）、持续查询 |

**决策建议**：
- 文档 < 50 页且是一次性分析 → 直接塞长上下文
- 文档 > 50 页或需要持续查询 → 上 RAG
- 两者可以结合：RAG 检索 Top-K → 塞入长上下文 → 让模型在上下文里推理

---

## 三、存储视角加餐 ⭐

Prompt Engineering 本身是计算侧的技术，但从存储角度有两个关注点：

### 3.1 Prompt 模板管理

生产系统的 prompt 不是写死的字符串，而是**需要版本管理的资产**：

| 管理需求 | 存储方案 |
|---------|---------|
| 版本控制 | Git 仓库（Prompt as Code），每次修改可追溯 |
| 动态加载 | 存在 GCS/S3，应用启动时拉取，不用重新部署 |
| A/B 测试 | 不同版本的 prompt 存在不同 key，配合 feature flag 切换 |
| 审计合规 | 每次 prompt 修改记录到 BigQuery/CloudWatch Logs |

### 3.2 RAG 的存储架构

RAG 是 Prompt Engineering 的延伸（把外部知识塞进 prompt），它的存储需求在 02-embeddings 里详细讲了：
- 向量存储：600 GB~1.2 TB 级别（1 亿文档）
- 原始文档存储：S3/GCS
- 索引存储：内存（HNSW）或 SSD（IVF-PQ）

### 3.3 Prompt Caching

长 system prompt 或固定的 few-shot examples 可以**缓存**，避免每次都重新计算 KV Cache：

| 服务 | 缓存机制 | 存储位置 |
|------|---------|---------|
| Anthropic Claude | Prompt Caching（cache_control） | 服务端内存/SSD |
| Google Gemini | Context Caching（cachedContents） | 服务端 |
| OpenAI | 自动 Prefix Caching | 服务端 |

缓存减少了重复 token 的计算成本（通常打 5 折），但不影响客户端存储。

---

## 四、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| LLM API（用 prompt 调用） | **Vertex AI Gemini API**, Model Garden | **Amazon Bedrock** (Claude/Llama/Titan) |
| Agent 编排（ReAct） | **Vertex AI Agent Builder** | **Bedrock Agent** |
| Prompt 管理/版本 | Vertex AI Prompt Gallery（内置模板） | Bedrock Prompt Management |
| RAG（检索增强） | Vertex AI Search, Vector Search | Bedrock Knowledge Bases（自动 RAG 管道） |
| 长上下文 | Gemini 1.5 Pro: 2M tokens | Claude 3.5: 200K tokens |
| JSON Mode | Gemini: `response_mime_type=application/json` | Bedrock: 取决于模型（Claude 支持 tool_use JSON） |
| Grounding（搜索增强） | Google Search Grounding（内置） | Bedrock + Web Search connector |
| Tool Use | Gemini Function Calling | Bedrock Agent Action Groups |

---

## 五、面试话术

### Q: 请解释 Prompt Engineering 的主要技术，以及什么时候应该用 Prompt Engineering vs Fine-tuning vs RAG？

> **答题模板**：
> 
> Prompt Engineering 的核心技术有四个层次：
> 
> 第一层，**基础 prompting**：Zero-shot（直接问）和 Few-shot（给示例）。Few-shot 通过 3-5 个输入输出示例让模型"学会"任务模式。
> 
> 第二层，**推理增强**：Chain-of-Thought（让模型先推理再答，"Let's think step by step"），对数学和逻辑题提升显著。Self-Consistency 在 CoT 基础上多次采样取多数票进一步提升稳定性。
> 
> 第三层，**结构化输出**：System Prompt 设定角色和规范，JSON Mode 强制合法输出，方便下游系统解析。
> 
> 第四层，**Agent 编排**：ReAct 让模型交替推理和调用工具，Prompt Chaining 把复杂任务拆成串联的子任务。
> 
> 关于**三者的选型决策**：
> - **Prompt Engineering 优先**：成本最低、见效最快。如果好的 prompt + few-shot 就能达到要求，不需要动模型。
> - **RAG**：当模型需要外部知识（最新信息、专有文档）时用。本质是在推理时动态注入知识，不改模型。
> - **Fine-tuning**：当 prompt 和 RAG 都搞不定时——比如需要特定风格/格式/领域能力，或者 few-shot 的 token 成本太高（高频调用场景，fine-tune 后可以省掉 few-shot 示例）。
> 
> 在 GCP 上，Vertex AI Gemini API 支持 2M token 长上下文 + Google Search Grounding + Function Calling，基本覆盖前三层。Agent Builder 覆盖第四层。

### Q: 什么是 "Lost in the Middle" 问题？怎么解决？

> **答题模板**：
> 
> "Lost in the Middle" 是 2023 年 Stanford 论文发现的现象：LLM 在处理长上下文时，对**开头和结尾**的信息利用率高，但**中间位置**的信息容易被忽略，形成 U 形性能曲线。
> 
> 这对 RAG 系统的直接影响是：如果检索到 10 个文档片段，最相关的片段如果排在第 5-7 位（中间），模型可能忽略它，导致回答不准。
> 
> **三个解决策略**：
> 1. **排序优化**：把最相关的文档放在 prompt 的开头或结尾，不要放中间。RAG 系统加 reranker（如 Cohere Rerank、BGE-Reranker）重排文档。
> 2. **控制长度**：不要贪多塞文档，Top-3 到 Top-5 通常比 Top-20 效果好。
> 3. **结构化标记**：给每个文档片段加 `[Document 1]`...`[Document N]` 标签 + 编号，帮助模型定位和引用。
> 
> Gemini 1.5 Pro 的 2M token 上下文虽然很长，但仍然存在这个问题——长上下文不等于无损利用所有信息。

---

*下一篇：[04-fine-tuning.md](04-fine-tuning.md) — Fine-tuning（微调）+ 模型剪枝*
