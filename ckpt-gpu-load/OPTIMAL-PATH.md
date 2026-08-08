# S3 → GPU 显存 最优加载路径

## 🏁 结论(先看这个)

**最快路径 = CRT `recv_filepath` 下载 → NVMe → `safetensors.load_file(cuda)` = 26s**（20GB ckpt）
比 naive 写法（S3→RAM→`torch.load(BytesIO)`→GPU = 130s）**快 5 倍**。

| 链路 | 总计 | 排名 |
|------|------|------|
| **CRT recv_filepath → NVMe → load_file(cuda)** | **26.1s** | 🥇 用这个(代码最简) |
| 多进程boto3 DL → NVMe → load_file | 28.0s | 🥈 也很快 |
| CRT recv_filepath → /dev/shm(RAM) → load_file | 30.7s | ❌ RAM盘反而更慢 |
| 多进程DL → tmpfs → load_file | 30.2s | |
| 多线程DL → NVMe → load_file | 91.9s | ❌ 慢(GIL) |

**一句话**：下载用 CRT(recv_filepath，C 层直接写文件、自带并发绕 GIL)或多进程 boto3；加载用 `load_file(cuda)` 吃刚写完的热缓存(3s)。**别用 tmpfs/dev/shm、别手动零拷贝——实测全都没用甚至更慢。**

### ⚠️ 反直觉实测(全都被推翻的"合理推论")
- "数据直接进 RAM(/dev/shm)最快" → **实测反而慢 4.5s**(tmpfs 挤占 page cache，加载 7.2s vs NVMe 3.1s)
- "内存直载比落盘快" → 实测落盘快(内存直载多一次大拷贝)
- "safetensors 零拷贝远快于 torch.load" → 冷启动几乎一样(优势只在热缓存)
- "手动整块 H2D 更快" → 实测更慢(实现有多余拷贝)

**教训：一切结论必须实测。理论上"应该更快"常因隐藏开销(拷贝/GIL/缓存竞争)而更慢。**

## ▶️ 可运行代码(直接用)

**`full_pipeline.py`** —— 复制即可跑，改环境变量指向你的 bucket：

```bash
export S3_BUCKET=your-bucket S3_KEY=ckpt-bench/ckpt_20g.safetensors AWS_REGION=us-east-2
/opt/pytorch/bin/python full_pipeline.py
```

前提：GPU 实例(g5/g6 等) + DLAMI(PyTorch)，EC2 IAM role 有 S3 读权限，本地有 NVMe 挂在 `/nvme`。

核心就这几行(最优路径)：
```python
# 1) 多进程下载(绕GIL): 64 进程各下一段 byte-range 写同一文件
mp_download("/nvme/ckpt.st", nproc=64, part_mb=16)
# 2) 加载到显存: mmap 直接 DMA 到 GPU, 吃刚写完的热缓存
sd = safetensors.torch.load_file("/nvme/ckpt.st", device="cuda:0")
torch.cuda.synchronize()
```

想更快：把 `mp_download` 的 worker 换成 Rust/Go 二进制，下载 25s→~10s，全链路可到 ~13s。

---

## 📊 详细分析(想深入再看)

### 全链路实测明细(g5.4xlarge A10G, 20GB safetensors)

| 链路 | 下载 | 加载显存 | 总计 |
|------|------|---------|------|
| CRT recv_filepath → NVMe → load_file | 23.0s | 3.1s | **26.1s** 🥇 |
| CRT recv_filepath → /dev/shm(RAM) → load_file | 23.5s | 7.2s | 30.7s |
| 多进程boto3 DL → NVMe → load_file | 25.1s | 2.9s | 28.0s |
| 多进程boto3 DL → tmpfs → load_file | 23.7s | 6.4s | 30.2s |
| 多线程boto3 DL → NVMe → load_file | 88.3s | 3.6s | 91.9s |
| 多线程boto3 DL → tmpfs → load_file | 87.7s | 6.5s | 94.1s |

### CRT recv_filepath 与 "直接读进 RAM" 的现实

需求"让 boto3/CRT 直接读进进程可访问 RAM"——**boto3/CRT 没有"交我一块 buffer 让 CRT 直接 DMA 写入"的官方接口**(Python 层限制)。最接近的做法是 CRT `recv_filepath` 写 `/dev/shm`(tmpfs=RAM) 再 mmap。但**实测 /dev/shm 反而比 NVMe 慢**(加载 7.2s vs 3.1s)：推测 tmpfs 占 20GB RAM 挤压了 page cache，而 NVMe 文件读时进 page cache 反而命中更快。`recv_filepath`(C 层直接写文件、自带并发绕 GIL)本身很高效，写 NVMe 即最优，且代码比手写多进程更简单。

### 三个原理

**1. 多进程下载绕 GIL(88s→25s，最大提速点)**
- 多线程受 GIL：同一时刻只有一个线程执行字节码，下载后处理响应被串行化。
- 多进程 `mp.Pool`：每进程独立解释器/GIL，真并行。
- 代价：每进程各建 `boto3.client`(不能跨进程共享)，有 fork/IPC 开销，但对大数据下载值得。

**2. 加载显存只要 ~3s —— 热缓存 + mmap**
- `load_file(path, device="cuda")`：mmap 映射文件，数据直接 DMA 到显存，不经 Python 反序列化/CPU tensor 中转。
- 下载进程刚 `write()` 完，数据还在 page cache(热)，`load_file` 直接热读 ~3s；冷读盘则 ~20s。

**3. 反直觉：NVMe 比 tmpfs 更快**
- 直觉以为 tmpfs 内存盘更快，实测 NVMe(2.9s) 反而快于 tmpfs(6.4s)。
- 推测：多进程写 tmpfs 有内存分配/竞争开销 + 挤压 page cache；NVMe 写完同样落 page cache 被热读。
- 教训：别过度优化，实测说话。

### page cache 一致性：不 flush 直接 mmap 读安全吗？

**安全，不会不一致。** Linux 的 `write()` 和 mmap 读**共享同一份统一 page cache**：数据一进 page cache 就对所有读者可见，mmap 立即读到最新内容。`fsync`/`flush` 只保证落盘持久化，与"读一致性"无关。

本代码时序也安全：多进程写同一 inode 的**不重叠区段**(byte-range 切片)，`mp.Pool().map()` **全部返回后**才 mmap 加载 → 先写完再读。

会不一致的场景(本代码都没触发)：边写边读同一区段 / O_DIRECT / 跨机器 NFS / mmap 写未 msync。

### 优化优先级

| 阶段 | 现状 | 优化后 |
|------|------|--------|
| 下载 | 25s(多进程) / 88s(多线程) | Rust/Go → ~10s |
| 加载显存 | ~3s | 已接近极限(纯 H2D 2s) |
| **全链路(20GB)** | **28s** | **~13s** |

**核心洞察**：90% 收益来自"下载绕 GIL"；加载靠"热缓存 + load_file(cuda)"就够快。

## 文件
- `full_pipeline.py` — 最优路径完整代码(4 链路对比，带注释)
- `README.md` — 更早的 A/B/safetensors/pinned 系列测试
