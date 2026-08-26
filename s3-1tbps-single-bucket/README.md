# S3 单 Bucket 吞吐极限测试：跑满 1 Tbps

用 **Rust + tokio 多客户端并发 ranged GET**，实测**单个 S3 Standard bucket** 的聚合下载吞吐能否达到 **1 Tbps**。

## TL;DR 结论

**单个 S3 Standard bucket 轻松跑满 1 Tbps —— 7 台实测 1.25 Tbps，零错误。**

| 规模 | 聚合吞吐 | 错误 |
|---|---|---|
| 单机 c7gn.16xlarge | ~185 Gbps（标称 200Gbps 的 ~92%）| 0 |
| 2 台 | ~370 Gbps（线性）| 0 |
| **7 台** | **1,253 Gbps ≈ 1.25 Tbps / 156.7 GB/s** | 0 |

三个硬结论：

1. **单个 S3 bucket 吞吐上限远超 1 Tbps**，瓶颈在**客户端网卡总和**，不在 S3 服务端。
2. **完美线性扩展**：7 台同打同一个 bucket，聚合 ≈ 7 × 单机，无衰减、无限流（84 万请求 0 个 503 SlowDown）。
3. **Rust + tokio 单机轻松打满 200Gbps 网卡**，无 Python GIL 瓶颈。

## 测试设计

### 数据准备
- **50 个对象 × 20 GB = 1 TB**，分散到 **50 个 prefix**（`p00/` ~ `p49/`）。
- 大文件设计：单对象 20GB，压测时用 **ranged GET 随机 offset** 读取 8MB 分片，**无需切换文件**、避免小文件元数据开销。
- prefix 分散是关键：S3 GET 性能按 prefix 横向扩展，50 个 prefix 足以支撑 1.25 Tbps 而不触发单 prefix 限流。

### 压测客户端（`main.rs`）
- Rust + tokio 多线程 runtime，`concurrency` 个并发 worker。
- 每个 worker 循环：随机选对象 + 随机 offset → `GET` with `Range: bytes=off-end` → **流式读取并丢弃字节**（测纯网络吞吐，不落盘）。
- 实时每 2s 报告 Gbps / GB/s / reqs / errs，结束打印均值。
- 用法：`s3tp <bucket> <region> <concurrency> <duration_secs> <chunk_mb>`
- 典型参数：`s3tp <bucket> us-east-2 256 45 8`

### 基础设施
- 机型：**c7gn.16xlarge**（Graviton3，标称 200 Gbps 网络，$/Gbps 最划算的 200Gbps 机型）。
- 全部实例 + bucket **同一 AZ**（us-east-2a），走 **S3 Gateway VPC Endpoint** 内网访问，免 NAT、免流量费。
- IAM instance profile 授予 S3 访问；ranged GET 全程零落盘。

## 逐台明细（7 台）

```
N1  177.7 Gbps    N2  180.3 Gbps    N3  181.8 Gbps
N4  179.6 Gbps    N5  179.6 Gbps    N6  174.5 Gbps
N7  180.1 Gbps
---------------------------------------------
聚合 1,253.6 Gbps = 1.25 Tbps = 156.7 GB/s
45 秒下载 ~7 TB，errs=0
```

## 外推

单机稳态 ~185 Gbps，线性扩展：

| 目标 | c7gn.16xlarge 台数 | 成本估算 |
|---|---|---|
| 1000 Gbps (1 Tbps) | 6 台（留余量 7 台）| ~$28/hr |

## 文件

- `main.rs` — Rust 压测程序（tokio 并发 ranged GET）
- `Cargo.toml` — 依赖（aws-sdk-s3 / tokio / rustls）
- `gen_data.sh` — 数据生成脚本（生成 1 个 20GB 源文件，并行上传到 N 个 prefix）

## 复现步骤

1. 建 S3 Standard bucket（与压测实例同 region/AZ）。
2. 起 N 台高网络实例（c7gn.16xlarge 200Gbps），同 AZ，挂 S3 Gateway Endpoint + S3 IAM。
3. 每台 `cargo build --release`（或分发预编译二进制）。
4. 任一台跑 `gen_data.sh <bucket>` 灌数据（1 TB / 50 prefix）。
5. N 台**同时**启动 `s3tp <bucket> <region> 256 45 8`，汇总各台 AVG Gbps 即聚合吞吐。

## 注意事项 / 教训

- **瓶颈判定法**：单机打满网卡后逐台加，看聚合是否线性。线性增长 = 瓶颈在客户端；不涨 = 撞到服务端/AZ 上限。本测试全程线性 → S3 侧远未到顶。
- **必须 Rust（或同等无 GIL 语言）**：Python 单进程受 GIL 限制打不满高带宽网卡。
- **prefix 要分散**：单 prefix 有 GET req/s 上限，大规模高吞吐必须多 prefix。
- **同 AZ + Gateway Endpoint**：跨 AZ 有额外延迟/带宽损失且产生流量费；同 region EC2↔S3 免流量费。
- **测完立即清理**：高网络实例 $4/台/hr，7 台 ~$28/hr。

---

*测试日期：2026-08-26 · region us-east-2 · 所有测试资源已于测试后完全清理。*
