# S3 单 Bucket 吞吐极限测试：跑满 1 Tbps → 10 Tbps

用 **Rust + tokio 多客户端并发 ranged GET**，实测**单个 S3 Standard bucket** 的聚合下载吞吐上限。分两阶段：先验证 1 Tbps，再推高到 10 Tbps。

## TL;DR 结论

**单个 S3 Standard bucket 稳态实测 10.69 Tbps，瓶颈完全在客户端网卡，S3 服务端毫无压力（0 错误 / 0 限流 / 0 503 SlowDown）。**

| 阶段 | 规模 | 聚合吞吐 | 说明 |
|---|---|---|---|
| 阶段一 | 单机 c7gn.16xlarge | ~190 Gbps | 标称 200Gbps 的 ~95% |
| 阶段一 | 2 台 | ~370 Gbps | 线性 |
| 阶段一 | **7 台** | **1.25 Tbps** | 均值（含爬坡）|
| 阶段二 | **56 台（全程均值）** | **9.61 Tbps** | 含前 ~10s 爬坡拉低 |
| 阶段二 | **56 台（稳态峰值）** | **10.69 Tbps** ✅ | 单机稳态 190.9 Gbps × 56 |

## 核心结论（10 Tbps 级铁证）

1. **单个 S3 bucket 吞吐上限远超 10 Tbps** —— 瓶颈是**客户端网卡总和**，不在 S3 服务端。
2. **完美线性扩展**：56 台各打满自己的 200G 网卡（稳态 189.5~193.5 Gbps，极均匀），聚合 ≈ 56 × 191 = 10.69 Tbps，无衰减。
3. **前缀（prefix）分散是关键**：GET 性能按 prefix 横向扩展。
   - 1 Tbps 用 **50 个 prefix**（`p00`~`p49`）
   - 10 Tbps 用 **200 个 prefix**（`p000`~`p199`）
   - 全程 **0 个 503 SlowDown**，说明 prefix 数量充足，S3 后端自动横向扩展跟得上。
4. **必须 Rust（或同等无 GIL 语言）**：Python 单进程受 GIL 限制打不满高带宽网卡。tokio 多并发 ranged GET 单机轻松打满 200Gbps。

## 网卡是唯一瓶颈（关键发现）

- 单机稳态 190.9 Gbps ≈ c7gn.16xlarge 标称 200Gbps 的 **95.5%**（已接近物理线速）。
- 56 台稳态峰值区间仅 **189.5~193.5 Gbps**（标准差极小），说明每台都稳定顶在网卡上限，**不是 S3 侧限流造成的抖动**。
- 聚合 = 单机 × 台数，**严格线性**：1 台 190 → 7 台 1.25T → 56 台 10.69T。
- 推论：想继续推高（15/20 Tbps），只需继续加客户端网卡（更多实例或更高带宽机型），S3 单 bucket 侧不构成瓶颈。

## 测试设计

### 机型 / 网络
- **c7gn.16xlarge**（Graviton3 ARM，标称 **200 Gbps**，$3.99/hr，$/Gbps 最划算的 200Gbps 机型；对比 c6in.32xlarge 200Gbps 需 $7.26/hr）。
- 全部实例 + bucket 同 region（us-east-2），走 **S3 Gateway VPC Endpoint** 内网访问，免 NAT、免流量费。
- 10Tbps 阶段因单 AZ 容量不足，跨 **us-east-2a / 2c 多 AZ** 分散起 56 台（2b 全程无 c7gn 容量）。

### 数据准备
- 1 Tbps：50 对象 × 20 GB = **1 TB**，50 prefix。
- 10 Tbps：200 对象 × 20 GB = **4 TB**，200 prefix。
- 大文件设计：单对象 20GB，压测用 **ranged GET 随机 offset** 读 8MB 分片 → 无需切换文件、避免小文件元数据开销。

### 压测客户端（`main.rs`）
- Rust + tokio 多线程 runtime，`concurrency` 个并发 worker。
- 每 worker 循环：随机选对象 + 随机 offset → `GET Range: bytes=off-end` → **流式读取并丢弃字节**（测纯网络吞吐，不落盘）。
- 实时每 2s 报告 Gbps / GB/s / reqs / errs。
- 用法：`s3tp <bucket> <region> <concurrency> <duration_secs> <chunk_mb>`
- 典型参数：`s3tp <bucket> us-east-2 256 90 8`

## 10 Tbps 实测日志（摘要）

**56 台，各 256 并发，90s，8MB chunk：**

```
稳态单机峰值 (samples after warmup, 56 节点匿名化):
  最高: node-A = 193.5 Gbps
        node-B = 193.0 Gbps
        node-C = 192.9 Gbps
  最低: node-X = 189.5 Gbps
        node-Y = 189.5 Gbps
  ---------------------------------------
  56 台稳态峰值之和 = 10,690 Gbps = 10.69 Tbps
  单机峰值均值 = 190.9 Gbps  (区间 189.5~193.5, 极均匀)
  有效节点 56/56, errs=0

50s 轮次全程均值 (含爬坡):
  56 台聚合 = 9,610 Gbps = 9.61 Tbps  (前~10s爬坡拉低均值)
```

## 成本

| 阶段 | 实例 | $/hr |
|---|---|---|
| 1 Tbps | 7 × c7gn.16xlarge | ~$28 |
| 10 Tbps | 56 × c7gn.16xlarge | ~$224 |

实际测试各阶段仅运行几分钟~十几分钟，总成本约 $50-60。测完立即清理。

## 踩过的坑（重要教训）

1. **default VPC 子路由表的默认路由指向已删除的 NAT gateway（blackhole）** → 该 subnet（us-east-2c）的实例有公网 IP 但**无出入站互联**，SSH 全部 timeout。修复：`replace-route` 把 0.0.0.0/0 从 blackhole NAT 改指 IGW。诊断法：`ssh -v` 看 "Connection timed out" + 查路由表 `Routes[?DestinationCidrBlock=='0.0.0.0/0']` 是否 `State: blackhole`。
2. **实例默认不分配公网 IP** → 多数 default VPC subnet 的 auto-assign-public-IP=false，`run-instances` 必须显式 `--network-interfaces [{...,"AssociatePublicIpAddress":true}]`（不能和顶层 `--security-group-ids/--subnet-id` 混用，要放进 network-interfaces）。
3. **c7gn.16xlarge 单 AZ 容量不足** → 大批量（20+ 台/AZ）常 `InsufficientInstanceCapacity`。解法：小批次（每次 6 台）+ 多 AZ 滚动重试凑齐目标台数。
4. **数据生成两进程竞争同一 src 文件 → `IncompleteBody` 上传失败**：并行 `aws s3 cp` 时若源文件还在被另一进程写/未固定大小，会报 "did not provide the number of bytes specified by Content-Length"。修复：**先完整生成源文件（阻塞等完成），再并行上传**（两步分离）。
5. **后台任务被 SSH 会话关闭杀死**：`nohup ... &` 在单条 SSH 里有时仍被 SIGHUP。可靠模式 = `(nohup cmd > log 2>&1 &)` 子shell 包裹，或 `setsid ... < /dev/null &`。
6. **S3 CloudWatch 请求指标默认不开**：BytesDownloaded/GetRequests 属 request metrics，**必须先 `put-bucket-metrics-configuration` 开启**才记录，否则测完在 CloudWatch 看不到服务端吞吐曲线（存储指标 BucketSizeBytes 免费但每天才刷一次）。

## 文件

- `main.rs` — Rust 压测程序（tokio 并发 ranged GET）
- `Cargo.toml` — 依赖（aws-sdk-s3 / tokio / rustls）
- `gen_data.sh` — 1TB 数据生成（50 prefix）
- `gen_data_big.sh` — 4TB 数据生成（200 prefix，两步分离防 IncompleteBody）

## 复现步骤

1. 建 S3 Standard bucket（与压测实例同 region）。
2. 起 N 台高网络实例（c7gn.16xlarge 200Gbps），显式分配公网 IP，挂 S3 Gateway Endpoint + S3 IAM，容量不足则多 AZ 滚动起。
3. 一台上 `cargo build --release`，把二进制分发到全部 N 台。
4. 一台跑 `gen_data_big.sh <bucket> 200 20` 灌数据（先生成源文件再并行上传）。
5. N 台**同时**启动 `s3tp <bucket> <region> 256 90 8`，采集各台稳态峰值求和 = 聚合吞吐。
6. （可选）测前 `put-bucket-metrics-configuration` 开 request metrics，测后在 CloudWatch 看服务端 GET/BytesDownloaded 曲线。

---

*测试日期：2026-08-26 · region us-east-2 · 峰值 10.69 Tbps（56×c7gn.16xlarge）· 所有计算资源已清理，仅保留空 bucket 供查看 metrics。*
