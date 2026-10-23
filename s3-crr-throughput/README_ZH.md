# S3 跨区域复制（CRR）+ Batch Replication 2 TiB 吞吐实测：Ohio → Oregon（1/2/4 条前缀规则、多目标桶，12 次交替重复运行）

> 实测日期：2026-10-23（UTC 12:26～15:35）。源 us-east-2，目标 us-west-2。AWS CLI + s5cmd v2.3.0。
> 口径：MB = 10^6 字节，GB = 10^9 字节；费用按 GiB 计。
> 脚本在 [`scripts/`](scripts/)，每次运行的原始数据在 [`raw/`](raw/)。新加坡 → 东京的单独测试见 [`sg-tokyo/RESULTS_ZH.md`](sg-tokyo/RESULTS_ZH.md)。

## 1. 结论速览

### 1.1 按场景汇总（每个场景 3 次）

| 场景 | 配置 | 端到端 s 均值 [最小–最大] | 同场景极差 s | Batch Active s 均值 [最小–最大] | MB/s（端到端口径）均值 | 1 分钟峰值 MB/s 均值 [最小–最大]（只算 CloudWatch 数据完整的运行） | 峰值 PUT/min 均值 | 失败 |
|---|---|---|---|---|---|---|---|---|
| **A** | 1 规则 → 1 桶，1 个 job | **322** [294–338] | 44 | 266 [236–284] | 6,856 | 12,130 [10,084–14,175]（n=2）；A1 数据有缺口，但峰值分钟 16,257 | 43,394 | 0 |
| **B** | 2 规则 → 1 桶，2 个 job | **301** [286–321] | 34 | 252 [239–265] | 7,313 | 11,499 [10,175–12,822]（n=2） | 41,124 | 0 |
| **C** | 4 规则 → 1 桶，4 个 job | **301** [268–331] | 62 | 253 [218–283] | 7,354 | 13,691 [10,650–16,688]（n=3） | 48,963 | 0 |
| **D** | 4 规则 → **4 个桶**，4 个 job | **312** [302–327] | 25 | 265 [256–282] | 7,057 | 12,119 [10,575–13,662]（n=2）；D1 数据有缺口，峰值 11,092 | 43,344 | 0 |

12 次运行的端到端：均值 **309 s**，标准差 21 s，范围 268–338 s。12 次全部 `Complete`，失败任务 0。目标桶 key+size 与源逐条比对：缺失 0、多余 0。

### 1.2 核心结论（已实测）

1. **多 prefix 多 job（B/C）的端到端只比 A 短约 20 s（约 6.5%），这个差距在同配置重复跑的波动范围内，不能算真提升。** A 平均 322 s，B、C 都是 301 s，D 312 s。但同场景 3 次的极差有 25～62 s（A 44 s、C 62 s），标准差 13～31 s。n=3 的 Welch t 检验：A vs B t≈1.19，A vs C t≈0.91，A vs D t≈0.63，都远不到显著。另外还有时段效应：第 1 轮（A1 B1 C1 D1）平均 323 s，第 2、3 轮都是 302 s，而 A1 正好排在最前面，拉高了 A 的均值。最快的一次是 C2（268 s），最慢的是 A1（338 s）；但 A3（294 s）比 C1（331 s）、C3（305 s）都快。
2. **数据面峰值不随 job 数变化。** 4 个场景 1 分钟峰值的区间完全重叠：A 10.1～14.2（A1 到 16.3）、B 10.2～12.8、C 10.7～16.7、D 10.6～13.7 GB/s。所有运行的写入形态都一样：大约 3～5 个 1 分钟桶，中间稳定段在 **~10～14 GB/s、每分钟 3.6～6 万个 PUT**。稳定段大致有两档，"~10 GB/s"（B1、D2、A2、C3、D1）和"~13～16 GB/s"（A1、C1 峰值分钟、C2、D3、A3、B3），但哪一档和场景无关，A/C/D 两档都出现过。
3. **D vs C：4 个目标桶合计的峰值没有突破 ~14 GB/s，最高 13.7 GB/s（D3），反而单目标桶的 C1 跑到了 16.7 GB/s、A1 到了 16.3 GB/s。** D 场景每个目标桶单独的峰值只有 **3.6～4.7 GB/s**。所以"单个目标桶写入"不是瓶颈：一个目标桶就能吃下 16 GB/s 以上，拆成 4 个桶也没让合计更高。
   - 推测（未实测）：上限更像是**账号/区域级的 Batch Operations 或复制服务端并发配额**（这个源桶/账号的 Batch Replication 总并发在 ~1,000 对象/s 左右，即 16 MiB 对象下的 ~10～16 GB/s），拆成多个 job/规则/目标桶只是分摊同一份额度。也可能是源桶读取侧、跨区链路或其他服务端限制，这次测试分不出来。要确认，需要用两个**不同源桶**（或不同账号）同时跑来对比，本轮没做。
4. **端到端时间的构成很稳定**：manifest 生成和准备 31～36 s（Preparing → Active），每个 job 的 `wall − Active` 固定是 46～58 s（准备 + Completing），数据面 3～5 分钟。"数据已写完、job 还挂在 Active 状态"的尾巴，12 次里只有一次比较明显：D3 的 job0 剩最后 4 个对象，多拖了约 70 s（数据窗口结束 → 最后一个 job 终止 = 72 s），其余 11 次尾巴都在 25 s 以内。
5. **一句话：** 2 TiB / 131,072 × 16 MiB，Ohio → Oregon 的 Batch Replication 端到端稳定在 **~4.5～5.6 分钟（均值 309 s，约 7.1 GB/s）**，数据面峰值 ~10～16 GB/s。**规则拆成 1/2/4 条、job 拆成 1/2/4 个、目标桶拆成 1/4 个，都没有可测量的加速**，成本几乎也一样（多一个 job 只多 $0.25）。

## 2. 环境

| 项 | 值 |
|---|---|
| 源桶 | `s3-crr-src-1792758433`，us-east-2，Versioning=Enabled，SSE-S3 默认加密 |
| 目标桶 | 每次运行都新建：A/B/C 用 `s3-crr-dst-<run>-<E>`，D 用 `s3-crr-dst-<run>-{0..3}-<E>`（共 20 个桶），us-west-2，Versioning=Enabled，开 1 分钟 request metrics（`Id=all`） |
| 数据 | 131,072 × 16 MiB = 2,199,023,255,552 B（2 TiB）。同一个 `/dev/urandom` 源文件（md5 `422abcb504aff66ba3ada464fa8b2305`）反复上传，单段上传 |
| Key 布局 | `g{0,1}/p{0..3}/<md5前2位>/obj_NNNNN`；p0、p1 在 g0 下，p2、p3 在 g1 下，每个 p 前缀 32,768 个对象 |
| 数据生成 | c7gn.16xlarge（us-east-2b，AL2023 arm64，默认 VPC 公有子网，显式 `AssociatePublicIpAddress`），user-data 跑 `scripts/gen_r2.sh`，s5cmd `--numworkers 1024`，**12:28:34 → 12:30:44，用时 130 s**（约 16.9 GB/s），131,072 个成功、0 错误；生成完 `shutdown -h`，实例随即 terminate（`InstanceInitiatedShutdownBehavior=terminate`） |
| 复制配置 | N 条规则，Priority 1..N，`DeleteMarkerReplication=Disabled`，`StorageClass=STANDARD`，开 Replication Metrics，**不开 RTC** |
| Batch 作业 | `S3ReplicateObject`，S3 自动生成 manifest（`S3JobManifestGenerator`），`EligibleForReplication=true` + `KeyNameConstraint.MatchAnyPrefix=[前缀]`（A 不加前缀）；**不按 ObjectReplicationStatuses 过滤**（官方文档 [Replicating existing objects with Batch Replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-batch-replication-batch.html)：不设 `ObjectReplicationStatuses` 时，所有符合规则的对象都会尝试复制，包括已复制过的。每次换新目标桶都需要这样做）；Priority=10，`--no-confirmation-required`，报告 FailedTasksOnly |
| 计时 | 每次 put-bucket-replication 后等 300 s 再建 job；describe-job 30 s 轮询；端到端 = 最早 `CreationTime` → 最晚 `TerminationDate`（API 返回值） |

### 2.1 D 场景的官方依据
- [Replicating objects within and across Regions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html)："You can replicate objects to a single destination bucket or to multiple destination buckets."；在 [replication-walkthrough-2](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication-walkthrough-2.html) 中也提到，复制规则定义了 "the destination bucket or buckets"，规则可以按 prefix 选对象子集。
- 实测：一个复制配置写 4 条规则，每条前缀指向不同目标桶，put-bucket-replication 成功；4 个 Batch job 各自把 32,768 个对象复制到对应的桶，4 个桶合起来 = 源（缺失 0）。

### 2.2 执行顺序（轮转，消除时段偏差）
```
第 1 轮: A1 B1 C1 D1   (12:41 → 13:27)
第 2 轮: B2 C2 D2 A2   (13:35 → 14:21)
第 3 轮: C3 D3 A3 B3   (14:29 → 15:14)
```
每次运行之间：上一次 job 全部 Complete → 校验 → 等 120 s 看目标桶 CloudWatch PUT/min（每次都已回落到 0～2 位数）→ 下一次 put-bucket-replication，在 300 s 传播等待期间删掉上一次的目标桶（全部版本 + 桶）。

### 2.3 测试中发现并处理的问题（如实记录）
- **request metrics 开启后要过一段时间才开始上报**（官方 [configure-request-metrics-bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/configure-request-metrics-bucket.html)："After about 15 minutes, CloudWatch begins tracking these request metrics"）。A1、B1、C1、D1、B2 这 5 次是建桶时才开 metrics，距 job 开始只有约 5 分钟：
  - B1、C1：CloudWatch 合计字节 = 100%，数据完整（运气好，指标开始上报得早）。
  - A1：97.7%（缺开头约 50 GB，12:42～12:43）；峰值分钟 12:45 是完整的。
  - D1：82.2%（缺 13:23 那一分钟）；13:24 以后完整。
  - **B2：只有 35.8%**（13:39 之前的数据都没有），峰值不可信，没算进峰值均值。
  - 发现后，13:33 我把 C2 及以后 7 次运行的目标桶都**提前建好并开 metrics**（`scripts/precreate_dst.sh`），距 job 开始 15～95 分钟，这 7 次覆盖率都是 100%。端到端、Active 时间来自 Batch API，不受这个问题影响。
- A 场景是全桶规则，`reports/` 下的 manifest/报告小文件也会被复制（A1 131,072、A2 131,135、A3 131,162 个任务，多出来的是前面几次运行的报告文件，字节可以忽略），B/C/D 都正好是 131,072 个。
- 源桶 `OperationsFailedReplication`（33 个规则维度的序列）在全程都是 0。

## 3. 原始数据（12 次运行）

### 3.1 每次运行
| # | 运行 | 场景 | job 数 | 首个 job 创建 (UTC) | 端到端 s | Active(max) s | MB/s（端到端） | MB/s（Active） | 数据窗口（首个 → 最后一个 PUT>1000/min 的分钟） | 尾巴 s | 1 分钟峰值 MB/s | 峰值 PUT/min | CW 覆盖率 | 任务数 / 失败 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A1 | A | 1 | 12:41:34 | 338 | 284 | 6,499 | 7,743 | 12:44–12:47（3 个分钟桶） | 12 | 16,257 ⚠️ | 58,144 | 97.7% | 131,072 / 0 |
| 2 | B1 | B | 2 | 12:55:13 | 321 | 265 | 6,858 | 8,298 | 12:56–13:01（5） | −25 | 10,175 | 36,391 | 100.0% | 131,072 / 0 |
| 3 | C1 | C | 4 | 13:08:37 | 331 | 283 | 6,651 | 7,770 | 13:09–13:14（5） | 8 | 16,688 | 59,681 | 100.0% | 131,072 / 0 |
| 4 | D1 | D | 4 | 13:22:21 | 302 | 256 | 7,283 | 8,590 | 13:24–13:27（3）⚠️ | 24 | 11,092 ⚠️ | 39,670 | 82.2% | 131,072 / 0 |
| 5 | B2 | B | 2 | 13:35:55 | 297 | 252 | 7,397 | 8,726 | 13:39–13:41（2）⚠️ | −7 | 10,894 ⚠️ | 38,965 | 35.8% | 131,072 / 0 |
| 6 | C2 | C | 4 | 13:48:47 | **268** | 218 | 8,199 | 10,087 | 13:49–13:53（4） | 15 | 13,735 | 49,121 | 100.0% | 131,072 / 0 |
| 7 | D2 | D | 4 | 14:01:52 | 307 | 257 | 7,161 | 8,557 | 14:02–14:07（5） | −1 | 10,575 | 37,822 | 100.0% | 131,072 / 0 |
| 8 | A2 | A | 1 | 14:15:26 | 334 | 278 | 6,591 | 7,910 | 14:16–14:21（5） | 0 | 10,084 | 36,066 | 100.0% | 131,135 / 0 |
| 9 | C3 | C | 4 | 14:29:03 | 305 | 257 | 7,213 | 8,557 | 14:29–14:34（5） | 8 | 10,650 | 38,088 | 100.0% | 131,072 / 0 |
| 10 | D3 | D | 4 | 14:42:44 | 327 | 282 | 6,726 | 7,798 | 14:43–14:47（4） | **72** | 13,662 | 48,865 | 100.0% | 131,072 / 0 |
| 11 | A3 | A | 1 | 14:56:20 | 294 | 236 | 7,477 | 9,318 | 14:57–15:01（4） | 14 | 14,175 | 50,723 | 100.0% | 131,162 / 0 |
| 12 | B3 | B | 2 | 15:09:25 | 286 | 239 | 7,685 | 9,201 | 15:10–15:14（4） | 11 | 12,822 | 45,858 | 100.0% | 131,072 / 0 |

字段说明：
- "数据窗口"按 1 分钟桶算，窗口结束 = 最后一个 >1000 PUT/min 分钟的结束时刻；"尾巴" = 窗口结束 → 最后一个 job 的 TerminationDate。负值表示 job 在那个分钟桶结束前就终止了（分钟桶粒度造成的）。
- ⚠️ = CloudWatch 数据有缺口（见 2.3）。
- MB/s（端到端） = 2,199,023 MB ÷ 端到端；MB/s（Active） = 2,199,023 MB ÷ max(ElapsedTimeInActiveSeconds)。

### 3.2 每个 job（describe-job）
```
run job wall(s)                    Active(s)
A1  [338]                          [284]
B1  [321, 306]                     [265, 260]
C1  [299, 299, 328, 311]           [253, 254, 283, 266]
D1  [265, 300, 289, 295]           [220, 256, 244, 247]
B2  [297, 295]                     [252, 247]
C2  [257, 254, 265, 262]           [211, 209, 212, 218]
D2  [297, 282, 300, 303]           [252, 237, 257, 257]
A2  [334]                          [278]
C3  [290, 303, 301, 299]           [245, 251, 257, 247]
D3  [327, 274, 268, 271]           [282, 228, 223, 227]
A3  [294]                          [236]
B3  [274, 285]                     [227, 239]
```
- 同一次运行内多个 job 的结束时间差 2～59 s，最慢的那个 job 决定端到端。
- Preparing/New → Active：A 31～32 s，B 33 s，C/D 36 s（30 s 轮询粒度，见 `raw/<run>/poll.log`）。

### 3.3 目标桶 CloudWatch 1 分钟写入（MB/s = BytesUploaded ÷ 60）
```
A1 12:44 41174 PUT 11,513 | 12:45 58144 16,257 | 12:46 28781 8,048 | 12:47 21 6
B1 12:55 709 198 | 12:56 24436 6,833 | 12:57 36391 10,175 | 12:58 36119 10,100 | 12:59 30353 8,487 | 13:00 3068 858
C1 13:09 8166 2,283 | 13:10 21808 6,097 | 13:11 29438 8,231 | 13:12 59681 16,688 | 13:13 11983 3,351
D1 13:24 39670 11,092 | 13:25 39126 10,940 | 13:26 28265 7,903 | 13:27 685 191      (13:23 缺数据)
B2 13:39 38965 10,894 | 13:40 7933 2,218                                          (13:36–13:38 缺数据)
C2 13:49 10069 2,815 | 13:50 45046 12,596 | 13:51 49121 13,735 | 13:52 26760 7,482 | 13:53 80 22
D2 14:02 6558 1,834 | 14:03 35001 9,787 | 14:04 37023 10,352 | 14:05 37822 10,575 | 14:06 14682 4,105
A2 14:16 14374 4,019 | 14:17 36066 10,084 | 14:18 35495 9,925 | 14:19 34729 9,700 | 14:20 10483 2,923 | 14:21 2 0
C3 14:29 3405 952 | 14:30 33172 9,275 | 14:31 38088 10,650 | 14:32 37537 10,496 | 14:33 18879 5,279
D3 14:43 10277 2,874 | 14:44 43207 12,081 | 14:45 48865 13,662 | 14:46 28351 7,927 | 14:47 384 107
A3 14:57 17975 5,026 | 14:58 41474 11,596 | 14:59 50723 14,175 | 15:00 21002 5,855 | 15:01 1 0
B3 15:09 55 15 | 15:10 21549 6,026 | 15:11 40416 11,301 | 15:12 45858 12,822 | 15:13 23191 6,484
```

### 3.4 D 场景每个目标桶（MB/s，逐分钟；桶 0..3 = g0/p0、g0/p1、g1/p2、g1/p3）
```
D1 13:24  3,572 1,478 3,729 2,313 = 11,092
   13:25  1,129 2,692 3,328 3,790 = 10,940
   13:26     50 4,139 1,378 2,337 =  7,903
D2 14:03  2,182 4,584 1,612 1,409 =  9,787
   14:04  4,150 2,116 2,979 1,107 = 10,352
   14:05  2,356   941 3,632 3,647 = 10,575
   14:06    325    45   883 2,852 =  4,105
D3 14:44  4,713 2,694 2,560 2,114 = 12,081
   14:45  2,183 3,602 4,144 3,733 = 13,662
   14:46     35 2,525 2,243 3,124 =  7,927
单桶峰值：D1 3.6/4.1/3.7/3.8 GB/s；D2 4.2/4.6/3.6/3.6 GB/s；D3 4.7/3.6/4.1/3.7 GB/s
```
可以看到，4 个桶的分钟写入是**此消彼长**的：某个 job 先做完（比如 D1/D3 的桶 0 在第 3 分钟就降到 ~0），其他桶就多分到一些，合计维持在 ~10～13.7 GB/s，这符合"4 个 job 共享同一份总额度"的形态。推测（未实测）：额度在源桶/账号/区域层面，不在目标桶层面。

### 3.5 校验
```
verify a1: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=2
verify b1: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0
verify c1: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0
verify d1: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0   (4 个桶合并)
verify b2: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0
verify c2: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0
verify d2: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0   (4 个桶合并)
verify a2: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=44
verify c3: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0
verify d3: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0   (4 个桶合并)
verify a3: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=62
verify b3: dst_g_objs=131072 missing=0 extra_g=0 non_g(reports etc)=0
```
（size,key）与源桶清单逐条 `comm` 比对。A 的 non_g 是 `reports/` 小文件。

## 4. 三个问题的回答

1. **B/C vs A 端到端是否下降？下降是否超过同配置波动？**
   B、C 平均比 A 快约 21 s（322 → 301 s，−6.5%），但同场景极差 34～62 s、标准差 18～31 s，t 值约 0.9～1.2（n=3），**没有超过波动**。而且 A 的均值被第 1 轮的时段效应拉高了（A1 338 s；第 1 轮均值 323 s，第 2、3 轮都是 302 s）。结论：**看不出可靠的加速**；如果真有加速，也是 ≤ 几十秒的级别，被时段噪声淹没了。
2. **数据面峰值是否随 job 数变化？** 不变。1 job / 2 job / 4 job / 4 job 4 桶的峰值区间完全重叠（~10～16.7 GB/s），历史最高的两次峰值反而是 1 job 的 A1（16.3）和单桶 4 job 的 C1（16.7）。
3. **D vs C：4 桶合计峰值是否突破 ~14 GB/s？** **没有**（D 最高 13.7 GB/s；单桶 C1 已经到 16.7 GB/s）。→ 瓶颈**不在单个目标桶/前缀的写入**。推测（未实测）：更像账号/区域级（或源桶级）的 Batch Replication / 复制服务端并发上限（~1,000 对象/s 量级，16 MiB 对象下 ~10～16 GB/s），也可能是源端读取或跨区链路等其他服务端限制。本轮数据区分不出"账号/区域级"和"源桶级"，需要多源桶并发测试。

## 5. 费用（不含存储）

单价（AWS Price List API，2026-10-22 拉取；对照 [S3 定价页](https://aws.amazon.com/s3/pricing/) Replication / Batch Operations 部分）：跨区 $0.02/GB（`USE2-USW2-AWS-Out-Bytes`）、复制 PUT $0.005/1,000（`USW2-Requests-Tier1`）、Batch $0.25/job（`USE2-BatchOperations-Jobs`）+ $1.00/百万对象（`USE2-BatchOperations-Objects`）+ manifest $0.015/百万源对象/job（`USE2-BatchOperations-Manifest`）。

### 5.1 复制本身（每次 2,048 GiB）
| 运行 | 传输 GiB | 传输 $ | 复制 PUT | PUT $ | job | job $ | Batch 对象 | 对象 $ | manifest $ | **小计 $** |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 / A2 / A3 | 2,048 | 40.96 | 131,072 / 131,135 / 131,162 | 0.656 | 1 | 0.25 | 同左 | 0.131 | 0.002 | **42.00** ×3 |
| B1 / B2 / B3 | 2,048 | 40.96 | 131,072 | 0.655 | 2 | 0.50 | 131,072 | 0.131 | 0.004 | **42.25** ×3 |
| C1 / C2 / C3 | 2,048 | 40.96 | 131,072 | 0.655 | 4 | 1.00 | 131,072 | 0.131 | 0.008 | **42.75** ×3 |
| D1 / D2 / D3 | 2,048 | 40.96 | 131,072 | 0.655 | 4 | 1.00 | 131,072 | 0.131 | 0.008 | **42.75** ×3 |
| **12 次合计** | 24,576 | 491.52 | ~1.573 M | 7.86 | 33 | 8.25 | ~1.573 M | 1.573 | 0.071 | **509.27** |

D 和 C 的复制费完全相同（PUT 按目标桶计，只是分到 4 个桶）。

### 5.2 测试附带成本
| 项 | 用量 | 单价 | 费用 $ |
|---|---|---|---|
| EC2 c7gn.16xlarge（生成数据） | 12:28:23 启动 → ~12:31 关机并 terminate，约 3 min | $3.9936/h | ~0.20 |
| 生成数据的 PUT（us-east-2） | 131,072 + 少量 | $0.005/1,000 | ~0.66 |
| LIST（校验 12 次 + 清理） | 约 3,000～4,000 次 | $0.005/1,000 | < 0.03 |
| DELETE（目标 20 桶 + 源桶全部版本，约 157 万个） | — | 免费 | 0 |
| 1 分钟 request metrics（20 个目标桶）+ Replication Metrics | 每个桶约 0.3～1.7 h | CloudWatch 自定义指标按小时折算 | 推测（未实测）：< $0.5 |
| 存储（源 2 TiB 约 3 h；每个目标桶 10～20 min） | — | 按要求不算 | — |

**本轮总费用估算 ≈ $510（复制 $509.27 + 生成 ~$0.9 + 其他 < $0.5），低于 $560 止损线。** 编排脚本按场景单价逐次累加估算，每次开跑前都检查过不超过 $560，最后累计 $511.25（含 $2 生成预留）。

## 6. 完整可复现命令

脚本在 `scripts/`，原始数据在 `raw/`：
- `gen_r2.sh`（数据生成 user-data）
- `run_r2.sh <a|b|c|d> <轮次>`（单次运行：建桶/开 metrics → 复制配置 → 300 s → N 个 job → 30 s 轮询 → 保存 describe-job）
- `precreate_dst.sh`（提前建目标桶并开 metrics）
- `verify_dst.sh <run>`（key+size 校验）
- `delete_dst.sh <桶列表文件>`（删全部版本 + metrics 配置 + 桶）
- `orchestrate.sh`（12 次轮转编排 + 预算止损 + 异常止损）
- `analyze_r2.py <run...>`（汇总 + CloudWatch 分析，输出 `raw/<run>/analysis.json`、`raw/analysis_all.txt`）
- 每次运行的 `raw/<run>/`：`replication.json`、`replication.applied.json`、`job<i>.manifest-generator.json`、`job<i>.report.json`、`jobs.txt`、`poll.log`、`describe-<JobId>.json`、`dst_buckets.txt`、`verify.txt`、`analysis.json`；`raw/runs_<run>.out` 是运行日志，`raw/orchestrate.log` 是编排日志。

### 6.1 桶 / IAM
```bash
E=$(date +%s); SRC=s3-crr-src-$E      # 本轮 E=1792758433
aws s3api create-bucket --bucket $SRC --region us-east-2 --create-bucket-configuration LocationConstraint=us-east-2
aws s3api put-bucket-versioning --bucket $SRC --versioning-configuration Status=Enabled --region us-east-2
aws iam create-role --role-name s3crr-repl-$E  --assume-role-policy-document file://trust-s3.json
aws iam put-role-policy --role-name s3crr-repl-$E --policy-name repl --policy-document file://repl-policy.json
aws iam create-role --role-name s3crr-batch-$E --assume-role-policy-document file://trust-batch.json
aws iam put-role-policy --role-name s3crr-batch-$E --policy-name batch --policy-document file://batch-policy.json
# 生成机实例角色
aws iam create-role --role-name s3crr-gen-ec2-$E --assume-role-policy-document file://trust-ec2.json
aws iam put-role-policy --role-name s3crr-gen-ec2-$E --policy-name s3 --policy-document file://ec2-s3.json
aws iam attach-role-policy --role-name s3crr-gen-ec2-$E --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name s3crr-gen-ec2-$E
aws iam add-role-to-instance-profile --instance-profile-name s3crr-gen-ec2-$E --role-name s3crr-gen-ec2-$E
aws ec2 create-security-group --region us-east-2 --group-name s3crr-gen-$E --description "s3crr gen r2" --vpc-id <DEFAULT_VPC>
```
`repl-policy.json`（目标用通配 `s3-crr-dst-*-<E>`，D 场景 4 个桶也覆盖）：
```json
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:GetReplicationConfiguration","s3:ListBucket"],"Resource":"arn:aws:s3:::<SRC>"},
{"Effect":"Allow","Action":["s3:GetObjectVersionForReplication","s3:GetObjectVersionAcl","s3:GetObjectVersionTagging"],"Resource":"arn:aws:s3:::<SRC>/*"},
{"Effect":"Allow","Action":["s3:ReplicateObject","s3:ReplicateDelete","s3:ReplicateTags"],"Resource":["arn:aws:s3:::s3-crr-dst-*-<E>/*"]}]}
```
`batch-policy.json`、`trust-*.json` 见 `scripts/`。

### 6.2 数据生成
```bash
aws ec2 run-instances --region us-east-2 --image-id <AL2023-arm64-AMI> --instance-type c7gn.16xlarge --key-name <KEY> \
  --iam-instance-profile Name=s3crr-gen-ec2-$E \
  --network-interfaces '[{"DeviceIndex":0,"SubnetId":"<SUBNET_2b_PUBLIC>","Groups":["<SG>"],"AssociatePublicIpAddress":true}]' \
  --instance-initiated-shutdown-behavior terminate --user-data file://gen_r2.sh
# gen_r2.sh 主体：
dd if=/dev/urandom of=/dev/shm/src.bin bs=1M count=16; sync          # 先完整生成源文件
python3 -c "...写 131072 行 cp /dev/shm/src.bin s3://<SRC>/g{p//2}/p{p}/{md5(f'{p}-{i}')[:2]}/obj_{i:05d}"
./s5cmd --numworkers 1024 --retry-count 10 run cmds.txt
./s5cmd du "s3://<SRC>/g*"; shutdown -h now
```

### 6.3 单次运行（以 D 为例；A 一条 `"Prefix":""` 指向 1 桶，B `g0/` `g1/` 指向 1 桶，C 4 前缀指向 1 桶）
```bash
# 目标桶 + 1 分钟 request metrics（至少提前 ~15 分钟开，否则开头几分钟没有数据）
for k in 0 1 2 3; do D=s3-crr-dst-d2-$k-$E
  aws s3api create-bucket --bucket $D --region us-west-2 --create-bucket-configuration LocationConstraint=us-west-2
  aws s3api put-bucket-versioning --bucket $D --versioning-configuration Status=Enabled --region us-west-2
  aws s3api put-bucket-metrics-configuration --bucket $D --region us-west-2 --id all --metrics-configuration Id=all
done
```
`replication.json`（D2 实际文件 `raw/d2/replication.json`）：
```json
{"Role":"arn:aws:iam::<ACCOUNT_ID>:role/s3crr-repl-<E>","Rules":[
 {"ID":"rule0","Priority":1,"Status":"Enabled","Filter":{"Prefix":"g0/p0/"},"DeleteMarkerReplication":{"Status":"Disabled"},
  "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-d2-0-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}},
 {"ID":"rule1","Priority":2,"Status":"Enabled","Filter":{"Prefix":"g0/p1/"},"DeleteMarkerReplication":{"Status":"Disabled"},
  "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-d2-1-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}},
 {"ID":"rule2","Priority":3,"Status":"Enabled","Filter":{"Prefix":"g1/p2/"},"DeleteMarkerReplication":{"Status":"Disabled"},
  "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-d2-2-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}},
 {"ID":"rule3","Priority":4,"Status":"Enabled","Filter":{"Prefix":"g1/p3/"},"DeleteMarkerReplication":{"Status":"Disabled"},
  "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-d2-3-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}}]}
```
```bash
aws s3api put-bucket-replication --bucket $SRC --region us-east-2 --replication-configuration file://replication.json
sleep 300
# 每条规则一个 job（i=0..3, P=g0/p0/ g0/p1/ g1/p2/ g1/p3/）
aws s3control create-job --region us-east-2 --account-id <ACCOUNT_ID> \
  --operation '{"S3ReplicateObject":{}}' \
  --report '{"Bucket":"arn:aws:s3:::<SRC>","Prefix":"reports/d2/job0","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}' \
  --manifest-generator '{"S3JobManifestGenerator":{"ExpectedBucketOwner":"<ACCOUNT_ID>","SourceBucket":"arn:aws:s3:::<SRC>","EnableManifestOutput":false,"Filter":{"EligibleForReplication":true,"KeyNameConstraint":{"MatchAnyPrefix":["g0/p0/"]}}}}' \
  --priority 10 --role-arn arn:aws:iam::<ACCOUNT_ID>:role/s3crr-batch-<E> --no-confirmation-required --description crr-r2-d2-job0
# A 场景的 manifest-generator Filter 只有 {"EligibleForReplication":true}
# 轮询
aws s3control describe-job --region us-east-2 --account-id <ACCOUNT_ID> --job-id <JOB_ID> \
  --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed,ProgressSummary.Timers.ElapsedTimeInActiveSeconds]'
# 目标桶 1 分钟写入（D 场景 4 个桶分别查，逐分钟相加）
aws cloudwatch get-metric-statistics --region us-west-2 --namespace AWS/S3 --metric-name BytesUploaded \
  --dimensions Name=BucketName,Value=<DST> Name=FilterId,Value=all --period 60 --statistics Sum --start-time ... --end-time ...
# 源桶复制失败
aws cloudwatch list-metrics --region us-east-2 --namespace AWS/S3 --metric-name OperationsFailedReplication --dimensions Name=SourceBucket,Value=<SRC>
```

### 6.4 校验 / 清理
```bash
AWS_REGION=us-east-2 s5cmd ls "s3://<SRC>/*" | awk '{print $3,$4}' | sort > src_keys.txt
for D in <本次所有目标桶>; do AWS_REGION=us-west-2 s5cmd ls "s3://$D/*" | awk '{print $3,$4}'; done | grep ' g[01]/' | sort > dst_keys.txt
comm -3 src_keys.txt dst_keys.txt | wc -l        # 0
AWS_REGION=us-west-2 s5cmd --numworkers 256 rm --all-versions "s3://<DST>/*"
aws s3api delete-bucket-metrics-configuration --bucket <DST> --id all --region us-west-2
aws s3api delete-bucket --bucket <DST> --region us-west-2
# 全部结束后
aws s3api delete-bucket-replication --bucket <SRC> --region us-east-2
AWS_REGION=us-east-2 s5cmd --numworkers 512 rm --all-versions "s3://<SRC>/*"
aws s3api delete-bucket --bucket <SRC> --region us-east-2
```

## 7. 清理确认（2026-10-23 ~15:35 UTC）
- EC2（c7gn.16xlarge）：生成完自己关机，已 terminated（运行约 3 分钟）。
- SG `s3crr-gen-1792758433`：已删除。
- IAM：`s3crr-gen-ec2-1792758433`（role + instance profile）、`s3crr-repl-1792758433`、`s3crr-batch-1792758433` 都已删除；`list-roles` / `list-instance-profiles` 里查不到本轮 epoch。
- S3：20 个目标桶都在各自运行校验完后删除（全部版本 + metrics 配置 + 桶）；源桶先删复制配置，再删全部版本（131,171 个，含 reports 文件），确认 `list-object-versions` 为空后删桶。`list-buckets` 里已经没有任何含 `1792758433` 的桶。
- `s3control list-jobs`（Active/Preparing/New/Suspended）：没有未完成的 job。
- 没碰：`s3lambdatest2`、新加坡测试的资源、其他已有资源。没有 push GitHub。
