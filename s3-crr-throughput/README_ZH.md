# S3 跨区域复制（CRR）+ Batch Replication 2 TiB 吞吐实测：Ohio → Oregon

> 实测日期：2026-10-22（UTC）。源 us-east-2，目标 us-west-2。
> 问题：复制规则/前缀从 1 条拆成 2 条、4 条，复制已有 2 TiB 数据会不会更快？
> 口径：MB = 10^6 字节，GB = 10^9 字节；费用按 GiB 计。

## 1. 结论速览

| 场景 | 规则数 / Batch 作业数 | 端到端耗时（首个作业创建 → 最后一个作业结束） | Batch Active 时间（作业中最大值） | MB/s（端到端） | MB/s（按 Active） | 对象/s（端到端） | 目标桶 CloudWatch 每分钟 PUT 峰值速率 | 失败数 |
|---|---|---|---|---|---|---|---|---|
| **A** 1 条规则（全桶） | 1 / 1 | **381 s**（6.4 min） | 326 s | 5,770 | 6,745 | 344 | （当时没开 request metrics） | 0 |
| A2 复测 | 1 / 1 | 582 s（9.7 min） | 526 s | 3,780 | 4,181 | 225 | **13,977 MB/s**（838.6 GB/min） | 0 |
| **B** 2 条规则（`g0/`、`g1/`） | 2 / 2 | **276 s**（4.6 min） | 221 s | 7,969 | 9,950 | 475 | （当时没开 request metrics） | 0 |
| B2 复测 | 2 / 2 | 556 s（9.3 min） | 509 s | 3,958 | 4,320 | 236 | **13,985 MB/s**（839.1 GB/min） | 0 |
| **C** 4 条规则（`g0/p0/`…`g1/p3/`） | 4 / 4 | **267 s**（4.5 min） | 219 s | 8,251 | 10,041 | 492 | **14,384 MB/s**（863.0 GB/min） | 0 |

数据量都一样：**131,072 个对象 × 16 MiB = 2,199,023,255,552 B（2 TiB）**。5 个目标桶我都把全部 key 和大小跟源桶逐条比过，差异为 0。

**核心结论（已实测）：**
1. **拆规则/前缀并不能让实际搬数据变快。** 从目标桶 CloudWatch 1 分钟粒度的 `PutRequests`/`BytesUploaded` 看，A2（1 条规则）、B2（2 条）、C（4 条）的写入都集中在 **4 个 1 分钟桶**里，峰值都在 **~14 GB/s（约 110 Gbps）、每分钟约 5 万个 PUT**。三者实际搬数据的窗口约 **2.6～4 分钟**，几乎一样。
2. **端到端耗时的差异主要来自 Batch 作业的"尾巴"，和规则数关系不大。** 配置完全相同的 A 和 A2 分别是 381 s 和 582 s，B 和 B2 是 276 s 和 556 s，同配置重复跑的波动（约 200～280 s）比 1→2→4 条规则之间的差异还大。A2/B2 里数据早在第 4 分钟就写完了（CloudWatch 之后每分钟只剩 0～2 个 PUT），但作业还挂在 Active 状态好几分钟才进入 Completing/Complete。
3. **Batch 作业的准备阶段很稳定**：S3 自动生成 manifest（131k 对象）每次都在 **31～36 s** 内完成，作业进入 Active（Preparing/New → Active），拆成 2 个或 4 个作业也一样（各作业是同时准备的）。
4. **Batch 进度计数是成批更新的**（比如 0 → 35,351 → 99,953 → 131,072），30 秒一次的轮询看不出真实写入曲线。要看真实速度，必须用目标桶的 request metrics（或复制指标）。
5. 推测（未实测）：第一轮（A/B/C，09:33～10:04）的端到端耗时整体比第二轮（A2/B2，10:13～10:40）短，原因可能是 S3 Batch 后台调度或账户级并发状态不同，跟规则数无关；只靠本次数据无法确认。
6. 推测（未实测）：本测试只测了"已有对象 → Batch Replication"这条路径。**线上实时复制（新写入的对象自动触发 CRR）** 的吞吐和延迟另有机制（可以开 RTC 拿 15 分钟 SLA），这次没测，不能套用上面的数字。

**一句话：** 2 TiB / 13 万个 16 MiB 对象从 Ohio 到 Oregon，Batch Replication 实际搬数据只要约 3～4 分钟（~14 GB/s），作业端到端 4.5～10 分钟。拆成 2 条或 4 条前缀规则，**不会**提高数据面吞吐。

## 2. 环境

| 项 | 值 |
|---|---|
| 源桶 | `s3-crr-src-<epoch>`，us-east-2，Versioning=Enabled，SSE-S3 默认加密 |
| 目标桶 | `s3-crr-dst-{a,b,c,a2,b2}-<epoch>`，us-west-2，Versioning=Enabled，**每个场景单独新建一个目标桶** |
| 数据 | 131,072 × 16 MiB（同一个 `/dev/urandom` 生成的源文件反复上传，ETag `ab5dbacc095c81ba0a47b07aa86f3af1`，单段上传） |
| Key 布局 | `g{0,1}/p{0..3}/<md5前2位>/obj_NNNNN`；p0、p1 在 g0 下，p2、p3 在 g1 下，每个 p 前缀 32,768 个对象（512 GiB） |
| 为什么这样分层 | 复制规则的 `Filter.Prefix` 只能写一个前缀，所以 B 场景用 `g0/`、`g1/` 两个前缀，各自刚好覆盖 2 个 p 前缀 |
| 数据生成 | c7gn.16xlarge（us-east-2b，AL2023 arm64），s5cmd v2.3.0，`--numworkers 1024`，**130 s 传完 2 TiB**（约 16.9 GB/s） |
| 复制配置 | N 条规则，Priority 1..N，DeleteMarkerReplication=Disabled，StorageClass=STANDARD，**开了 Replication Metrics，没开 RTC** |
| Batch 作业 | `S3ReplicateObject`，S3 自动生成 manifest（`S3JobManifestGenerator`），`EligibleForReplication=true` + `KeyNameConstraint.MatchAnyPrefix=[前缀]`，**不按 ObjectReplicationStatuses 过滤**，Priority=10，不需要确认，报告 FailedTasksOnly |
| 计时 | 每个作业 30 s 轮询一次 `describe-job`；端到端耗时取 `CreationTime` → `TerminationDate`（API 返回值）；A2/B2/C 的目标桶还开了 1 分钟 request metrics（`PutRequests`、`BytesUploaded`） |

### 为什么 B/C 不按复制状态过滤（查过官方文档）
- 官方文档（[Replicating existing objects with Batch Replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-batch-replication-batch.html)）说明，Batch Replication 可以复制 "Objects that have previously been replicated"；**不设 `ObjectReplicationStatuses` 过滤时，manifest 里所有符合规则的对象都会尝试复制，不管它们的复制状态是什么**。A 跑完后源对象状态是 COMPLETED，所以 B/C（以及 A2/B2）都不加这个过滤。如果要专门"给另一个目标补数据"，文档写的是用 `"COMPLETED"`。
- 实测：每次换成新目标桶和新规则后，所有对象都复制到了新目标桶（key 差异为 0），验证了这个做法可行。
- 文档还提到：修改复制配置后要等几分钟才生效，再用 S3 生成的 manifest 建作业。本测试每次 put-bucket-replication 后都等 **300 s**（这段时间不算进耗时）。

### 测试过程中的小插曲（已如实处理）
- 第一次生成数据用的是 `p0/..p3/` 一层前缀，传到 53,904 个对象时我发现 B 场景"一条规则管两个前缀"做不到（Filter.Prefix 只能写一个；用 And+Tag 会改变测试性质），于是停下、删光所有版本，改成 `g/p` 两层布局重新传。
- `Metrics.EventThreshold` 只能在开 RTC 时设置，不开 RTC 时会报 `InvalidArgument`，所以只保留 `Metrics.Status=Enabled`。
- A 场景规则是全桶（Prefix=""），所以 Batch 报告目录 `reports/` 下的小文件也会被复制：A 有 131,074 个任务，A2 有 131,093 个（多出来的都是前面几次运行的 manifest.json 小文件，字节数可以忽略）。B/C 用前缀规则，正好是 131,072 个。
- **A2、B2 是 HANDOFF 里没有的额外复测**，目的是：①给 A/B 补上 CloudWatch 1 分钟写入曲线（第一轮只有 C 开了 request metrics）；②看同配置的波动有多大。两次复测多花了约 $84（见费用表）。

## 3. 原始计时

### 3.1 状态时间点（相对第一个作业创建时间，30 s 轮询的粒度）
```
a  3b149263 Preparing@+0s Active@+31s Completing@+378s Complete@+409s
b  01af1b1f New@+0s       Active@+33s Completing@+263s Complete@+296s
b  97706a98 Preparing@+0s Active@+33s Completing@+230s Complete@+263s
c  04c87024 Preparing@+0s Active@+36s Completing@+180s Complete@+215s
c  48aec63e Preparing@+0s Active@+36s Completing@+215s Complete@+251s
c  90d98aa3 Preparing@+0s Active@+36s Completing@+215s Complete@+251s
c  c8785f0c Preparing@+0s Active@+36s Completing@+251s Complete@+287s
a2 44c0350b New@+0s       Active@+32s Completing@+567s Complete@+598s
b2 59a3dc1d Preparing@+0s Active@+33s Completing@+527s Complete@+560s
b2 d7fae78b Preparing@+0s Active@+33s Completing@+527s Complete@+560s
```

### 3.2 每个作业的 API 数值（describe-job）
| 场景 | 作业 | 前缀 | 任务数 | 成功 | 失败 | ElapsedTimeInActiveSeconds | CreationTime → TerminationDate | 作业耗时 |
|---|---|---|---|---|---|---|---|---|
| A | job0 | (全桶) | 131,074 | 131,074 | 0 | 326 | 09:33:08.2 → 09:39:29.3 | 381.1 s |
| B | job0 | g0/ | 65,536 | 65,536 | 0 | 221 | 09:48:04.5 → 09:52:40.4 | 275.9 s |
| B | job1 | g1/ | 65,536 | 65,536 | 0 | 209 | 09:48:06.0 → 09:52:28.7 | 262.7 s |
| C | job0 | g0/p0/ | 32,768 | 32,768 | 0 | 178 | 09:59:31.1 → 10:03:15.8 | 224.7 s |
| C | job1 | g0/p1/ | 32,768 | 32,768 | 0 | 161 | 09:59:32.6 → 10:02:58.1 | 205.5 s |
| C | job2 | g1/p2/ | 32,768 | 32,768 | 0 | 219 | 09:59:34.1 → 10:03:57.6 | 263.5 s |
| C | job3 | g1/p3/ | 32,768 | 32,768 | 0 | 200 | 09:59:35.6 → 10:03:40.2 | 244.7 s |
| A2 | job0 | (全桶) | 131,093 | 131,093 | 0 | 526 | 10:13:21.4 → 10:23:03.2 | 581.8 s |
| B2 | job0 | g0/ | 65,536 | 65,536 | 0 | 509 | 10:30:40.9 → 10:39:56.5 | 555.6 s |
| B2 | job1 | g1/ | 65,536 | 65,536 | 0 | 508 | 10:30:42.4 → 10:39:55.3 | 552.9 s |

N>1 时看各作业自己的速度：C 场景单个作业搬 512 GiB 用了 205～264 s（约 2.1～2.7 GB/s/作业），4 个作业合计 8.25 GB/s（端到端口径）。B 场景单个作业 1 TiB 用了 263～276 s（约 4.0～4.2 GB/s/作业），合计 7.97 GB/s。

### 3.3 目标桶 CloudWatch 1 分钟写入（这是真实的数据面速度）
```
C  (4 规则)  10:00  21,021 PUT  352.7 GB   5,878 MB/s
             10:01  51,443 PUT  863.0 GB  14,384 MB/s
             10:02  47,626 PUT  799.0 GB  13,317 MB/s
             10:03  10,988 PUT  184.3 GB   3,072 MB/s
A2 (1 规则)  10:14  20,391 PUT  342.1 GB   5,701 MB/s
             10:15  49,986 PUT  838.6 GB  13,977 MB/s
             10:16  48,150 PUT  807.5 GB  13,458 MB/s
             10:17  12,569 PUT  210.8 GB   3,513 MB/s
             10:21～10:24  每分钟 1～2 个 PUT（尾部零星任务；作业 10:23:03 才结束）
B2 (2 规则)  10:31  14,886 PUT  249.7 GB   4,162 MB/s
             10:32  49,329 PUT  827.6 GB  13,793 MB/s
             10:33  50,014 PUT  839.1 GB  13,985 MB/s
             10:34  16,846 PUT  282.6 GB   4,710 MB/s
```
- 三组的写入形态几乎一样：4 个 1 分钟桶，两头是半分钟左右的爬坡和收尾，中间 2 分钟稳定在 **13.3～14.4 GB/s、每分钟约 4.8～5.1 万个对象（约 800～860 对象/s）**。
- 数据面实际搬运时长：下限 = 2,199 GB ÷ 峰值 14.4 GB/s ≈ 153 s，上限 = 4 个分钟桶 = 240 s。所以真实数据窗口约 **2.6～4 分钟，等效 9.2～14.4 GB/s**，跟规则数无关。
- 推测（未实测）：~14 GB/s / ~850 对象/s 可能是这个账户在 us-east-2 上 Batch Replication 的服务端并发上限（每个账户/区域），而不是网络或桶前缀的限制。在 13 万个对象、2 TiB 的规模下，拆规则/作业只是把同一份并发额度分给多个作业。如果把对象数或单对象大小换成别的组合（比如大量 KB 级小对象），瓶颈可能变成每秒请求数，结论要重新测。

### 3.4 数据生成
```
upload_start 2026-10-22T09:22:54Z
upload_end   2026-10-22T09:25:04Z   (130 s, 131072 成功, 0 错误)
s5cmd du: 2199023255552 bytes in 131072 objects
```

### 3.5 校验
- 每个目标桶都把 `aws s3 ls --recursive` 的 (size, key) 和源桶排序后 `comm` 比较：a/b/c/a2/b2 **缺失 0、多余 0**（a/a2 另外多出前面说的 reports/ 小文件）。
- 抽样 `head-object`：目标对象 ContentLength=16777216，ETag 跟源一致，ReplicationStatus=REPLICA。
- 所有作业 `NumberOfTasksFailed=0`，失败报告为空（只有 manifest.json）。
- 源桶 `OperationsFailedReplication`（复制指标）全是 0。

## 4. 费用估算（不含存储费）

单价都来自 **AWS Price List API（us-east-2 / us-west-2 offer 文件，2026-10-22 拉取）**，并对照了 [S3 定价页](https://aws.amazon.com/s3/pricing/) 的 Replication 和 Batch Operations 部分：

| 项 | 单价 | 来源（usagetype） |
|---|---|---|
| 跨区传输 us-east-2 → us-west-2 | **$0.02/GB** | AWSDataTransfer `USE2-USW2-AWS-Out-Bytes` |
| 复制 PUT（按目标区域、目标存储类计费） | **$0.005/1,000** | AmazonS3 `USW2-Requests-Tier1`（定价页："PUT request pricing for the replicated copy is based on the selected destination AWS Regions"） |
| Batch Operations 作业费 | **$0.25/作业** | `USE2-BatchOperations-Jobs` |
| Batch Operations 对象费 | **$1.00/百万对象** | `USE2-BatchOperations-Objects` |
| Batch 生成 manifest | **$0.015/百万个源桶对象**（每个作业按源桶对象数计） | `USE2-BatchOperations-Manifest` |
| RTC（本测试**没开**） | $0.015/GB | `USE2-USW2-S3RTC-Out-Bytes` |

### 4.1 复制本身的费用（每个场景 2,048 GiB、约 131k 对象）
| 场景 | 传输 GiB | 传输费 $ | 复制 PUT 数 | PUT 费 $ | 作业数 | 作业费 $ | Batch 对象数 | 对象费 $ | Manifest 费 $ | **小计 $** |
|---|---|---|---|---|---|---|---|---|---|---|
| A（1 规则） | 2,048 | 40.96 | 131,074 | 0.655 | 1 | 0.25 | 131,074 | 0.131 | 0.002 | **42.00** |
| B（2 规则） | 2,048 | 40.96 | 131,072 | 0.655 | 2 | 0.50 | 131,072 | 0.131 | 0.004 | **42.25** |
| C（4 规则） | 2,048 | 40.96 | 131,072 | 0.655 | 4 | 1.00 | 131,072 | 0.131 | 0.008 | **42.75** |
| A2（复测） | 2,048 | 40.96 | 131,093 | 0.655 | 1 | 0.25 | 131,093 | 0.131 | 0.002 | 42.00 |
| B2（复测） | 2,048 | 40.96 | 131,072 | 0.655 | 2 | 0.50 | 131,072 | 0.131 | 0.004 | 42.25 |
| **A+B+C 合计** | 6,144 | 122.88 | | 1.966 | 7 | 1.75 | | 0.393 | 0.014 | **127.00** |
| **5 次实际合计** | 10,240 | 204.80 | | 3.277 | 11 | 2.75 | | 0.655 | 0.020 | **211.50** |

要点：**98% 的费用是跨区传输费（$0.02/GB）**。多拆 1 条规则或 1 个作业只多 $0.25 的作业费，拆规则在成本上几乎没影响，但也换不来速度。

- 推测（未实测）：定价页 Replication 部分列的收费项只有目标存储、复制 PUT、跨区传输（RTC 另算），**没有列源端读（GET）费用**。我推测源端不收 GET 费，需要第二天去 Cost Explorer 按 usage type 核对。
- 推测（未实测）：Replication Metrics（没开 RTC）按 CloudWatch 自定义指标计费（定价页把它跟 RTC 放在一起说明）。本测试 7 条规则的指标只存在了约 1 小时，按比例折算后 < $0.05，所以没放进表里。目标桶 1 分钟 request metrics 同理，开了约 1 小时，可以忽略。

### 4.2 测试附带成本（不属于复制本身，单列）
| 项 | 用量 | 单价 | 费用 $ |
|---|---|---|---|
| EC2 c7gn.16xlarge（生成数据） | 约 8 min（09:19:55 启动 → 约 09:27 终止） | $3.9936/h（Price List API） | ~0.53 |
| 生成数据的 PUT（含第一次放弃的 53,904 个） | 184,976 | $0.005/1,000（USE2-Requests-Tier1） | ~0.92 |
| 删除版本（DELETE 请求） | ~89 万 | 免费 | 0 |
| LIST（校验和清理） | 约几千次 | $0.005/1,000 | < 0.05 |
| 存储（源桶约 1.5 h，目标桶约 0.5～1.5 h） | — | 按要求不算 | — |

**本次测试总花费约 $213**（低于 $300 的上限）。

## 5. 完整可复现命令

所有脚本都在 `s3-crr-bench/` 目录：`gen_data.sh`（user-data 第一版）、`gen2.sh`（实际使用的 g/p 布局生成脚本，通过 SSM 执行）、`run_scenario.sh`（单个场景：复制配置 + N 个作业 + 轮询）、`analyze.py`（汇总 + CloudWatch），以及 `runs/<场景>/` 下所有的 replication.json、manifest-generator.json、report.json、poll.log、describe-*.json。

### 5.1 桶 / IAM
```bash
E=$(date +%s); SRC=s3-crr-src-$E
aws s3api create-bucket --bucket $SRC --region us-east-2 --create-bucket-configuration LocationConstraint=us-east-2
aws s3api put-bucket-versioning --bucket $SRC --versioning-configuration Status=Enabled --region us-east-2
for s in a b c a2 b2; do
  aws s3api create-bucket --bucket s3-crr-dst-$s-$E --region us-west-2 --create-bucket-configuration LocationConstraint=us-west-2
  aws s3api put-bucket-versioning --bucket s3-crr-dst-$s-$E --versioning-configuration Status=Enabled --region us-west-2
  aws s3api put-bucket-metrics-configuration --bucket s3-crr-dst-$s-$E --region us-west-2 --id all --metrics-configuration Id=all  # 1 分钟 request metrics（可选）
done
# 复制角色（trust: s3.amazonaws.com）
aws iam create-role --role-name s3crr-repl-$E --assume-role-policy-document file://trust-s3.json
aws iam put-role-policy --role-name s3crr-repl-$E --policy-name repl --policy-document file://repl-policy.json
# Batch 角色（trust: batchoperations.s3.amazonaws.com，策略按官方 "S3 generated manifest" 模板）
aws iam create-role --role-name s3crr-batch-$E --assume-role-policy-document file://trust-batch.json
aws iam put-role-policy --role-name s3crr-batch-$E --policy-name batch --policy-document file://batch-policy.json
```
`repl-policy.json`：
```json
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:GetReplicationConfiguration","s3:ListBucket"],"Resource":"arn:aws:s3:::<SRC>"},
{"Effect":"Allow","Action":["s3:GetObjectVersionForReplication","s3:GetObjectVersionAcl","s3:GetObjectVersionTagging"],"Resource":"arn:aws:s3:::<SRC>/*"},
{"Effect":"Allow","Action":["s3:ReplicateObject","s3:ReplicateDelete","s3:ReplicateTags"],"Resource":["arn:aws:s3:::<DST_a>/*","arn:aws:s3:::<DST_b>/*","..."]}]}
```
`batch-policy.json`（manifest 和报告都放在源桶）：
```json
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:InitiateReplication"],"Resource":"arn:aws:s3:::<SRC>/*"},
{"Effect":"Allow","Action":["s3:GetReplicationConfiguration","s3:PutInventoryConfiguration"],"Resource":"arn:aws:s3:::<SRC>"},
{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":"arn:aws:s3:::<SRC>/*"},
{"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::<SRC>/*"}]}
```

### 5.2 数据生成（c7gn.16xlarge，us-east-2，通过 SSM 执行 gen2.sh）
```bash
curl -sL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-arm64.tar.gz | tar xz
dd if=/dev/urandom of=/dev/shm/src.bin bs=1M count=16      # 先完整生成源文件，再上传
python3 -c "
import hashlib
with open('/root/cmds.txt','w') as f:
  for p in range(4):
    g=p//2
    for i in range(32768):
      h=hashlib.md5(f'{p}-{i}'.encode()).hexdigest()[:2]
      f.write(f'cp /dev/shm/src.bin s3://<SRC>/g{g}/p{p}/{h}/obj_{i:05d}\n')
"
./s5cmd --numworkers 1024 --retry-count 10 run cmds.txt > upload.out 2> upload.err
./s5cmd du "s3://<SRC>/*"
```
EC2 启动命令（default VPC 的子网需要显式分配公网 IP）：
```bash
aws ec2 run-instances --region us-east-2 --image-id <AL2023-arm64-AMI> --instance-type c7gn.16xlarge --key-name <KEY> \
  --iam-instance-profile Name=<PROFILE> \
  --network-interfaces '[{"DeviceIndex":0,"SubnetId":"<SUBNET_2b>","Groups":["<SG>"],"AssociatePublicIpAddress":true}]' \
  --instance-initiated-shutdown-behavior terminate --user-data file://gen_data.sh
```

### 5.3 场景执行（`./run_scenario.sh a|b|c|a2|b2`）
复制配置（以 C 为例，A 是一条 `"Prefix":""`，B 是 `g0/`、`g1/` 两条）：
```json
{"Role":"arn:aws:iam::<ACCOUNT_ID>:role/s3crr-repl-<E>","Rules":[
 {"ID":"rule0","Priority":1,"Status":"Enabled","Filter":{"Prefix":"g0/p0/"},
  "DeleteMarkerReplication":{"Status":"Disabled"},
  "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-c-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}},
 {"ID":"rule1","Priority":2, ... "Filter":{"Prefix":"g0/p1/"} ...},
 {"ID":"rule2","Priority":3, ... "Filter":{"Prefix":"g1/p2/"} ...},
 {"ID":"rule3","Priority":4, ... "Filter":{"Prefix":"g1/p3/"} ...}]}
```
```bash
aws s3api put-bucket-replication --bucket $SRC --region us-east-2 --replication-configuration file://replication.json
sleep 300   # 官方文档：配置变更要几分钟才能生效
# 每个前缀建一个作业（A 场景不写 KeyNameConstraint）
aws s3control create-job --region us-east-2 --account-id <ACCOUNT_ID> \
  --operation '{"S3ReplicateObject":{}}' \
  --report '{"Bucket":"arn:aws:s3:::<SRC>","Prefix":"reports/c/job0","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}' \
  --manifest-generator '{"S3JobManifestGenerator":{"ExpectedBucketOwner":"<ACCOUNT_ID>","SourceBucket":"arn:aws:s3:::<SRC>","EnableManifestOutput":false,"Filter":{"EligibleForReplication":true,"KeyNameConstraint":{"MatchAnyPrefix":["g0/p0/"]}}}}' \
  --priority 10 --role-arn arn:aws:iam::<ACCOUNT_ID>:role/s3crr-batch-<E> --no-confirmation-required
# 轮询（每 30 s）
aws s3control describe-job --region us-east-2 --account-id <ACCOUNT_ID> --job-id <JOB_ID> \
  --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed,ProgressSummary.Timers.ElapsedTimeInActiveSeconds]'
# 目标桶 1 分钟写入
aws cloudwatch get-metric-statistics --region us-west-2 --namespace AWS/S3 --metric-name BytesUploaded \
  --dimensions Name=BucketName,Value=<DST> Name=FilterId,Value=all --period 60 --statistics Sum --start-time ... --end-time ...
```

### 5.4 校验 / 清理
```bash
aws s3 ls s3://<SRC>/g --recursive | awk '{print $3,$4}' | sort > src_keys.txt
aws s3 ls s3://<DST>/ --recursive | awk '$4 ~ /^g[01]\//{print $3,$4}' | sort > dst_keys.txt
comm -3 src_keys.txt dst_keys.txt | wc -l     # 期望 0
aws s3api delete-bucket-replication --bucket <SRC> --region us-east-2
AWS_REGION=us-west-2 s5cmd --numworkers 512 rm --all-versions "s3://<DST>/*"   # 注意：s5cmd 必须设对区域，否则会 403
AWS_REGION=us-east-2 s5cmd --numworkers 512 rm --all-versions "s3://<SRC>/*"
aws s3api delete-bucket --bucket <BUCKET> --region <REGION>
```

## 6. 清理确认（2026-10-22 ~10:50 UTC）
- EC2 `c7gn.16xlarge` 已终止（生成完数据立刻终止，运行约 8 分钟）。
- SG `s3crr-gen-<E>` 已删除。
- IAM：`s3crr-gen-ec2-<E>`（role + instance profile）、`s3crr-repl-<E>`、`s3crr-batch-<E>` 都已删除。账户里其他 `s3crr_role_for_*` 角色是以前就有的，没动。
- S3：源桶 + 5 个目标桶的全部版本都删光（删前确认 Versions/DeleteMarkers 都是 0），6 个桶都已删除；`list-buckets` 里已经没有 `s3-crr-*` 开头的桶。删之前先删了源桶的复制配置和目标桶的 metrics 配置。
- 没碰 s3lambdatest2 和其他已有资源。
