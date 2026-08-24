# Amazon S3 Vectors — 插入/查询延迟实测

在 AWS 账号（us-east-2）上对 **Amazon S3 Vectors**（2025-12-02 GA，首个原生支持向量存储/检索的对象存储）做的一组延迟基准测试。

- 向量维度：**1024**，distance metric：**cosine**
- SDK：boto3 `s3vectors` client（`create_index` / `put_vectors` / `query_vectors`）
- metadata filter 语法：类 MongoDB（`$eq` 等），本测试用 `filter={"category": {"$eq": "tech"}}`
- API 参数格式均对照官方文档核实（PutVectors 要求 float32；QueryVectors 的 filter/returnMetadata/returnDistance）

> 说明：本目录只保留脚本 + 结果数据 + 结论。所有测试 bucket/index 测完已清理，不再计费。

---

## 实验一：5 个不同 index，各插 100 条 + filter 查询（`s3vectors_demo.py`）

每轮新建一个 index → batch 插入 100 条（一次 put_vectors 提交）→ filter+相似性查询。

| Round | CreateIndex | Batch Insert(100) | Filter Query |
|------:|------------:|------------------:|-------------:|
| 1 | 264 ms | 1983 ms | 279 ms |
| 2 | 271 ms | 1953 ms | 292 ms |
| 3 | 258 ms | 2014 ms | 301 ms |
| 4 | 258 ms | 2023 ms | 301 ms |
| 5 | 281 ms | 2019 ms | 320 ms |

- 插入 avg ≈ **1998 ms**（波动 <4%，非常稳定）
- 查询 avg ≈ **299 ms**
- **无明显首轮冷启动**（首轮 insert 1983ms 反而低于均值）——因为直连 API，没有容器冷启动环节。
- filter「边搜边过滤」正确：每轮稳定返回 10 条且全为 `category=tech`。

---

## 实验二：单个 index 插 10000 条（每批 500，共 20 批）+ 同一 index 跑 5 轮查询（`s3vectors_demo_v2.py`）

**插入（20 批 × 500）：**
- 第 1 批 **3320 ms**，后续 19 批稳定在 **~2000–2130 ms**
- 首批比后续多 **~1250 ms** —— 插入侧存在明显首批开销
- 总插入 43.1 s
- **关键发现：每批 500 条 ≈ 每批 100 条 也是 ~2s** → batch 延迟主要是固定的请求/服务端写入开销，与批内条数关系不大。**大 batch 更划算**（同样 ~2s 写 500 条而非 100 条）。

**查询（同一 index，5 轮）：**

| Round | Query Latency | |
|------:|--------------:|---|
| 1 | 413.5 ms | ← 首次(cold) |
| 2 | 382.5 ms | |
| 3 | 397.4 ms | |
| 4 | 402.8 ms | |
| 5 | 339.8 ms | |

- 首次 413.5 ms，热均值(2-5) 380.6 ms，**首次比热查询慢约 33 ms（+8.7%）**
- 结论：**首次查询确实略慢，但幅度小（接近正常抖动）**，不是强冷启动。第 5 轮甚至更快。

---

## 实验三：对照实验 — 首批插入慢是「建连接」还是「服务端首写初始化」？（`s3vectors_warmup_test.py`）

**背景问题**：S3 Vectors 有没有"建立连接"概念？首批慢是不是客户端建连接/懒加载的锅？

**设计**：两个独立进程，各是"进程内首次插入"，唯一区别是插入前有没有 warmup 请求。

| | 首批插入 | 热均值(2-5) | 首批-热 |
|---|---:|---:|---:|
| **Baseline（无 warmup）** | 3293 ms | 2065 ms | **+1228 ms** |
| **Warmup（先 query 预热）** | 3237 ms | 2055 ms | **+1181 ms** |

（warmup query 本身耗 466 ms，已走完 TCP/TLS 握手 + botocore 懒加载）

### 结论（实测，非推测）

1. **warmup 几乎没消除首批插入的慢**：有/无 warmup 首批基本一样慢（差 56ms，在抖动内），都比热均值多 ~1200ms。
2. **首批插入慢来自服务端**，是 S3 Vectors 对该 index **首次执行 put_vectors 时的服务端初始化开销**（首次写入时后端为该 index 分配/初始化存储或索引结构），**客户端 warmup / 连接池消除不了**。
3. 用 query 预热无法替代"首次 put 的服务端初始化"（warmup 走的是 query 路径，不是 put）。

### 关于「连接」概念的澄清

- **S3 Vectors 没有数据库式的"连接会话"**：它是无状态 HTTPS/REST API（和 S3 一样，每次请求 SigV4 签名打到区域 endpoint），不需要先 `connect()` 建有状态会话。
- **boto3 底层有连接池**（urllib3 keep-alive 复用 TCP/TLS）：第一次请求付 DNS+TCP+TLS 握手成本，后续同 client 复用。可用 `Config(max_pool_connections=N)` 调池大小（高并发时有意义）。
- **但首批插入慢 ≠ 建连接**：实测证明它是服务端首写初始化，与客户端连接/连接池无关。

---

## 综合要点

- **插入**：冷启动集中在"该 index 的首次 put"（首批 +1200ms），之后稳定 ~2s/批（500 条）。
- **查询**：几乎无冷启动（首次仅 +33ms，在抖动范围）。
- **大 batch 更高效**：100 条与 500 条每批都约 2s，批越大单位成本越低（受限于单请求条数/大小上限，见官方 Limitations）。
- **S3 Vectors 是无状态 API + 连接池**，不是长连接数据库；连接层不是首批插入慢的原因。

## 文件

- `s3vectors_demo.py` — 实验一（5 index × 100 条）
- `s3vectors_demo_v2.py` — 实验二（单 index 10000 条 + 5 轮查询）
- `s3vectors_warmup_test.py` — 实验三（warmup 对照）
- `s3vectors_demo_result.json` / `s3vectors_demo_v2_result.json` — 原始结果数据

## 复现

```bash
pip install boto3 numpy
AWS_DEFAULT_REGION=us-east-2 python3 s3vectors_demo.py
AWS_DEFAULT_REGION=us-east-2 python3 s3vectors_demo_v2.py
# warmup 对照（两个独立进程）
B=$(AWS_DEFAULT_REGION=us-east-2 python3 s3vectors_warmup_test.py --mkbucket)
AWS_DEFAULT_REGION=us-east-2 python3 s3vectors_warmup_test.py baseline $B
AWS_DEFAULT_REGION=us-east-2 python3 s3vectors_warmup_test.py warmup   $B
AWS_DEFAULT_REGION=us-east-2 python3 s3vectors_warmup_test.py --cleanup $B
```

_测试日期：2026-08-24 · region us-east-2 · S3 Vectors GA_
