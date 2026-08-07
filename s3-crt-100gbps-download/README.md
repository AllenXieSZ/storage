# S3 大文件下载吞吐测试 —— 打满 100Gbps 网卡

测试从 Amazon S3 下载单个 100GB 大对象的吞吐极限，对比 **Python (awscrt) vs Rust (aws-sdk-s3)**，并找出打满 100Gbps 网卡的关键因素。

- **区域**: us-east-2 (Ohio)
- **测试对象**: `s3://<BUCKET>/ckpt-bench/ckpt_100g.bin`（100GB，随机数据，S3 不压缩）
- **测试日期**: 2026-08-07
- **场景**: 模拟 AI checkpoint 从 S3 加载（数据读进内存，body 丢弃，纯测 S3→内存传输，不落盘）

## 机器配置

| 项 | 配置 |
|----|------|
| 实例类型 | **i7i.48xlarge**（从 i7i.4xlarge 升级而来） |
| vCPU / 内存 | 192 vCPU / 1488 GiB RAM |
| 网卡 | **Up to 100 Gigabit** |
| 本地存储 | 12 × 3.4 TB NVMe instance store |
| OS | Amazon Linux 2023（kernel 6.1） |
| AZ | us-east-2a（与测试无关，纯 S3 下载） |
| Rust | 1.97.1 |
| aws-sdk-s3 | 1.141.0（默认 hyper HTTP client，非 CRT） |
| Python awscrt | 0.31.1（对照组，CRT 底层绑定） |

## 核心结果

![charts](s3_download_throughput_charts.png)

### Rust aws-sdk-s3 手动 byte-range 并发（打满 100Gbps）

| part_size | 并发数 | 时间 | 吞吐 |
|-----------|--------|------|------|
| 8MB | 64 | 35.3s | 3.04 GB/s (24.3 Gbps) |
| 8MB | 128 | 14.0s | 7.67 GB/s (61.4 Gbps) |
| 8MB | 256 | 9.1s | 11.84 GB/s (94.8 Gbps) |
| 16MB | 128 | 9.1s | 11.81 GB/s (94.5 Gbps) |
| **16MB** | **256** | **8.9s** | **12.03 GB/s (96.3 Gbps)** ⭐ 打满 |

### Python awscrt 对照（`throughput_target_gbps` 驱动并发）

| 机型 | part_size | target | 峰值吞吐 |
|------|-----------|--------|---------|
| i7i.4xlarge (25G) | 8MB | 25Gbps | 3.05 GB/s (24.4 Gbps) |
| i7i.48xlarge (100G) | 8MB | 50Gbps | **6.72 GB/s (53.8 Gbps)** ← 单对象峰值 |
| i7i.48xlarge (100G) | 8MB | 100Gbps | 6.30 GB/s (50.4 Gbps) |

多对象并行（awscrt）聚合也只到 ~52 Gbps，加并发不涨。

## 关键结论

1. **并发度是打满带宽的决定因素**（不是 chunk 大小、不是语言）：
   - 64 路 → 24 Gbps；128 路 → 61 Gbps；256 路 → **94–96 Gbps**
   - part 8MB 与 16MB 差别很小，关键在**同时 in-flight 的 byte-range GET 数量**。

2. **单对象也能打满 100Gbps**：只要并发够高（256 路 byte-range），单个 100GB 对象 8.9 秒下完，达 96.3 Gbps。

3. **Python awscrt 卡在 ~54 Gbps 不是实例/S3 的上限**，而是：
   - `throughput_target_gbps` 驱动的 CRT 内部并发不够激进
   - Python `on_body` 回调 + GIL 开销
   - Rust 手动开 256 路并发直接压满 → **推翻了"54 Gbps 是实例天花板"的误判**。

4. **larger part = slower**（Python awscrt）：8MB > 16MB > 32MB > 64MB，大分片让 in-flight 请求数变少，并发被稀释。

## 实践建议（AI checkpoint / 大文件从 S3 加载）

- **想吃满高带宽网卡（100G），关键是拉高并发分片数到 256 左右**，语言/库其次。
- 用 CRT（awscrt）时别盲目调大 chunk（默认 8MB 最优）；`throughput_target_gbps` 设成 ≈ 网卡带宽，别设过高。
- 需要极致吞吐（打满 100G）时，Rust/Go 手动控并发 或 Python 多进程 比单进程 awscrt 更能压满。
- 下载目标设内存/流（不落盘）可省一次磁盘往返；但注意 100GB 对象需 < 实例内存才能整份驻留。

## 文件说明

- `src/main.rs` — Rust 测试程序（aws-sdk-s3 + tokio，手动 byte-range + Semaphore 控并发，body 流式丢弃）
- `Cargo.toml` — 依赖定义
- `gen_charts.py` — 图表生成脚本（matplotlib）
- `s3_download_throughput_charts.png` — 结果图表

## 复现

```bash
# 实例: i7i.48xlarge (100Gbps), Amazon Linux 2023, EC2 IAM role 有 S3 读权限
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env
sudo dnf install -y gcc
# 准备一个 100GB 测试对象到 s3://<bucket>/ckpt-bench/ckpt_100g.bin
cargo build --release
./target/release/s3crt
```

> 测试资源（i7i.48xlarge + S3 测试对象）测完已清理。BUCKET/KEY 为测试值，复现时替换为你自己的。
