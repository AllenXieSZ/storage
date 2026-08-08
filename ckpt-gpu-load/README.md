# Checkpoint 从 S3 加载到 GPU 显存 —— 性能分析

## 🏁 结论(先看这个)

**最优路径 = 多进程下载 → NVMe → `safetensors.load_file(cuda)`**，20GB ckpt 到显存 **28s**（naive 写法 130s，快 4.6 倍）。详见 [`OPTIMAL-PATH.md`](OPTIMAL-PATH.md)。

三条核心结论：
1. **下载是最大瓶颈**，且瓶颈在 Python GIL 不在网络 —— 多进程绕 GIL 是最大提速点(88s→25s)。
2. **加载到显存的硬件极限只要 ~2s(纯 H2D)**；`torch.load`/`safetensors.load(bytes)` 的 29s 全是软件开销(深拷贝+反序列化)。
3. **"内存直载""safetensors 零拷贝"未必快** —— 冷启动被磁盘读/H2D 主导，safetensors 零拷贝优势只在**热缓存**才体现(冷 20s vs 热 3.8s)。

## ▶️ 可运行代码

| 文件 | 作用 | 直接可跑 |
|------|------|---------|
| **`full_pipeline.py`** | **最优路径 + 4 链路对比(推荐先看这个)** | ✅ |
| `ckpt_load_bench.py` | 路径 A(内存直载) vs B(落盘) | ✅ |
| `st_bench.py` | safetensors mmap vs torch.load | ✅ |
| `pinned_bench.py` | pinned/普通内存 → H2D 纯传输 | ✅ |

跑法：
```bash
export S3_BUCKET=your-bucket S3_KEY=ckpt-bench/ckpt_20g.safetensors AWS_REGION=us-east-2
/opt/pytorch/bin/python full_pipeline.py
```
前提：GPU 实例(g5/g6) + DLAMI，EC2 IAM role 有 S3 读权限，本地 NVMe 挂 `/nvme`。凭证走 IAM role，代码无硬编码密钥。

---

## 📊 详细分析(想深入再看)

测试环境：g5.4xlarge(A10G 24GB，64GB RAM，25Gbps)，20GB PyTorch state_dict ckpt(`.pt` + `.safetensors`)，PyTorch 2.9 + CUDA 13，us-east-2，2026-08-08。计时全用 `torch.cuda.synchronize()`。

### 一、三条加载路径(到显存总时间，20GB)

| 路径 | 下载 | 加载显存 | 总计 |
|------|------|---------|------|
| A：S3→RAM→`torch.load(BytesIO)`→GPU | 101s | 29s | 130s |
| B：S3→NVMe→`torch.load(file)`→GPU | 95s | 20s | 115s |
| C：S3→NVMe→`safetensors.load_file(cuda)` | 95s | 20s | 115s |

反直觉：内存直载(A)反而最慢(多一次 20GB 拷贝)；safetensors mmap(C) 冷启动和 torch.load(B) 一样。

### 二、加载慢的真凶：29s 里 H2D 只占 2s

| 方式 | 时间 | 说明 |
|------|------|------|
| `safetensors.load(bytes(buf))` | 29.1s | 深拷贝 + 反序列化 + 逐 tensor .to |
| `safetensors.load(memoryview)` | ❌ 报错 | safetensors 只接受 bytes，不支持 memoryview |
| **纯 H2D(内存→显存单次大块 copy_)** | **1.6~2.2s(10-13 GB/s)** | 硬件真实速度 |
| load_file(cuda) 热缓存 | 3.8s | 数据在 page cache 时最快 |

**"内存→显存"硬件只需 ~2s，29s 全是软件开销。** memoryview 零拷贝在 safetensors 走不通(库只吃 bytes)。

### 三、下载才是最大瓶颈

三条路径下载都 ~95-101s，有效仅 ~1.7 Gbps，远没打满 25Gbps 网卡 —— 因为 Python boto3 多线程受 GIL。多进程可到 25s(见 `full_pipeline.py`)，Rust/Java 可打满(见同仓库 `s3-crt-100gbps-download`)。

### 四、最优方案

见 `OPTIMAL-PATH.md`。核心：多进程下载(绕 GIL) + 落 NVMe + `load_file(cuda)` 吃热缓存 = 28s，Rust/Go 下载可再降到 ~13s。全链路两个瓶颈都是软件开销，不是硬件(网卡/PCIe/显存都很快)。

> 测试资源(g5.4xlarge + S3 对象)测完清理。代码无硬编码密钥/bucket。
