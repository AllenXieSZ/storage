# AI 训练 × 存储：速查总表

> 一页表格概览全部内容。详细展开见各子文档。

## 目录

| # | 文档 | 内容 |
|---|---|---|
| 1 | [README_ZH.md](README_ZH.md) | 7 个核心技术问题（参数规模/注意力机制/位置编码/前向反向/Epoch/NaN梯度/学习率） |
| 2 | [PRETRAIN_7_STAGES_ZH.md](PRETRAIN_7_STAGES_ZH.md) | 预训练完整流程 7 阶段 |
| 3 | [AI_TRAINING_4_IO_PATTERNS_ZH.md](AI_TRAINING_4_IO_PATTERNS_ZH.md) | 4 大训练场景的 IO 模式对比 |

---

## 一、模型架构速查

### 参数规模

| 模型 | 隐藏维度 d | 层数 L | 参数量 | Checkpoint (bf16) | + 优化器 = 完整 Checkpoint |
|---|---|---|---|---|---|
| LLaMA-3 8B | 4096 | 32 | 8B | 16 GB | ~42 GB |
| LLaMA-3 70B | 8192 | 80 | 70B | 140 GB | ~420 GB |
| LLaMA-3 405B | 16384 | 126 | 405B | 810 GB | ~2.4 TB |
| DeepSeek-V3 (MoE) | 7168 | 61 | 671B(激活37B) | ~1.3 TB | — |

> 公式：总参数 ≈ V×d + L × (12~14.67) × d²

### 注意力机制

| 类型 | 原理 | KV Cache (相对MHA) | 代表模型 |
|---|---|---|---|
| MHA | Q/K/V 全多头 | 1× (基准) | GPT-2/3, BERT |
| MQA | K/V 共享一组 | 1/h | PaLM, Falcon |
| **GQA** | Q 分组共享 K/V | h/(g×h) | **LLaMA-2/3, Mistral, Claude** |
| **MLA** | KV 压缩到潜在向量 | ~1/20 | **DeepSeek-V2/V3/R1** |
| SWA | 滑动窗口注意力 | O(w) | Mistral (交替层) |
| Flash Attention | IO 优化 (tiling) | 不变 | 通用加速 2-4× |

### 位置编码

| 方案 | 原理 | 外推能力 | 代表 |
|---|---|---|---|
| 正弦 | 固定 sin/cos | 差 | 原始 Transformer |
| 可学习 | 可训练参数 | 差 | GPT-2 |
| **RoPE** | 旋转 Q/K 向量 | **好** | **LLaMA/Mistral/Qwen/DeepSeek** |
| ALiBi | 距离偏置惩罚 | 好 | Falcon/BLOOM |

---

## 二、预训练 7 阶段速查

| # | 阶段 | 做什么 | IO 模式 | 存储需求 |
|---|---|---|---|---|
| ① | **数据准备** | 爬取→清洗→去重→混合 | 大量小文件读→大文件写 | S3(原始) + Lustre/EBS(处理) |
| ② | **Tokenization** | 文本→token ID→二进制打包 | 顺序读写大文件 | CPU 密集，S3→S3 |
| ③ | **数据加载** | DataLoader 多 worker 预取到 GPU | 顺序读(已预打乱) | 不是瓶颈(~50MB/s) |
| ④ | **前向传播** | 输入→L 层 Transformer→Loss | **零磁盘 IO**(纯 GPU) | HBM 带宽瓶颈 |
| ⑤ | **反向传播** | Loss→链式法则→每个参数的梯度 | **零磁盘 IO**(2× 前向计算量) | 激活 Offload 时有 PCIe IO |
| ⑥ | **梯度同步+更新** | All-Reduce→AdamW 更新参数 | **网络 IO**(EFA 400Gbps+) | 通信量 ≈ 2× 模型大小 |
| ⑦ | **Checkpoint+评估** | 每 N 步写 checkpoint→定期 eval | **存储写 IO**(核心瓶颈) | Lustre 20+ GB/s |

### Checkpoint 关键数据

| 项目 | 数值 |
|---|---|
| 70B 完整 checkpoint | ~420 GB (参数 140GB + 优化器 280GB) |
| 405B 完整 checkpoint | ~2.4 TB |
| 保存频率 | 每 500-2000 步 |
| 同步写阻塞 (Lustre 22GB/s) | ~19s (70B) |
| 异步写阻塞 (GPU→CPU 拷贝) | 6-14s (7B-13B, IBM 实测) |
| 异步默认开启？ | **否**。PyTorch/Megatron 默认同步 |
| 全量保留存储量 (70B, 390万步) | ~1.6 PB |

---

## 三、学习率与优化器速查

| 模型 | 优化器 | 峰值 lr | Warmup | 衰减 | 最终 lr |
|---|---|---|---|---|---|
| LLaMA-3 405B | AdamW | 8×10⁻⁵ | 8000 steps | Cosine | peak/10 |
| LLaMA-3 8B | AdamW | 3×10⁻⁴ | 8000 steps | Cosine | peak/10 |
| DeepSeek-V3 | AdamW | 2.2×10⁻⁴ | 2000 steps | Cosine | peak/10 |

> 规律：模型越大 → 峰值 lr 越小

### NaN/Inf 防护

| 措施 | 作用 |
|---|---|
| Gradient Clipping (max_norm=1.0) | 梯度范数超阈值等比缩放 |
| bf16 (vs fp16) | 指数位 8bit 同 fp32，动态范围大不溢出 |
| Loss Scaling (fp16 专用) | 放大 loss 防下溢，更新前除回 |
| NaN 检测 + 跳过 | 丢弃坏 step，回滚 checkpoint |

---

## 四、评估后重训决策树

| 发现的问题 | 从哪里开始 | 成本 |
|---|---|---|
| 架构/tokenizer 要改 | 从头预训练 | $$$$$（数千万美元） |
| 预训练数据大改 | 从头或早期 checkpoint | $$$$$ |
| 预训练数据微调配比 | 从中间 checkpoint 继续 | $$$（节省已训部分） |
| Loss 正常但下游任务不行 | 后训练 (SFT/RLHF) | $（预训练的 1/1000） |
| NaN / Loss spike | 回退最近好的 checkpoint | 损失几个 step |
| 加新能力(新语言/领域) | Continue Pre-training 或 LoRA | $$~$$$ |

### 预训练 vs 后训练

| | 预训练 | 后训练 (SFT/RLHF) |
|---|---|---|
| 数据量 | 15T tokens | 10M-100M tokens |
| 计算量 | 3000 万 GPU 小时 | 几万 GPU 小时 |
| 学习率 | ~1e-4 | ~1e-5 到 1e-6 |
| 耗时 | 几个月 | 几天到几周 |

---

## 五、4 大 IO 模式速查

| 训练场景 | IO 模式 | IO 大小 | 关键指标 | 存储瓶颈 | AWS 推荐存储 |
|---|---|---|---|---|---|
| **LLM 预训练** | 顺序大块读 | MB~GB | 吞吐 (GB/s) | Checkpoint 写入 | FSx Lustre / S3 |
| **推荐系统** | 随机小 IO (Embedding 查表) | 64B~512B | **IOPS** (百万级) | Embedding 加载 | GPU 显存 / 本地 NVMe |
| **GNN** | 极度随机小 IO (图采样) | 256B~4KB | **IOPS** (百万级) | 节点特征加载 | DRAM / NVMe RAID-0 |
| **多模态** | 中等随机中文件 | 30KB~5MB | 带宽 + IOPS | 图片/视频加载 | Lustre + WebDataset 打包 |

### IO 大小 vs 随机性象限

```
IO 大小 (大)
     ^
     │  Checkpoint 写入      多模态(视频)
     │  (MB-GB, 顺序)       (MB, 中等随机)
     │
     │  LLM 数据读取         多模态(图片)
     │  (MB, 顺序)          (KB, 中等随机)
     │
     │                       推荐 Embedding    GNN 图采样
     │                       (Bytes, 随机)     (KB, 极度随机)
     └──────────────────────────────────────────────► 随机性 (高)
```

### AWS 存储选型

| 训练场景 | 首选 | 备选 | 不适合 |
|---|---|---|---|
| LLM 预训练 | FSx Lustre PERSISTENT_2 | S3 + Mountpoint | EBS(吞吐上限低) |
| 推荐系统 | 本地 NVMe (i3en/p5d) | EBS io2 Block Express | Lustre/EFS(随机延迟高) |
| GNN | 本地 NVMe (i4i/i3en) | 大内存型 (r7i) | 任何网络存储 |
| 多模态(打包后) | FSx Lustre | S3 + prefetch | — |
| 多模态(未打包) | FSx Lustre + MDT | EBS io2 | S3(小文件 IOPS 低) |

---

## 一步训练的时间分解 (70B, 64×H100, 估算)

```
③ 数据加载    0.01s  ██                          (预取覆盖)
④ 前向传播    1.5s   ████████████████████████
⑤ 反向传播    3.0s   ████████████████████████████████████████
⑥ All-Reduce 0.3s   ██████                (与反向重叠)
⑥ AdamW 更新  0.2s   ████
⑦ Checkpoint  6-19s  ████████████████████  (每 1000 步, 同步/异步)

总计: ~5s/step (不含 checkpoint)
吞吐: 4M tokens / 5s = 800K tokens/s
```
