# Checkpoint 加载到显存(GPU)全链路性能分析

深入分析 AI checkpoint 从 S3 加载到 GPU 显存的全链路耗时，拆解每一步的真实瓶颈。核心发现：**瓶颈几乎都在软件层（下载的 Python GIL、加载的反序列化），而非硬件（网卡/PCIe/显存）**。

- **测试机**: g5.4xlarge（NVIDIA A10G 24GB，16 vCPU，64GB RAM，25Gbps 网卡），us-east-2
- **测试对象**: 20GB checkpoint（真实 PyTorch state_dict，20×1GB float32 tensor），`.pt` 与 `.safetensors` 两种格式
- **软件**: PyTorch 2.9 + CUDA 13，boto3，safetensors 0.8
- **日期**: 2026-08-08
- **计时**: 全部用 `torch.cuda.synchronize()` 卡到显存真正就绪

> 🔒 代码 bucket/key 从环境变量读取，无硬编码；凭证走 EC2 IAM role。

## 一、三条加载路径对比（到显存总时间，20GB）

| 路径 | 下载 | 加载到显存 | **总计** |
|------|------|-----------|---------|
| A：S3→RAM→`torch.load(BytesIO)`→GPU | 101s | 29s | **130s** |
| B：S3→NVMe→`torch.load(file)`→GPU | 95s | 20s | **115s** |
| C：S3→NVMe→`safetensors.load_file(cuda)` | 95s | 20s | **115s** |

**反直觉发现 1**：内存直载(A)反而最慢——多了一次 20GB 大内存拷贝，且 `torch.load(BytesIO)` 比文件路径慢。
**反直觉发现 2**：safetensors mmap(C) 和 torch.load(B) 冷启动几乎一样——冷缓存下都要真读盘 20GB，safetensors 的零拷贝优势在**热缓存/反复加载**才体现。

## 二、揪出"加载慢"的真凶：29s 里 H2D 只占 2s

对"内存→显存"这一步深入拆解：

| 方式 | 时间 | 说明 |
|------|------|------|
| M1：`safetensors.load(bytes(buf))` | 29.1s | `bytes()`深拷贝20GB + Rust反序列化 + 逐tensor `.to(GPU)` |
| M2：`safetensors.load(memoryview(buf))` | ❌ TypeError | safetensors 只接受 `bytes`，不支持 memoryview/buffer protocol |
| **M3：pinned/普通内存 → 单次大块 `copy_` 到显存** | **1.6~2.2s（10-13 GB/s）** | 纯 H2D 传输 |

**核心发现**：**"内存→显存"的真实硬件速度只需 ~2s（10-13 GB/s）。之前 A 路径的 29s 全是 safetensors/torch 的反序列化 + 大内存拷贝 + 逐张量小块 H2D 的软件开销，不是 H2D 本身。**

- pinned vs 普通内存 H2D 差异很小（单次大块场景），pinned 的优势在**异步 non_blocking + 与下载/计算 overlap** 时才明显。
- memoryview 零拷贝在 safetensors 上走不通（库限制），要真零拷贝得绕开 `safetensors.load`。

## 三、下载才是全链路最大瓶颈

三条路径下载都 ~95-101s，有效吞吐仅 ~1.7 Gbps，**远没打满 25Gbps 网卡**——因为用的是 **Python boto3 多线程，被 GIL 限制**（见同仓库 `s3-crt-100gbps-download` 的语言对比：Python 多线程仅 ~5 Gbps，Rust/Java 可打满）。

## 四、最优方案与优化优先级

```
S3 并发下载 (Rust/Go 打满带宽)  ← 瓶颈①: 94s → ~10s
   → pinned CPU buffer
   → 单次大块 H2D 整块到显存 (~2s)   ← 瓶颈②: 29s → 2s
   → 用 safetensors header offset 在显存上 zero-copy 切 view
```

| 阶段 | 现状(Python+safetensors) | 优化后 |
|------|----------|--------|
| 下载 | ~94s (Python GIL) | Rust/Go 打满 → ~10s |
| 加载到显存 | ~29s (反序列化) | 纯 H2D → ~2s |
| **全链路(20GB)** | **130s** | **~15s** |

**核心洞察**：全链路两个瓶颈都是软件开销，不是硬件。网卡、PCIe H2D、显存本身都很快。别被"safetensors 零拷贝""内存直载更快"这类说法误导——要实测拆解每一步。

## 文件说明

- `ckpt_load_bench.py` — 路径 A/B 对比（内存直载 vs 落盘）
- `st_bench.py` — safetensors mmap vs torch.load
- `pinned_bench.py` — pinned/普通内存 → H2D 纯传输测试（揪出 2s 硬件极限）
- 结论见本 README

> 测试资源（g5.4xlarge + S3 对象）测完清理。代码无硬编码密钥/bucket。
