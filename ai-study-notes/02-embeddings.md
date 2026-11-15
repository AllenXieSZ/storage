# 02 - Embeddings（向量嵌入）

## 一、什么是 Embedding

Embedding（向量嵌入）是把**离散的高维对象**（文字、图片、音频、用户行为……）映射到**连续的低维向量空间**的技术。映射后的向量有一个关键性质：**语义相近的对象，在向量空间里距离近。**

```
"国王" → [0.23, -0.45, 0.87, 0.12, ...]    (1536 维)
"皇帝" → [0.25, -0.43, 0.85, 0.14, ...]    (距离很近，语义相似)
"苹果" → [0.91, 0.33, -0.12, 0.76, ...]    (距离很远，语义不同)
```

### 为什么需要 Embedding

| 问题 | 不用 Embedding | 用了 Embedding |
|------|---------------|----------------|
| 语义理解 | "好吃"和"美味"被当成完全不同的词 | 两者向量接近，知道它们是近义词 |
| 跨模态搜索 | 只能精确匹配关键词 | 图片和文字在同一空间，可以搜"一只猫"返回猫图 |
| 推荐系统 | 基于规则/协同过滤 | 用户和物品在同一向量空间，距离近 = 可能感兴趣 |
| 聚类分析 | 人工定义特征 | 向量自带语义，K-Means 直接聚类 |

### Embedding 的产生过程

对于文本 Embedding，通常用预训练好的 Encoder 模型（如 BERT、text-embedding-3-large）处理输入文本，取最后一层的 [CLS] token 输出或所有 token 输出的均值池化（mean pooling），就得到了一个固定长度的向量。

```python
# 使用 OpenAI 的 Embedding API
import openai

response = openai.embeddings.create(
    model="text-embedding-3-large",
    input="如何优化数据库查询性能？"
)
vector = response.data[0].embedding  # 3072 维的浮点数列表
```

---

## 二、维度

Embedding 向量的维度决定了**表达力**和**成本**的平衡：

| 模型 | 维度 | 特点 |
|------|------|------|
| text-embedding-3-small (OpenAI) | 1536 | 性价比高，多数场景够用 |
| text-embedding-3-large (OpenAI) | 3072 | 最高精度，成本翻倍 |
| text-embedding-004 (Google) | 768 | Vertex AI 默认，成本低 |
| Cohere embed-v3 | 1024 | 多语言强 |
| BGE-large-en-v1.5 | 1024 | 开源，英文强 |
| BAAI/bge-m3 | 1024 | 开源，多语言最优之一 |
| Amazon Titan Text Embeddings V2 | 1024 | AWS Bedrock 内置 |

**维度越高**：
- ✅ 向量空间表达力更强，能区分更细微的语义差别
- ❌ 每个向量占的存储空间更大（3072 维 × 4 bytes/float32 = 12.3 KB/向量）
- ❌ 相似度计算更慢（点积/余弦都是 O(d)）
- ❌ 索引构建和查询更慢更耗内存

**实际选型**：768-1536 维是当前主流甜蜜点。除非对检索精度有极致要求，否则 1536 已经足够。

---

## 三、距离度量

有了向量，怎么判断两个向量"接不接近"？三种主流度量：

### 3.1 Cosine Similarity（余弦相似度）

```
cos(A, B) = (A · B) / (||A|| × ||B||)
```

只看**方向**，不管**长度**。值域 [-1, 1]，1 表示方向完全相同，0 表示正交，-1 表示完全相反。

**最常用**，因为 Embedding 模型通常已经归一化（向量长度=1），此时方向就是唯一的语义信息。

### 3.2 Euclidean Distance（欧氏距离）

```
d(A, B) = √(Σ(aᵢ - bᵢ)²)
```

看**绝对位置差异**。值域 [0, +∞)，越小越相似。

对向量长度敏感——如果两个语义相似的向量因为输入长度不同导致模长不一，欧氏距离可能不准。

### 3.3 Dot Product（点积/内积）

```
A · B = Σ(aᵢ × bᵢ)
```

同时考虑**方向和长度**。值域 (-∞, +∞)，越大越相似。

**当向量归一化后（||A||=||B||=1），点积 = 余弦相似度。** 很多系统用归一化向量 + 点积来替代余弦计算（更快，少除一次法）。

### 度量选型指南

| 度量 | 适用场景 | 注意点 |
|------|---------|--------|
| Cosine | 文本语义搜索（默认选这个） | 对长度不敏感，关注方向 |
| Euclidean | 图像特征比较、需要考虑绝对距离 | 需先归一化，否则受模长影响 |
| Dot Product | 推荐系统（模长代表"重要性"） | 向量不归一化时有意义 |

---

## 四、ANN 索引（近似最近邻搜索）

当你有 1 亿个向量时，暴力遍历找最近邻（Brute-Force）太慢（O(N×d)）。ANN（Approximate Nearest Neighbor）用近似算法把查询时间从 O(N) 降到 O(log N) 级别，代价是可能漏掉真正的最近邻（recall < 100%）。

### 4.1 HNSW（Hierarchical Navigable Small World）

**原理**：构建多层图，底层包含所有节点，上层逐渐稀疏。查询时从最高层开始"跳跃"导航，逐层下降，类似跳表（Skip List）。

```
Layer 3: [A] ──────────── [D]           （最稀疏，全局导航）
Layer 2: [A] ── [B] ──── [D] ── [F]    （中间层）
Layer 1: [A]-[B]-[C]-[D]-[E]-[F]-[G]   （最密，所有节点）
Layer 0: 原始向量数据

查询时：Layer 3 找到大致区域 → Layer 2 缩小范围 → Layer 1 精确搜索
```

| 优点 | 缺点 |
|------|------|
| 精度极高（recall >99%） | **全部索引必须放内存**，内存消耗大 |
| 查询速度快（ms 级） | 构建时间长（需要插入每个向量） |
| 支持动态插入/删除 | 1 亿 × 1536 维 ≈ 600 GB 向量 + ~150 GB 图索引 |

### 4.2 IVF（Inverted File Index）

**原理**：先用 K-Means 将向量空间分成 N 个聚类（Voronoi cell），每个向量归入最近的聚类。查询时只搜索最近的 nprobe 个聚类，而非全量。

```
聚类 1: {v₁, v₅, v₈, ...}
聚类 2: {v₂, v₃, v₇, ...}    ← 查询向量落在这里
聚类 3: {v₄, v₆, v₉, ...}    ← 也搜这个（nprobe=2）
...
聚类 N: {...}

只搜 nprobe 个聚类 << 全部 N 个聚类
```

| 优点 | 缺点 |
|------|------|
| **可以落盘 SSD**（向量不用全放内存） | 精度略低于 HNSW |
| 内存占用低（只需聚类中心在内存） | 需要预构建聚类（K-Means） |
| 适合超大规模（十亿+） | nprobe 和 N 需要调参 |

**IVF-PQ**：IVF + Product Quantization（PQ），把向量分段量化压缩，进一步减少内存/磁盘占用，但精度有损。

### 4.3 ScaNN（Scalable Nearest Neighbors by Google）

Google 开源的 ANN 库，核心创新是 **Anisotropic Vector Quantization**（各向异性向量量化）——传统量化最小化重建误差，ScaNN 最小化的是**内积方向的误差**，更适合最大内积搜索场景。

架构：分区（类似 IVF）→ 量化（各向异性 VQ）→ Reranking。

**Vertex AI Vector Search 底层就用了 ScaNN 技术。**

### 索引对比

| 特性 | HNSW | IVF / IVF-PQ | ScaNN |
|------|------|-------------|-------|
| 精度 | ★★★★★ | ★★★★ | ★★★★★ |
| 查询速度 | ★★★★★ | ★★★★ | ★★★★★ |
| 内存占用 | ★★（全内存） | ★★★★（可落盘） | ★★★★ |
| 可扩展性 | ★★★ | ★★★★★ | ★★★★ |
| 动态更新 | ★★★★★ | ★★（需重建） | ★★★ |
| 适合规模 | 千万级 | 十亿+ | 十亿+ |

---

## 五、向量数据库

向量数据库 = 向量索引 + 元数据过滤 + 持久化存储 + CRUD API + 分布式能力。

### 5.1 主流向量数据库

| 数据库 | 类型 | 底层索引 | 特点 |
|--------|------|---------|------|
| **Pinecone** | 全托管 SaaS | 自研 | 最省心，serverless 模式按查询计费 |
| **Weaviate** | 开源 + 托管 | HNSW | 内置向量化（直接传文本自动 embed）、GraphQL API |
| **Milvus** | 开源 + 托管 (Zilliz) | IVF/HNSW/DiskANN | 最灵活，支持十亿级，GPU 加速索引构建 |
| **Chroma** | 开源 | HNSW (hnswlib) | 最轻量，适合本地开发/小规模 |
| **pgvector** | PostgreSQL 扩展 | IVF-Flat / HNSW | 已有 PG 的直接加扩展，不需要独立向量数据库 |
| **Qdrant** | 开源 + 托管 | HNSW | Rust 写的，性能强，支持复杂过滤 |

### 5.2 选型决策

```
你已有 PostgreSQL？
├── 是 → pgvector（最低运维成本，中小规模够用）
└── 否 → 数据量多大？
    ├── <100 万向量 → Chroma（本地开发）/ Pinecone Serverless（生产）
    ├── 100 万~1 亿 → Weaviate / Qdrant / Pinecone
    └── >1 亿 → Milvus（GPU 加速 + IVF-PQ 落盘）
```

---

## 六、存储视角加餐 ⭐

### 6.1 向量存储成本计算

以 1 亿文档为例：

```
文档数量：100,000,000（1 亿）
Embedding 维度：1536
精度：float32（4 bytes/维度）

每个向量大小 = 1536 × 4 bytes = 6,144 bytes ≈ 6 KB
总向量数据 = 100M × 6 KB = 600 GB（纯向量）

加上元数据（文档 ID、标题、标签等，假设每条 500 bytes）：
元数据总量 = 100M × 500 bytes = 50 GB

加上 ANN 索引（HNSW 图结构，约向量数据的 20-30%）：
索引开销 ≈ 600 GB × 0.25 = 150 GB

总计 ≈ 600 + 50 + 150 = 800 GB
```

### 6.2 HNSW vs IVF 的存储对比

| 维度 | HNSW | IVF-PQ |
|------|------|--------|
| 向量存储位置 | **全内存** | **可落盘 SSD** |
| 1 亿 × 1536d 需要 | ~750 GB 内存 | ~100 GB 内存 + ~200 GB SSD |
| 机器成本（AWS） | r6g.16xlarge × 2（~512 GB RAM 起） | r6g.4xlarge + gp3 SSD |
| 月成本估算 | ~$6,000-8,000 | ~$1,500-2,000 |
| 精度 (recall@10) | >99% | 95-98%（调参后） |

### 6.3 索引重建时间

| 数据规模 | HNSW 构建 | IVF-PQ 训练 |
|----------|----------|-------------|
| 1M vectors | ~10 min | ~5 min |
| 10M vectors | ~2 hours | ~30 min |
| 100M vectors | ~20 hours | ~3 hours |
| 1B vectors | 不现实（内存放不下） | ~1 天（GPU 加速） |

**存储架构师关注点**：
- HNSW 全内存 → 需要大内存实例，成本高但查询快
- IVF-PQ 可落盘 → 可以用 EBS gp3 / 本地 NVMe（i3/i4 系列），成本低一个数量级
- 向量数据备份 → dump 到 S3/GCS，定期快照
- 高可用 → 主从复制（Milvus 支持），或者 Pinecone 全托管

### 6.4 float32 vs float16 vs int8 量化向量

| 精度 | 每维字节 | 1 亿向量 (1536d) 总大小 | recall 损失 |
|------|---------|----------------------|-------------|
| float32 | 4 | 600 GB | 0%（基准） |
| float16 | 2 | 300 GB | <0.5% |
| int8 | 1 | 150 GB | 1-3% |
| binary (1-bit) | 0.125 | 18.75 GB | 5-10%+ |

**Matryoshka Representation Learning（MRL）**：OpenAI 的 text-embedding-3 系列支持"截断维度"——3072 维的向量可以只取前 1024 维或 256 维使用，精度梯度下降，存储线性减少。这是客户端决定的，不需要重新 embed。

---

## 七、GCP / AWS 服务对照

| 能力 | GCP 服务 | AWS 服务 |
|------|---------|---------|
| Embedding API | **Vertex AI Embeddings API**（text-embedding-004, multimodalembedding） | **Bedrock Embeddings**（Titan Text Embeddings V2, Cohere Embed） |
| 托管向量搜索 | **Vertex AI Vector Search**（原 Matching Engine，底层 ScaNN） | **OpenSearch Service**（kNN plugin，HNSW/IVF） |
| 关系型 + 向量 | **AlloyDB** + pgvector / **Cloud SQL** + pgvector | **Aurora PostgreSQL** + pgvector / **RDS PostgreSQL** + pgvector |
| 图数据库 + 向量 | — | **Neptune Analytics**（图+向量混合查询） |
| Serverless 向量 | Vector Search（自动扩缩） | OpenSearch Serverless (vector engine) |
| 开源托管 | GKE 上自建 Milvus/Weaviate | EKS 上自建 / **Amazon MemoryDB**（Redis 兼容 + 向量） |

**GCP Vertex AI Vector Search 特点**：
- 底层 ScaNN 技术，Google 内部用于 YouTube 推荐、Google Search
- 支持 streaming update（增量更新索引，不用全量重建）
- 支持 filter 过滤（结构化元数据 + 向量搜索混合）
- 部署时选 machine type 和 replica count，有 autoscaling

**AWS OpenSearch kNN 特点**：
- 基于 FAISS 和 nmslib
- 支持 HNSW（精度高）和 IVF（大规模）
- 与 OpenSearch 的全文搜索结合 = **混合搜索**（BM25 + kNN 融合排序）
- Serverless 模式按 OCU 计费，不用管集群

---

## 八、面试话术

### Q: 你的 RAG 系统用了什么 Embedding 模型？怎么选的？向量数据库怎么选的？

> **答题模板**：
> 
> Embedding 模型选型我会从三个维度评估：**精度、成本、延迟**。
> 
> 精度层面，看 MTEB（Massive Text Embedding Benchmark）排行榜，对比模型在 Retrieval 子任务上的 nDCG@10。当前 top-tier 的有 OpenAI text-embedding-3-large（3072 维）、Cohere embed-v3（1024 维）。如果内网部署不想调 API，开源的 BGE-M3 或 GTE-large 也很强。
> 
> 成本层面，维度 × 文档数 = 存储成本。1536 维是甜蜜点——1 亿文档约 600 GB 纯向量。3072 维翻倍，但可以用 MRL 截断到 1024 维权衡。
> 
> 向量数据库层面，决策树是：
> - 已有 PostgreSQL → pgvector 扩展，零额外运维
> - 1 亿以下 → Pinecone Serverless（全托管）或 Qdrant
> - 1 亿以上 → Milvus + IVF-PQ（可落盘 SSD，省内存）
> 
> 在 GCP 上，一站式方案是 Vertex AI Embeddings API + Vertex AI Vector Search（底层 ScaNN）。AWS 上是 Bedrock Embeddings + OpenSearch kNN。
> 
> 从**存储角度**看，关键决策是 HNSW 全内存 vs IVF 落盘：HNSW 精度高但 1 亿向量需要 ~750 GB 内存（r6g.16xlarge × 2，月成本 $6K+），IVF-PQ 可以落到 gp3 SSD，月成本降到 $1.5K，recall 从 99% 降到 95-98%。多数生产系统选 IVF-PQ 够用。

### Q: Embedding 维度怎么选？高维度一定好吗？

> **答题模板**：
> 
> 不一定。维度的选择是**表达力 vs 成本**的 trade-off。
> 
> 高维度（3072d）在语义区分度上确实更好，但成本线性增长：存储翻倍、索引构建翻倍、查询延迟增加。对多数 RAG/搜索场景，768-1536 维已经足够——MTEB 上 1536 维和 3072 维的差距通常 <2%。
> 
> 实际建议：先用 1536 维跑基准，如果检索 recall 不满足再换 3072 维。如果用 OpenAI 的 text-embedding-3-large，可以用 MRL（Matryoshka Representation Learning）生成 3072 维向量后截断到 1024/512 维使用，一次 embed 多种规格。
> 
> 从**存储成本**看：1 亿文档 × 1536d × float32 = 600 GB，换 3072d = 1.2 TB。如果索引用 HNSW 全内存，这个差距直接翻译成内存需求和机器成本的翻倍。

---

*下一篇：[03-prompt-engineering.md](03-prompt-engineering.md) — Prompt Engineering*
