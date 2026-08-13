# Mountpoint-S3 OTLP 指标监控（独立部署）

部署日期：2026-07-27
**与现有 EBS `node_ebs_*` / Grafana id=43 dashboard 完全独立，零干扰。**

## 架构

```
MySQL-Master (<MOUNT_HOST_IP> / <MOUNT_HOST_INSTANCE_ID>)
  mount-s3 1.23.0  挂载 <YOUR_BUCKET> → /mnt/mp-s3
  --otlp-endpoint http://<MONITOR_HOST_IP>:9091/api/v1/otlp
  --otlp-export-interval 15
        │  OTLP/HTTP (exponential histogram + delta temporality)
        ▼
Monitor (<MONITOR_HOST_IP> / <MONITOR_HOST_INSTANCE_ID>)
  Prometheus 3.13.1  :9091   ← 新增，独立
  Grafana    13.1.1  :3001   ← 新增，独立
```

## 访问

| 服务 | 地址 | 凭据 |
|---|---|---|
| 新 Grafana | http://<MONITOR_HOST_IP>:3001 | admin / `<GRAFANA_PASSWORD>` |
| Dashboard | `/d/mountpoint-s3-otlp/` | — |
| 新 Prometheus | http://<MONITOR_HOST_IP>:9091 | — |

## 与现有系统的隔离（已验证）

| 组件 | 旧（未动） | 新（本次） |
|---|---|---|
| Prometheus | 2.37.1 :9090，60+ scrape jobs | **3.13.1 :9091，0 scrape job，仅 OTLP 接收** |
| Grafana | 7.5.9 :3000，含 id=43 Disk Characteristics | **13.1.1 :3001，独立 grafana-mp.db** |
| TSDB | `<HOME>/prom/data` | `<HOME>/prom-mp/data` |
| 指标命名空间 | `node_ebs_*` | `fuse_*` / `s3_*` / `process_*` |
| systemd unit | `prometheus` / `grafana-server` | `prometheus-mp` / `grafana-mp` |

验证：部署后 `count(node_ebs_read_ops_total)` 在 :9090 仍返回 6，老服务全部 active。

## 关键版本要求（官方文档 METRICS.md）

- **mount-s3 ≥ 1.21.0** — OTLP 支持在 v1.21.0 (2025-10-30) 引入。原装 1.15.0 无 `--otlp-endpoint`，已升级到 1.23.0
- **Prometheus ≥ 3.0** + 必须带这两个 flag，否则 histogram 数据被丢弃/误读：
  ```
  --web.enable-otlp-receiver
  --enable-feature=native-histograms,otlp-deltatocumulative
  ```
- **Grafana** — 7.5.9 不支持 native histogram，需新版（用 13.1.1）

## 指标清单（实测确认存在）

Mountpoint 发的是 **exponential histogram**，所以 `histogram_quantile()` 出的是真分位数，不是估算。

| Prometheus 指标名 | 类型 | 维度 |
|---|---|---|
| `fuse_request_latency_microseconds` | native histogram | `fuse_request` |
| `fuse_io_size_bytes` | native histogram | `fuse_request` |
| `fuse_request_errors_total` | counter | `fuse_request` |
| `s3_request_first_byte_latency_microseconds` | native histogram | `s3_request` |
| `s3_request_total_latency_microseconds` | native histogram | `s3_request` |
| `s3_request_count_total` | counter | `s3_request` |
| `s3_request_errors_total` | counter | `s3_request`, `http_status` |
| `process_memory_usage_bytes` | gauge | — |
| `experimental_fuse_idle_threads` | native histogram | — |
| `experimental_fuse_total_threads_ratio` | gauge | — |

注：OTel 的 `fuse.request_latency` → Prometheus 转成下划线并追加单位后缀。

## Dashboard 内容（29 panel / 5 row，v3 — 2026-07-27 负载测试后修订）

> **v3 修订说明**：真实负载压测（轻 10MB/s vs 重 550MB/s）暴露出多个面板会给出**错误结论**，已全部修正。
> **关键认知：dashboard 不做真实负载压测就不知道哪些面板在骗人** —— 轻负载下这些问题全都看不出来
> （404 只有几十次、读没有缓存命中差异、线程池永远空闲、TTFB/TOTAL 比值接近 1）。

### v3 修改清单

| # | 面板 | 原问题（实测证据） | 处置 |
|---|---|---|---|
| 1 | `S3 errors/s` | 把良性 404 + `-1` 与真 5xx 混加，显示 0.4/s 而 **S3 实际零故障** → 我本人被它误导 | 拆成 **`S3 real errors/s`**（`{http_status!~"404\|-1"}`）+ 独立的良性事件面板；加红色阈值 |
| 2 | `Throughput (FUSE)` | 读阶段显示 64 MB/s，fio 应用侧实际 **437 MB/s**（低报 6.8 倍，页缓存命中不下发 FUSE） | 改名 **`Throughput (FUSE layer only)`** + description 警告"不可用于容量规划" |
| 3 | `FUSE worker threads` | ①`experimental_fuse_total_threads_ratio` **查询恒为 no data**（死线）②`idle_threads` 套了 `rate()`，但它是瞬时分布不是累积量 | 删死线；改为**不套 rate** 的 `histogram_avg` / `histogram_quantile(0.01)`（最坏情况）/ `16 - avg`（实际在用） |
| 4 | — | **缺 TTFB÷TOTAL 比值**，本次最有诊断价值的指标却要人心算 | **新增 `S3 bottleneck indicator`**，对数轴 + 8x 阈值线 |
| 5 | `latency percentiles` | `histogram_avg` 在 p99/p50=855 倍的双峰分布下读起来"很健康"，掩盖长尾 | 默认**隐藏 avg 线**（保留在 legend 表）；新增 **p99.99** |
| 6 | `p99 by request type` | 同图跨 **5 个数量级**（getattr 29µs ↔ flush 2,133,810µs），线性轴下快的 op 全压成贴地线 | 改**对数轴 log10** |
| 7 | `ops/s by request type` | 单看会误判重要性：write 504 ops/s vs flush 0.2 ops/s（2500 倍），但 flush 才最慢 | 新增 **`FUSE time contribution`** 面板（`histogram_sum` 而非 `histogram_count`，反映墙钟时间真正花在哪） |
| 8 | `S3 errors by API/status` | **设计正确，是它救了我**（能看到 404/-1 而非一个总数） | 保留原面板；并把良性事件视图**上移到 Overview** 显眼位置 |
| + | — | flush 是最慢 op 却没有专属视图 | 新增 **flush latency heatmap** |
| + | S3 TTFB / TOTAL percentiles | 跨数量级 | 改对数轴 log2 |

所有面板的 description 里都写入了实测数值作为基准线，便于日后对照判断"现在算不算异常"。

### 表达式验证
39 条 PromQL 全部对实测窗口（重写阶段 07:15 UTC）验证：**0 解析错误，33 有数据，6 个 NODATA 均为预期**
（FUSE errors 全程为零 = 好事；`{http_status!~"404|-1"}` 为零 = 真无错误；read heatmap 在写窗口自然无数据；RSS gauge 瞬时点无样本）。
⚠️ 注意：**stacking + 对数轴不能同时用**（渲染异常），stacked 面板保持线性轴。

### v4 修正（15 分钟混合读写验证后 —— 有两处我 v3 判断错了）

改完必须验证。第二轮特意跑**混合读写**（2 个 O_WRONLY writer + fio 两个 reader 分别用 1M/64K 块，15 min，
16:27:36–16:42:37），因为上一轮读写分离导致很多面板在各自窗口里是空的、压不出真实情况。

**改动全部验证有效：**

| 面板 | 验证结果 |
|---|---|
| 1 拆分错误 | **新旧对比铁证**：旧混合面板 **0.8 e/s**（UploadPart/-1 0.5 + HeadObject/404 0.2 + Unknown/-1 0.1），新 `real errors` = **NODATA**。 |
| 3 线程池 | 新增的 `p1 idle` **证明了价值**：avg idle 11.0 看着很闲，**p1 idle 已掉到 4.0**（告警阈值 3）。上轮读写分离最坏只到 10.4，混合负载才压出来。**平均值会掩盖瞬时饱和。** |
| 4 瓶颈比值 | 全 6 个 API 都有数据：GetObject **15.2x** / ListObjectsV2 13.8x / UploadPart 8.5x / HeadObject 7.6x / CreateMPU 5.0x / CompleteMPU 2.7x。**`MountpointS3LocalBottleneck` 正确 firing** —— 全天唯一一条告警，且判断正确（c6i.xlarge 带宽被打满）。8x 阈值定得准。 |
| 5 隐藏 avg | p50 **63.8** µs 而 avg **1,670** µs（**26 倍**）→ avg 既不描述典型请求也不描述最坏请求，隐藏它是对的。新增 p99.99 = 1,226,967 µs = **p50 的 19,231 倍**。 |
| 6 对数轴 | 混合负载下出现 **11 个 op**，跨度 releasedir 26 µs ↔ flush 1,931,987 µs = **74,307 倍**。线性轴下 8 个 op 完全贴地。 |
| 7 时间贡献度 | **结论只有这个面板能给**：flush 用 **0.017% 的请求量（0.5 ops/s）吃掉 11% 的墙钟时间**（673,281 µs/s）；read 66%（4,042,068 µs/s / 2932 ops/s）。 |

**⚠️ v3 的两处判断错误（已修正）：**

1. **`experimental_fuse_total_threads_ratio` 不是"死线"。** 它**有数据，恒等于 16**（= `--max-threads` 默认值）。
   v3 我查它返回 no data 是因为用了**瞬时 `query` 且时间点落在样本间隙**，不是指标不存在。
   → 面板里仍然不放它（值恒定、信息量为零），但 **v3 写在 description 里的 "dead series, needs upstream check" 是错误信息，已删除**。
   **教训：判断"指标没数据"必须用 `query_range` 而不是单点 `query`。**
2. **读 IO 拆分不是固定 ~256KB。** 实测随**应用 block size 和并发情况**变化：
   - 单个 1MiB 顺序读：p50 **249 KB** / avg 213 KB
   - 加入 64K reader + 并发写之后：p50 **4 KB** / avg 74 KB
   → v3 文档写"读被拆成 ~256KB"太绝对，已改为"比例可变，不要当常数"。
   同理 **FUSE 吞吐低报倍数也不固定**：读密集 **6.8x**（64 vs 437 MB/s），混合读写 **1.7x**（474 vs ~787 MB/s）——
   倍数跟缓存命中率走，**这个面板只能当下限看**。

所有 description 已按两轮实测数据更新（Grafana version 4）。

### 原始 5 行结构


1. **Overview** — FUSE ops/s、S3 req/s、吞吐、错误率、RSS（6 stat）
2. **FUSE Request Latency** — 总延迟 heatmap + p50/p90/p99/p99.9 曲线 + 按 op 类型分解 + read/write 各自 heatmap
3. **FUSE IO Size** — IO 大小分布 heatmap（看小 IO vs 大 IO 混合比）+ 分位数 + 按类型吞吐
4. **S3 API Requests** — TTFB heatmap + total latency heatmap + 按 API 分位数 + 错误分解
5. **Mountpoint Internals** — FUSE 线程池饱和度、内存、错误

## 实测基线数据（2026-07-27 负载测试）

顺序读 8M×300 = **826 MB/s**

FUSE p99 延迟（µs）：
| op | p99 |
|---|---|
| getattr | 27.9 |
| ioctl | 18.8 |
| statfs | 31.4 |
| release | 178 |
| open | 30,336 |
| lookup | 42,513 |
| read | 59,047 |
| flush | 214,037 |

S3 TTFB p99（µs）：HeadObject 15,812 / ListObjectsV2 29,615 / GetObject 52,996

## 三态性能对照（2026-07-27 完整实测）

三组负载在同一挂载点（MySQL-Master c6i.xlarge, 4 vCPU / 7.8 GB）上跑：

| | 轻负载 | 重负载-写 | 重负载-读 |
|---|---|---|---|
| 方式 | 限速 writer + fio 各 10 MB/s，1 线程 | 4 workers × 8 MiB，全速 30 min | fio 4 jobs × 1 MiB，全速 30 min |
| 实测吞吐 | 10.00 MB/s（精确限速） | **1,038 GB / ~550 MB/s 聚合** | **437 MB/s（fio 侧）** |
| 时间窗 | 06:23:48–06:43:49 | 07:03:08–07:33:09 | 07:57:08–08:27:09 |

### FUSE 延迟 p99 对照（µs）

| op | 轻负载 | 重负载-写 | 倍数 |
|---|---|---|---|
| write | 304 | 185,132 | 609x |
| read | 211 | 75,932 (读阶段) | 360x |
| open | 32 | 851,708 | **26,616x** |
| lookup | 34,204 | 950,504 | 28x |
| flush | 155,737 | **2,133,810 (2.13 s)** | 14x |
| release | 23 | 65 | 2.8x |
| getattr | — | 29 | — |

**全局分位数（重负载-写）**：p50 250 µs / p90 471 µs / **p99 213,634 µs** → **p99 是 p50 的 855 倍**。

### S3 API TTFB vs TOTAL（重负载-写，p99 µs）

| API | TTFB p99 | TOTAL p99 | 比值 |
|---|---|---|---|
| UploadPart | 137,637 | **1,344,251** | 9.8x |
| CompleteMultipartUpload | 162,104 | 840,711 | 5.2x |
| CreateMultipartUpload | 56,291 | 706,033 | 12.5x |
| HeadObject | 42,238 | 678,936 | 16.1x |
| ListObjectsV2 | 36,754 | 678,446 | 18.5x |
| GetObject（读阶段） | 80,196 | **2,096,244** | **26.1x** |

**RSS**：轻负载 80 MB → 写 617 MB → 读 **978 MB**（12 倍增长，读比写更吃内存）。
**FUSE idle threads**（`--max-threads` 默认 16）：写 14.0 / 读 10.4 → 线程池未饱和。

## 指标解读要点（实测得出，非推测）

1. **p99 是 p50 的 855 倍** — 平均值/p50 在对象存储文件网关场景几乎无诊断价值。native histogram 出的是真分位数，这是本方案相比传统 counter 的核心价值。
2. **TTFB ÷ TOTAL 比值 = 瓶颈定位器**
   - TTFB 高 + TOTAL 高（比值≈1）→ S3 服务端慢 / 网络 RTT 问题
   - **TTFB 正常 + TOTAL 高（比值大）→ 本地瓶颈**（带宽饱和、并发挤占）
   - 本次 UploadPart TTFB 138 ms（与轻负载 158 ms 基本一致，**S3 没退化**）但 TOTAL 1.34 s → 瓶颈在实例带宽。**若无这两个指标分开，会误判"S3 变慢"去查限流，白费功夫。**
3. **延迟排序：flush ≫ lookup ≈ open ≫ write ≫ getattr**。flush（close 时等 CompleteMultipartUpload）p99 达 2.13 s，是 S3 对象语义的固有代价，轻负载下也有 156 ms，降不下来。**频繁 open/close 小文件的应用感受到的是秒级延迟，不是 write 显示的 185 ms。**
4. **ops 数量与延迟严重不成比例** — flush 仅占 0.2 ops/s（0.04% 请求量）却是最慢的 op。**按请求数加权的平均延迟会把它完全稀释掉，只有 per-op 分位数能暴露。**
5. **FUSE 层的吞吐/IO 大小 ≠ 应用侧数值**
   - 写：1 MiB 请求 1:1 透传（avg 1,024 KB）
   - **读：被内核拆成 ~256 KB（p50 249 KB / avg 213 KB）**
   - 读阶段 fio 应用侧 **437 MB/s**，FUSE 层只显示 **64 MB/s**，差 **6.8 倍** —— 页缓存命中的读根本不下发到 FUSE。**做容量规划别直接用 FUSE 吞吐。**
6. **换算自验证**：63 req/s UploadPart × 8 MB/part = 504 MB/s，与 FUSE 写吞吐完全吻合 → 印证默认分片 8 MiB 且无重传浪费。

## 分片大小与关键可调参数（mount-s3 1.23.0 `--help` 实测）

8 MiB 分片**是默认值，不是 hard code**，挂载时可指定：

```
--part-size <SIZE>         多段 GET+PUT 分片大小 [default: 8388608 = 8 MiB]  ← 总开关
--read-part-size <SIZE>    仅 GET  [default: 8388608]
--write-part-size <SIZE>   仅 PUT  [default: 8388608]
--maximum-throughput-gbps <N>   [default: EC2 上自动探测，其他环境 10 Gbps]
--max-threads <N>          FUSE 守护线程数 [default: 16]   ← 对应 idle threads 峰值 16
```

用法：`mount-s3 bucket /mnt/x --part-size 16777216` 或读写分设
`--read-part-size 8388608 --write-part-size 33554432`。

调优思路：本次 1,038 GB 用 8 MiB 分片 → 约 113,000 次 UploadPart。改 32 MiB 可把请求数降到 1/4（S3 请求费用同比下降）。
⚠️ **未实测**大分片对吞吐/内存的影响（RSS 已到 978 MB，分片越大缓冲越多）。S3 协议本身限制单 part 5 MiB–5 GiB、最多 10,000 part；**Mountpoint 自身是否有额外取值范围限制，`--help` 未写明，未确证**。

## 【重要】"S3 错误"的真实成因 —— debug 日志实证，推翻推测

`s3_request_errors_total` 有两组性质完全不同的序列，**聚合看会严重误判**：

```
{s3_request="HeadObject", http_status="404"}   ← POSIX O_CREAT 存在性检查
{s3_request="HeadObject", http_status="-1"}    ← Mountpoint 主动取消（去重）
```

### 开 `--debug --debug-crt` 跑 8 分钟高并发写（359 GB）的实证

```
CRT 错误码统计:
  14343 (Invalid response status)  149 次  → 全部 response status=404
  14347 (AWS_ERROR_S3_CANCELED)     19 次  → 全部 response status=0

Mountpoint 层取消计数:
  s3.request_canceled[s3_request=HeadObject]  20 次
  s3.request_canceled[UploadPart]              0 次   ← 一次都没有

所有被取消的请求按 operation:  HeadObject 21 次（100%）

按 operation 的最终状态:
  UploadPart               42,865 次  crt_error=None  http_status=200   ← 全部成功
  HeadObject                  336 次  crt_error=None  http_status=200
  CreateMultipartUpload       170 次  crt_error=None  http_status=200
  CompleteMultipartUpload     170 次  crt_error=None  http_status=200
  AbortMultipartUpload          0 次
```

**结论（已确证）**：
1. **404 = S3 正确工作**。`O_CREAT` 要求判断文件是否存在，S3 无"存在性"概念，Mountpoint 只能发 HeadObject，对象不存在时 S3 按协议返回 404。数量与文件创建次数成正比（本次 writer 循环约 486 次创建 ↔ 420 次 404，量级吻合）。
2. **`-1` = Mountpoint 主动取消重复的 HeadObject，是去重优化不是故障**。日志原文：
   ```
   lookup{name="fio-debug" pid=6281}:head_object{key="fio-debug"}:
     S3 request canceled operation_name="HeadObject"
     crt_error=Some(Error(14347, "aws-c-s3: AWS_ERROR_S3_CANCELED, Request successfully cancelled"))
     duration=326.6ms  ttfb=None
   ```
   CRT 自己的措辞是 **"Request successfully cancelled"**。`response status=0`（无 HTTP 状态码）映射到指标即 `http_status="-1"`。
   触发场景：4 个 writer 进程（pid 6280/6281/6282）**并发对同一目录做 lookup**，Mountpoint 取消重复请求。
   ⚠️ 触发取消的**确切内部条件官方文档未说明**，以上是基于 `lookup → head_object → canceled` 调用链与多进程并发同路径时序的推断，严格确证需读源码。
3. **写路径 100% 干净**：UploadPart 零错误零取消，零 503（无限流）、零 5xx、零 FUSE 错误。

**血泪教训**：第一轮我按 `sum by (s3_request)` 聚合，误报成"UploadPart 出现 485 次 -1"并推测是"长连接中断/客户端超时"，**全错**。
→ **指标名带 "errors" 不代表真有错误；下钻到 http_status + debug 日志才能确定语义。第一时间就该开 debug 而不是给推测。**

顺带两个无害项：
- `getxattr security.capability: operation not supported` — 内核例行询问，Mountpoint 不支持 xattr（同 `shutil.copy2()` errno 524 之源）
- 启动时 `Failed to resolve role arn during sts web identity provider initialization` — 凭据链依次尝试，最终走 EC2 instance profile 成功

## 告警规则（已部署，9 条 / 3 组）

文件：`<HOME>/prom-mp/rules/mountpoint_s3_alerts.yml`，`prometheus.yml` 加 `rule_files: <HOME>/prom-mp/rules/*.yml`。
**设计核心：404 完全不告警，`-1` 仅降级为 info**（已被上述实证验证）。

| 级别 | 告警名 | 条件 | 处置 |
|---|---|---|---|
| critical | MountpointFuseErrors | `sum(rate(fuse_request_errors_total[5m])) > 0` | **最高信号**，应用真的见到 IO 错误 |
| critical | MountpointS3Throttled | `{http_status="503"}` > 0 | S3 限流 → 降并发 / 打散 prefix |
| critical | MountpointS3ServerErrors | `{http_status=~"5.."}` > 0.1/s | S3 服务端故障 |
| warning | MountpointMemoryHigh | RSS > 2 GiB | 小实例 OOM 风险（实测已到 978 MB） |
| warning | MountpointFuseThreadPoolSaturated | `histogram_avg(experimental_fuse_idle_threads) < 3` | 调大 `--max-threads` |
| warning | MountpointFuseLatencyP99High | 全局 FUSE p99 > 1 s | 实测负载下 214 ms，1 s 即劣化 |
| warning | MountpointFlushLatencyHigh | flush p99 > 5 s | close() 卡在 CompleteMultipartUpload |
| warning | MountpointS3LocalBottleneck | TOTAL p99 ÷ TTFB p99 > 8x | **本地带宽瓶颈，不是 S3 慢** |
| info | MountpointS3NoResponseElevated | `{http_status="-1"}` > 5/s | 已确认是去重取消，仅提示 |

验证：`promtool check rules/config` 双 SUCCESS；9 条全部 `health=ok / state=inactive`（零误报）。

**顺带修复**：原 unit 缺 `--web.enable-lifecycle`，`POST /-/reload` 返回 403 只能 SIGHUP。已补该 flag（unit 已备份），现 reload 返回 **200**。

## 常用查询

```promql
# FUSE 延迟真分位数（按 op 分解）
histogram_quantile(0.99, sum by (fuse_request) (rate(fuse_request_latency_microseconds[5m])))

# FUSE 吞吐
sum by (fuse_request) (histogram_sum(rate(fuse_io_size_bytes[5m])))

# FUSE ops/s
sum by (fuse_request) (histogram_count(rate(fuse_request_latency_microseconds[5m])))

# 平均 IO 大小
histogram_avg(sum by (fuse_request) (rate(fuse_io_size_bytes[5m])))

# S3 TTFB p99
histogram_quantile(0.99, sum by (s3_request) (rate(s3_request_first_byte_latency_microseconds[5m])))

# heatmap（Grafana 里 format 选 heatmap）
sum(rate(fuse_request_latency_microseconds[$__rate_interval]))
```

## 踩坑记录

1. **Grafana ini 密码含 `#` 被当注释截断** — `admin_password = <PWD_WITH_HASH>` 导致 401 Invalid username or password。`#` 在 ini 里是注释符，密码被截成 `<PWD_TRUNCATED>`。改成无 `#` 的密码 + `grafana cli admin reset-admin-password` 重置。**Grafana custom.ini 里的密码不要用 `#`。**
2. **mount-s3 1.15.0 无 OTLP** — `--help | grep otlp` 空。OTLP 是 v1.21.0 才有的，必须升级。
3. **AWS CLI `--parameters commands=` 解析带引号/分号的 shell 脚本会失败** — 改用 `--cli-input-json` 传完整 JSON payload（用 python 生成）。
4. **AL2 glibc 2.26 能跑 Grafana 13.1.1** — 实测 OK，不用降版本。
5. **`histogram_sum` 对非 native histogram 返回空** — 确认指标真是 native histogram（查 `/api/v1/query` 返回里有 `"histogram"` 字段而非 `"value"`）。
6. **native histogram 的 `rate()` 窗口不能开太大** — delta→cumulative 转换在负载间隙会产生 counter reset，`[5m]` 窗口跨过空闲间隙会**直接返回空**（看着像数据丢了，其实数据在）。用 `[2m]~[3m]` + `query_range` 取中位数才稳。
7. **`systemctl show -p X --value` 在 AL2 旧 systemd 上不支持** — 报 `unrecognized option '--value'`，取 PID 改用 `pgrep -f`。
8. **`--debug --debug-crt` 日志极其暴力** — 8 分钟高并发写产生 **449 MB** 日志（含每个请求的 SigV4 签名全文）。排查完必须删掉并还原 unit，否则磁盘很快撑爆。只保留 grep 后的证据行即可。

## fio 在 Mountpoint-S3 上的 4 个坑（2026-07-27 血泪，全部实测）

1. **fio 根本不能做写测试** — fio 一律用 **`O_RDWR`** 打开目标文件（strace 确认：`openat(..., O_RDWR|O_CREAT, 0600)`），而 **Mountpoint 只接受写只句柄（`O_WRONLY`）** → 直接 `errno 9: file handle is not open for writes`。
   → **写测试必须自己写 O_WRONLY 的 writer**（本次用 python `os.open(path, O_WRONLY|O_CREAT|O_TRUNC)`）。
2. **必须加 `--fallocate=none`** — Mountpoint 不支持 fallocate，否则 `fio: posix_fallocate fails: Invalid argument`。日志：`fallocate failed: operation not supported by Mountpoint`。
3. **残留 fio 进程会导致 EBADF** — 前次失败的 fio 没退干净，与新进程并发写同一文件，Mountpoint 不允许 → `write failed with errno 9`。新测试前先 `pkill -9 -f 'fio --name'` 并确认 `pgrep` 为空。
4. **读测试用 `filename_format` 指向已有文件时必须显式给 `--size=`** — 否则 fio 靠 `total_file_size()` 推断，遇到 **0 字节文件**直接 `err=22 func=total_file_size` 整个 job 失败。
   **最坑的是：失败后 fio 进程不退出、只是挂住**，`pgrep` 看着像在正常跑 —— 本次因此白等了 23 分钟。**必须查 log 才知道它其实什么都没做。**
   （0 字节文件的来源：writer 在 `O_TRUNC` 后、还没写完就到时限退出。）

另：Mountpoint 不支持**乱序写**，`write failed with errno 22: out-of-order write is NOT supported by Mountpoint, aborting the upload; expected offset X but got Y` —— writer 必须严格顺序追加。

## 文件

- `mountpoint_dashboard.py` — dashboard 生成脚本（工作区）
- `mountpoint_dashboard.json` — 生成的 dashboard JSON
- 监控机：`<HOME>/prom-mp/`（Prometheus）、`<HOME>/grafana-mp/`（Grafana）
- MySQL-Master：`/etc/systemd/system/mount-s3-otlp.service`，日志 `/var/log/mount-s3/`

## 运维

```bash
# 监控机
systemctl status prometheus-mp grafana-mp
journalctl -u prometheus-mp -f

# MySQL-Master
systemctl status mount-s3-otlp
mount | grep mp-s3

# 改导出间隔：编辑 --otlp-export-interval 后
systemctl daemon-reload && systemctl restart mount-s3-otlp
```
