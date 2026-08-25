# GCP Vertex AI ↔ AWS 服务对照速查表

> GCP Vertex AI 与 AWS AI 服务的对照学习笔记，按能力维度整理。
> 用途：双云 AI 服务对照学习。服务更新快，具体特性以各厂商官方最新文档为准。

## 一、平台与模型服务

| 能力 | GCP | AWS |
|---|---|---|
| 统一 ML 平台 | **Vertex AI** | **SageMaker** + **Bedrock**（生成式） |
| 企业级托管大模型 API 入口 | **Vertex AI**（IAM/VPC-SC/合规） | **Amazon Bedrock** |
| 个人快速试玩模型 | **Google AI Studio**（API Key） | 各厂商自己的 console（如 Anthropic Console） |
| 模型市场/仓库 | **Model Garden**（一方Gemini+三方Claude/Llama+开源Gemma） | **SageMaker JumpStart**（部署开源）+ **Bedrock**（API调托管） |
| Notebook 环境 | Vertex AI Workbench | SageMaker Studio / Notebook |

## 二、模型家族（能力分档）

| 档位 | GCP Gemini | AWS Bedrock |
|---|---|---|
| 旗舰/最强 | Gemini **Pro** | Claude **Opus** / Amazon Nova Premier |
| 均衡/主力 | Gemini **Flash** | Claude **Sonnet** / Nova Pro |
| 快省/最轻 | Gemini **Flash-Lite** | Claude **Haiku** / Nova Micro-Lite |
| 备注 | Gemini 只在 Vertex AI，原生多模态+百万级长上下文 | Bedrock 多厂商（Anthropic/Meta/Amazon/Mistral），无 Gemini |

## 三、推理端点 / 流量切分

| 维度 | Vertex AI | SageMaker |
|---|---|---|
| 在线端点 | Endpoint（全托管，不选GCE/GKE） | Real-time Inference Endpoint |
| 多模型/AB分流 | 多 DeployedModel + trafficSplit(%) | Production Variants + InitialVariantWeight |
| 金丝雀发布 | 手动调 trafficSplit | Deployment Guardrails（Canary/Linear+自动回滚） |
| 海量模型省成本 | —（较弱） | Multi-Model Endpoint (MME) |
| autoscaling | min/max replica | Application Auto Scaling |
| 批量推理 | Batch Prediction | Batch Transform |

## 四、模型监控

| Vertex AI Model Monitoring | AWS SageMaker Model Monitor |
|---|---|
| Training-serving skew / data drift（无label） | **Data Quality Monitoring**（无需label） |
| 准确率退化 | **Model Quality Monitoring**（需接ground-truth label） |
| Feature attribution drift | **Feature Attribution Drift**（基于 Clarify） |
| —（不单列） | **Bias Drift**（Clarify） |
| 注：latency/QPS 属服务层监控(Cloud Monitoring / CloudWatch)，非 Model Monitoring |

## 五、RAG / 向量检索 / Embedding

| 环节 | GCP | AWS |
|---|---|---|
| 托管一站式 RAG | Vertex AI Search / RAG Engine | **Bedrock Knowledge Bases** |
| 向量检索(ANN) | **Vertex AI Vector Search**（原Matching Engine，底层ScaNN，毫秒级） | OpenSearch k-NN(HNSW,毫秒级) / Aurora pgvector / **S3 Vectors**(亚秒级/百毫秒,超低成本) |
| embedding 模型 | Vertex text-embedding / multimodal embedding | Titan Text/Multimodal Embeddings / Cohere Embed |
| ⚠️延迟对标 | Vector Search=毫秒级 ↔ OpenSearch；S3 Vectors=亚秒级(用延迟换成本) |

## 六、微调

| GCP | AWS Bedrock |
|---|---|
| Gemini 托管 **SFT**（底层 LoRA 类 PEFT，闭源做不了全参数微调） | **Custom Models**：Fine-tuning（监督微调）+ Continued Pre-training |
| 都是托管式，上传数据、不碰底层权重 | 同 |

## 七、Grounding / Agent

| 概念 | GCP | AWS |
|---|---|---|
| 用自己数据接地(RAG) | Vertex AI Search / Vector Search | Bedrock Knowledge Bases / Kendra |
| ⭐用公开搜索接地 | **Grounding with Google Search**（原生独有） | ❌ 无对等（靠 Kendra Web Crawler / 外接 search API） |
| Agent 框架 | Vertex AI **Agent Builder** / ADK | **Bedrock Agents** / AgentCore |
| 工具调用 | Gemini function calling / Extensions | Bedrock Agents **Action Groups**（Lambda+OpenAPI） |
| 命名差异 | "Agent Builder"=造Agent的平台 | "Bedrock Agents"=服务下的资源(复数) |

## 八、安全 / 责任 AI

| 责任机制 | GCP Vertex AI | AWS |
|---|---|---|
| 内容过滤 | **Safety Filters**（4类概率打分+阈值） | **Bedrock Guardrails**（拒答主题/有害内容/PII/幻觉检测） |
| 数据隐私 | 不拿数据训练 + VPC-SC + CMEK + 数据驻留 | Bedrock 同承诺 + PrivateLink + KMS |
| 水印溯源 | **SynthID**（图/音/视频/文本隐形水印） | ❌ 无自家对等 |
| 可解释性 | Explainable AI | SageMaker Clarify |
| PII 检测 | Cloud DLP | Guardrails PII / Comprehend |
| 注："Guardrails"是AWS产品名；Vertex 官方叫 safety filters |

## 九、上下文缓存

| GCP | AWS |
|---|---|
| **Vertex AI Context Caching**（显式建cache对象+TTL+cacheID引用） | **Bedrock Prompt Caching**（prompt里标记cache断点） |
| 都缓存固定前缀的 **KV Cache**(注意力键值,非tokenizer/权重)，命中打折+降TTFT。前缀token必须逐token一致才命中(prefix matching) |

## 十、训练芯片 / 基础设施

| 能力 | GCP | AWS |
|---|---|---|
| 自研训练芯片(ASIC) | **TPU**（Systolic Array脉动阵列） | **Trainium**（Trn） |
| 自研推理芯片 | TPU/更小档 | **Inferentia**（Inf） |
| 芯片间高速互联 | **ICI**（Inter-Chip Interconnect） | **NeuronLink** |
| 大规模组网 | TPU **Pod + Slice**（2D/3D Torus拓扑） | **UltraCluster / UltraServer**（EFA+NeuronLink） |
| 通用 GPU | NVIDIA A100/H100（GCP也卖） | NVIDIA P4/P5（AWS也卖） |
| 编译器/SDK | XLA + JAX/TensorFlow | Neuron SDK |
| 何时用自研芯片 | 大规模规整训练+JAX/TF，能效性价比高，锁GCP | 同理，锁AWS，靠Neuron生态 |
| GPU优势 | 通用灵活+CUDA+PyTorch+跨云可移植 | 同 |

---

## 十一、分布式训练

三种并行策略本身通用（数据并行 / 张量并行 / 流水线并行 / 3D 组合），差异在托管服务与通信加速组件：

| 能力 | GCP | AWS |
|---|---|---|
| 托管分布式训练 | Vertex AI Training | SageMaker Training（SMDDP / SMP） |
| 数据并行加速 | **Reduction Server**（加速 all-reduce） | SageMaker Distributed Data Parallel (SMDDP) |
| 模型并行库 | JAX GSPMD / Pax / DeepSpeed | SageMaker Model Parallel (SMP) / DeepSpeed |
| GPU 集群高速网 | **GPUDirect-TCPX** | **EFA** |
| 自研芯片路线 | TPU Pod | Trainium UltraCluster |

## 十二、GPU 机型对照

| GPU | GCP | AWS |
|---|---|---|
| A100 | **A2** | P4d / P4de |
| H100 | **A3**（当前训练主力，配 GPUDirect-TCPX） | **P5** |
| H200 | A3 变体 | P5e / P5en |
| Blackwell B200/GB200 | A4 / A4X | P6（P6-B200） |
| L4（推理性价比） | **G2** | G6 |

- GCP 加速机型命名：A 系列（A=Accelerator），A2→A3→A4 越新越强；G2 是推理向（L4）。
- 训练旗舰 A3(H100)↔P5；上一代 A2(A100)↔P4d；推理 G2(L4)↔G6。

## 核心记忆锚点

- **企业托管入口**：Vertex AI ↔ Bedrock
- **向量检索**：Vector Search(毫秒/ScaNN) ↔ OpenSearch(毫秒) / S3 Vectors(亚秒省钱)
- **托管RAG**：Vertex AI Search ↔ Bedrock Knowledge Bases
- **Agent**：Agent Builder ↔ Bedrock Agents
- **安全**：Safety Filters ↔ Bedrock Guardrails；SynthID 是 Google 独有
- **接地独门**：Grounding with Google Search（AWS 无对等）
- **自研芯片**：TPU(ICI/Torus/Pod-Slice) ↔ Trainium(NeuronLink/UltraCluster)
- **GPU机型**：A2(A100)↔P4d、A3(H100)↔P5、G2(L4)↔G6
- **分布式训练**：Reduction Server↔SMDDP、GPUDirect-TCPX↔EFA
