# S3 CRR + Batch Replication 小文件测试：Ohio → Oregon（500 GiB / 512 KiB × 1,024,000）

> 实测日期：2026-10-23（UTC 15:54～18:18）。源 us-east-2，目标 us-west-2。AWS CLI + s5cmd v2.3.0。
> 口径：MB = 10^6 字节，GB = 10^9 字节；费用按 GiB 计。16 MiB 主测试见 [`../README_ZH.md`](../README_ZH.md)。
> 脚本在 [`scripts/`](scripts/)，原始数据在 [`raw/`](raw/)。**只用 1 条规则（全桶）+ 1 个 Batch job，跑 2 次（S1、S2）。**

## 1. 结论速览

### 1.1 两次运行

| 运行 | 任务数 / 失败 | 端到端 s（CreationTime→TerminationDate） | Batch Active s | 准备阶段 s（Preparing→Active） | MB/s 端到端 | MB/s Active | 对象/s 端到端 | 对象/s Active | 数据窗口（PUT>1000/min） | 窗口内均值 | 1 分钟峰值 | 尾巴 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **S1** | 1,039,478 / 0 | **1,992**（33.2 min） | 1,865 | ~64～95（轮询粒度 30 s；Active 计时 1,865 ≈ 端到端 − 127） | **274** | 292 | **522** | 557 | 16:20–16:45（25 min） | 363 MB/s，692 对象/s | **573 MB/s，65,597 PUT/min = 1,093 对象/s** | 323 |
| **S2** | 1,039,481 / 0 | **1,769**（29.5 min） | 1,642 | ~64～95（同上；端到端 − Active = 127） | **308** | 332 | **588** | 633 | 17:21–17:41（20 min） | 454 MB/s，866 对象/s | **752 MB/s，86,118 PUT/min = 1,435 对象/s** | 398 |
| **均值** | — | **1,880**（31.3 min） | 1,754 | — | **291** | 312 | **555** | 595 | 22.5 min | 409 MB/s，779 对象/s | 663 MB/s，1,264 对象/s | 360 |

- MB/s 按**实际复制字节**算（任务数 × 524,288 B ≈ 545.0 GB，比 500 GiB 多约 1.5%，原因见 2.3）；按名义 500 GiB（536.87 GB）算是 S1 269 / S2 304 MB/s。
- 端到端 − Active = 127 s，两次完全相同 = Preparing（manifest 生成）+ Completing。poll.log 里 Preparing→Active 出现在 +63～+95 s 之间；`Completing` 状态持续 ≤ 31 s。所以 **manifest 生成/准备约 65～95 s**，16 MiB × 131k 时是 31～36 s——对象数 ×7.8，准备时间只多约 1 分钟。
- 两次的 CloudWatch 覆盖率（目标桶 BytesUploaded 合计 / 实际复制字节）都是 **100.0%**（目标桶提前 ~20 min / ~80 min 开 metrics）。
- 校验：两次目标桶 obj_ 对象 key+size 与源逐条 `comm`：**1,024,000 个，缺失 0、多余 0**；抽样 5 个 head-object：大小 524,288、ETag 一致、目标 `REPLICA`/源 `COMPLETED`、SSE AES256。源桶 OperationsFailedReplication = 0。

### 1.2 与 16 MiB 主测试（A 场景 1 规则 1 job）对比

| 指标 | 16 MiB × 131,072（2 TiB），A1/A2/A3 | 512 KiB × 1,024,000（500 GiB），S1/S2 | 比值（小/大） |
|---|---|---|---|
| 端到端 | 322 s（294–338） | **1,880 s**（1,769–1,992） | ×5.8（数据量只有 1/4） |
| MB/s（端到端） | 6,856 | **291** | **1/24** |
| 1 分钟峰值 MB/s | 10,084–16,257 | **573–752** | ~1/18 |
| 对象/s（端到端） | ~407（131k / 322 s） | **555** | ×1.4 |
| 对象/s（数据窗口内均值） | ~600–750（例：A2 131k / 5 min 窗口 ≈ 730/s） | **692–866** | ≈ 持平 |
| 1 分钟峰值对象/s（PUT/min ÷ 60） | 601–969（36,066–58,144 PUT/min） | **1,093–1,435**（65,597–86,118） | ×1.5 |
| 稳定段 PUT/min | 3.6～6 万 | S1 ~3.6 万（16:26–16:37）/ S2 ~5.2 万（17:27–17:39） | 同一量级 |
| 准备阶段（Preparing→Active） | 31–32 s | ~65–95 s | +~1 min |
| 尾巴（数据写完→job 终止） | 0–14 s | **323–398 s** | 小文件长尾明显 |

**一句话：对象从 16 MiB 降到 512 KiB（1/32），每秒对象数基本没变（稳定段 ~600～900 对象/s，峰值 ~1,100～1,400 对象/s），所以 MB/s 几乎按对象大小线性下降，从 ~7～16 GB/s 降到 ~0.3～0.75 GB/s。**

### 1.3 核心结论

1. **已实测：瓶颈是每秒对象数，不是带宽。** 512 KiB 时数据窗口内平均 692 / 866 对象/s，1 分钟峰值 1,093 / 1,435 对象/s；16 MiB 时窗口内约 600～750 对象/s、峰值 600～970 对象/s。对象小了 32 倍，对象/s 只高了 ~1.2～1.5 倍，MB/s 因此掉到 1/24（端到端口径 6,856 → 291 MB/s）。这印证了主测试的推测：单 job / 单源桶的 Batch Replication 吞吐上限是**按对象数**的，量级 ~1,000 对象/s。
   - 推测（未实测）：该上限是 Batch Operations 每作业/每账号的任务派发并发，或复制服务端的每源桶并发；本测试只有 1 个源桶 1 个 job，区分不了是哪一层。主测试已实测拆 1/2/4 个 job 对 16 MiB 没有加速，所以对小文件拆 job 大概率也无效，但 512 KiB 下未实测。
2. **已实测：写入曲线是"开头冲高 → 长时间平台 → (S1)再冲高 → 长尾"。** S1：16:22–16:25 爬升到 557 MB/s，16:26–16:37 平台 ~310～330 MB/s（~3.6 万 PUT/min ≈ 600 对象/s），16:38–16:43 又回到 ~500～570 MB/s；S2：17:23–17:26 冲到 752 MB/s，17:27–17:39 平台 ~450 MB/s（~5.2 万 PUT/min ≈ 870 对象/s）。平台非常平（S2 13 分钟内 446～460 MB/s，波动 < 3%），像是一个硬性的派发速率上限，而不是网络抖动。两次平台高度差 ~40%（600 vs 870 对象/s），和 16 MiB 时"~10 GB/s 档 vs ~13～16 GB/s 档"现象一致，推测（未实测）为服务端时段/分配差异。
3. **已实测：小文件的长尾很长，占端到端 ~17～22%。** 数据窗口结束（S1 16:45、S2 17:41）后 job 又在 Active 里挂了 5～6.6 分钟才终止：S1 最后 ~340 个任务用了 ~5 分钟（poll.log 1,039,137 → 1,039,478）；S2 只差最后 **1 个**任务就卡了 ~4 分钟（17:41:15 起 1,039,480，17:45:27 才到 1,039,481）。16 MiB 时尾巴只有 0～14 s（12 次中仅 D3 有 72 s）。推测（未实测）：Batch Operations 对个别任务有内部重试/超时等待，对象数越多，命中"慢任务"的概率越大。
4. **已实测：manifest 生成随对象数变慢但不多。** 1.04M 对象 Preparing ~65～95 s，13 万对象 31～36 s；端到端 − Active 两次都是 127 s。对 1M 级别对象来说，manifest 不是主要耗时，数据面（~25 min）才是。
5. **费用结构变了：小文件下"按对象计"的费用占比从 ~2% 升到 ~38%。** 每次 $16.9，其中跨区传输 $10.24（61%）、复制 PUT $5.20（31%）、Batch 对象费 $1.04（6%）。同样 500 GiB 如果是 16 MiB 对象，只要 ~$10.6。

## 2. 环境

| 项 | 值 |
|---|---|
| 源桶 | `s3-crr-src-small-1792770913`，us-east-2，Versioning=Enabled，SSE-S3 默认（AES256） |
| 目标桶 | `s3-crr-dst-s1-1792770913`、`s3-crr-dst-s2-1792770913`，us-west-2，Versioning=Enabled，开 1 分钟 request metrics（`Id=all`）；**15:55:45 / 15:55:50 在数据生成前建好**（距 S1 job 21 min、距 S2 job 82 min） |
| 数据 | 1,024,000 × 512 KiB（524,288 B）= 536,870,912,000 B = 500 GiB。同一个 `/dev/urandom` 源文件（md5 `13f3cafec38ac2cff05e54cfce651303`）反复上传，单段上传 |
| Key 布局 | `<md5(str(i))前3位hex>/obj_NNNNNNN`，4,096 个前缀，每个约 250 个对象 |
| 数据生成 | c7gn.16xlarge（us-east-2b，AL2023 arm64，默认 VPC 公有子网，显式 `AssociatePublicIpAddress`，实例角色），user-data 跑 `scripts/gen_small.sh`；s5cmd `--numworkers 2048 --retry-count 10`：**15:56:50 → 16:02:03，用时 313 s（约 3,272 对象/s，1.72 GB/s）**；s5cmd 输出 1,024,000 条成功、stderr 0 行，但 list 发现 5 个缺失 → 补传 16:02:03 → 16:03:19 → 最终 1,024,000 个；`InstanceInitiatedShutdownBehavior=terminate`，16:04 后自行终止 |
| 复制配置 | 1 条规则 `Prefix=""`，Priority 1，`DeleteMarkerReplication=Disabled`，`StorageClass=STANDARD`，开 Replication Metrics，**不开 RTC** |
| Batch 作业 | `S3ReplicateObject`，`S3JobManifestGenerator` Filter=`{"EligibleForReplication":true}`（**不按 ObjectReplicationStatuses 过滤**，S2 才能把已 COMPLETED 的对象复制到新目标桶），Priority=10，`--no-confirmation-required`，报告 FailedTasksOnly 到源桶 `reports/` |
| 计时 | put-bucket-replication 后等 300 s 再建 job；describe-job 30 s 轮询；端到端 = API 的 `CreationTime` → `TerminationDate` |
| 顺序 | S1（job 16:17:10）→ 校验 → 删 S1 目标桶（16:5x–17:12）→ S2（复制配置 17:13，job 17:18:09）→ 校验 → 清理 |

### 2.1 生成时 s5cmd 的"隐性失败"和多余版本（如实记录）
- s5cmd 报告 1,024,000 条 `cp` 成功、错误 0，但事后 `s5cmd du` 只有 1,023,995 个对象，**5 个对象实际不存在**（`489/obj_1008488`、`7d5/obj_1023553`、`afc/obj_1022596`、`c3f/obj_1022512`、`fce/obj_1023024`）。补传后齐全。
- 源桶 `list-object-versions` 共 **1,039,476 个对象版本**（不含 `_gen/` 2 个和 reports），即 1,008,795 个 key 只有 1 个版本、14,940 个 key 有 2 个版本、268 个 key 有 3 个版本。推测（未实测）：2,048 并发下部分 PUT 客户端超时/5xx 后由 s5cmd 重试，但服务端第一次其实已经写入，于是产生了重复版本（versioning 开着）。那 5 个"缺失"的对象 list 时都已有版本，推测是 list 与写入的可见性时序问题。
- **影响**：manifest 生成器（`EligibleForReplication=true`）会把**非当前版本也列进来**，所以 job 任务数是 1,039,478（S1）/ 1,039,481（S2）= 1,039,476 个数据版本 + `_gen/` 2 个 + 之前的 reports 文件；比 1,024,000 多 1.5%。目标桶 `list-object-versions` S1 共 1,039,481 个版本，与此吻合。所以实际复制字节 ≈ 545.0 GB，CloudWatch 合计 545.0 GB 与之吻合（覆盖率 100.0%）。本报告 MB/s、对象/s 均按实际任务数/字节计算。

## 3. 原始数据

### 3.1 describe-job
```
S1 9694d46b-b3a5-485f-9680-7fbcdd45da03 Complete  Created 16:17:10.319  Terminated 16:50:22.523  wall 1,992.2 s  Active 1,865 s  tasks 1,039,478 ok 1,039,478 failed 0
S2 884c21ff-9afe-4385-ac14-439befc26dec Complete  Created 17:18:09.274  Terminated 17:47:37.834  wall 1,768.6 s  Active 1,642 s  tasks 1,039,481 ok 1,039,481 failed 0
```
完整 JSON：`raw/<s1|s2>/describe-<JobId>.json`；30 s 轮询：`raw/<run>/poll.log`。

poll.log 摘录（每 ~2 min 一行；列：时间、相对 job 创建秒数、状态、已成功、Active 计时）：
```
S1  16:17:12 +0     Preparing 0          0     | S2  17:18:11 +0     Preparing 0          0
    16:18:15 +63    Preparing 0          0     |     17:19:14 +63    Preparing 0          0
    16:18:46 +95    Active    0          3     |     17:19:45 +95    Active    0          5
    16:21:23 +252   Active    1,048      161   |     17:22:22 +252   Active    1,107      162
    16:23:29 +378   Active    32,555     286   |     17:24:28 +378   Active    84,871     288
    16:25:35 +504   Active    142,208    412   |     17:26:34 +504   Active    229,399    414
    16:29:47 +755   Active    331,849    664   |     17:30:46 +756   Active    484,507    666
    16:33:58 +1007  Active    508,940    916   |     17:34:58 +1007  Active    697,130    917
    16:38:10 +1259  Active    647,912    1167  |     17:39:10 +1259  Active    953,567    1169
    16:42:22 +1510  Active    880,295    1419  |     17:41:15 +1385  Active    1,039,480  1295
    16:44:28 +1636  Active    991,480    1545  |     17:45:27 +1637  Active    1,039,481  1547
    16:46:34 +1762  Active    1,039,137  1671  |     17:47:33 +1763  Completing 1,039,481 1642
    16:48:40 +1888  Active    1,039,405  1797  |     17:48:05 +1794  Complete  1,039,481  1642
    16:50:14 +1983  Completing 1,039,478 1865  |
    16:50:45 +2014  Complete  1,039,478  1865  |
```
注：NumberOfTasksSucceeded 是批量更新的（常连续两次轮询不变），只做趋势参考；吞吐以 CloudWatch 为准。Active 计时开始后约 2 分钟（+95 → +220 s）目标桶才有明显写入，这段也算在 Active 里。

### 3.2 目标桶 CloudWatch 1 分钟写入（PutRequests / BytesUploaded，FilterId=all）

| S1 分钟 | PUT | 对象/s | GB | MB/s | | S2 分钟 | PUT | 对象/s | GB | MB/s |
|---|---|---|---|---|---|---|---|---|---|---|
| 16:19 | 565 | 9 | 0.3 | 5 | | 17:20 | 638 | 11 | 0.3 | 6 |
| 16:20 | 1,941 | 32 | 1.0 | 17 | | 17:21 | 2,108 | 35 | 1.1 | 18 |
| 16:21 | 20,521 | 342 | 10.8 | 179 | | 17:22 | 27,330 | 456 | 14.3 | 239 |
| 16:22 | 47,070 | 784 | 24.7 | 411 | | 17:23 | 63,486 | 1,058 | 33.3 | 555 |
| 16:23 | 55,773 | 930 | 29.2 | 487 | | 17:24 | 75,631 | 1,261 | 39.7 | 661 |
| 16:24 | 63,697 | 1,062 | 33.4 | 557 | | 17:25 | 84,103 | 1,402 | 44.1 | 735 |
| 16:25 | 51,533 | 859 | 27.0 | 450 | | **17:26** | **86,118** | **1,435** | 45.1 | **752** |
| 16:26 | 37,562 | 626 | 19.7 | 328 | | 17:27 | 52,947 | 882 | 27.8 | 463 |
| 16:27 | 40,035 | 667 | 21.0 | 350 | | 17:28 | 52,609 | 877 | 27.6 | 460 |
| 16:28 | 37,269 | 621 | 19.5 | 326 | | 17:29 | 51,049 | 851 | 26.8 | 446 |
| 16:29 | 36,202 | 603 | 19.0 | 316 | | 17:30 | 52,247 | 871 | 27.4 | 457 |
| 16:30 | 36,721 | 612 | 19.3 | 321 | | 17:31 | 51,377 | 856 | 26.9 | 449 |
| 16:31 | 36,050 | 601 | 18.9 | 315 | | 17:32 | 52,217 | 870 | 27.4 | 456 |
| 16:32 | 35,495 | 592 | 18.6 | 310 | | 17:33 | 52,491 | 875 | 27.5 | 459 |
| 16:33 | 35,680 | 595 | 18.7 | 312 | | 17:34 | 51,386 | 856 | 26.9 | 449 |
| 16:34 | 36,879 | 615 | 19.3 | 322 | | 17:35 | 52,127 | 869 | 27.3 | 455 |
| 16:35 | 36,675 | 611 | 19.2 | 320 | | 17:36 | 52,263 | 871 | 27.4 | 457 |
| 16:36 | 36,530 | 609 | 19.2 | 319 | | 17:37 | 52,305 | 872 | 27.4 | 457 |
| 16:37 | 35,803 | 597 | 18.8 | 313 | | 17:38 | 51,802 | 863 | 27.2 | 453 |
| 16:38 | 41,237 | 687 | 21.6 | 360 | | 17:39 | 51,861 | 864 | 27.2 | 453 |
| 16:39 | 62,318 | 1,039 | 32.7 | 545 | | 17:40 | 23,407 | 390 | 12.3 | 205 |
| 16:40 | 64,747 | 1,079 | 33.9 | 566 | | 17:41 | 18 | 0 | 0.0 | 0 |
| 16:41 | 59,061 | 984 | 31.0 | 516 | | 17:44 | 1 | 0 | 0.0 | 0 |
| **16:42** | **65,597** | **1,093** | 34.4 | **573** | | | | | | |
| 16:43 | 57,667 | 961 | 30.2 | 504 | | | | | | |
| 16:44 | 6,430 | 107 | 3.4 | 56 | | | | | | |
| 16:45 | 182 | 3 | 0.1 | 2 | | | | | | |
| 16:46 | 151 | 3 | 0.1 | 1 | | | | | | |
| 16:47 | 47 | 1 | 0.0 | 0 | | | | | | |
| 16:48 | 50 | 1 | 0.0 | 0 | | | | | | |
| 16:49 | 7 | 0 | 0.0 | 0 | | | | | | |
| 16:51 | 2 | 0 | 0.0 | 0 | | | | | | |
| **合计** | 1,039,497 | | 545.0 | | | **合计** | 1,039,522 | | 545.0 | |

（S2 17:19 有 1 个 PUT 未列。CW 合计 PUT 比任务数多 19～41 个，是 reports/ 文件等小对象。）

### 3.3 校验
```
verify s1: dst_obj=1024000 missing=0 extra_obj=0 non_obj(reports etc)=4
verify s2: dst_obj=1024000 missing=0 extra_obj=0 non_obj(reports etc)=6
head 20b/obj_0712454 524288 REPLICA "13f3cafec38ac2cff05e54cfce651303" AES256 | src 524288 COMPLETED (同 ETag)
head 214/obj_0853057 / f7e/obj_0823206 / 67f/obj_0856114 / 141/obj_0025317 同上（S1、S2 都抽了这 5 个）
S1 目标桶 list-object-versions: 1,039,481 个版本（= 源数据版本 1,039,476 + _gen 2 + reports 3）
源桶 OperationsFailedReplication (Sum, 5 min): 0
```

## 4. 费用（不含存储）

单价（AWS Price List API，2026-10-22 拉取，同主测试）：跨区 $0.02/GB、复制 PUT $0.005/1,000（USW2-Requests-Tier1）、Batch $0.25/job + $1.00/百万对象 + manifest $0.015/百万源对象/job、生成 PUT $0.005/1,000（USE2）。

| 项 | 用量 | 费用 $ |
|---|---|---|
| S1 跨区传输 | 545.0 GB ≈ 507.6 GiB | 10.15 |
| S1 复制 PUT | 1,039,478 | 5.20 |
| S1 Batch 作业 + 对象 + manifest | 1 + 1,039,478 + 1.04M | 0.25 + 1.04 + 0.016 |
| **S1 小计** | | **16.65** |
| **S2 小计**（同上，1,039,481 任务） | | **16.65** |
| 数据生成 PUT（us-east-2） | ~1,039,481 次 | 5.20 |
| EC2 c7gn.16xlarge | 15:56:37 → ~16:04:40，约 8 min | ~0.53 |
| LIST（源 3 次全量 + 目标 4 次全量 + 删除前 list） | ~1.04M 对象/1000 每次 ≈ 1,040 次 × ~8 ≈ 8,300 次 | ~0.04 |
| DELETE（源 + 2 目标桶全部版本，约 312 万个） | — | 0（免费） |
| HEAD 抽样 | 20 次 | ~0 |
| 1 分钟 request metrics（2 个桶，各 ~1～2.5 h）+ Replication Metrics | — | 推测（未实测）：< $0.3 |
| **合计** | | **≈ $39.1**（低于 $80 止损线） |

说明：跨区传输按实际复制字节 545.0 GB = 507.6 GiB × $0.02 = $10.15（AWS 账单的 "GB" 按 2^30 计，与主测试口径一致）。源桶存储（500 GiB 约 2.3 h）和目标桶存储按要求不计，推测（未实测）各 < $0.1。

## 5. 完整可复现命令

脚本在 `scripts/`，原始数据在 `raw/`：
- `gen_small.sh`（数据生成 user-data：dd 512 KiB → 生成 1,024,000 行 cmds → s5cmd 2048 并发 → list 比对补传 → du → 结果写 `_gen/` → shutdown/terminate）
- `run_small.sh <s1|s2>`（复用预建目标桶 → 1 条规则复制配置 → 300 s → 1 个 job → 30 s 轮询；>90 min 或失败任务 >10,000 自动 cancel）
- `verify_small.sh <run>`（key+size 逐条比对 + 5 个 head-object 抽样）
- `delete_dst.sh <桶列表文件>`（r2 原样复用：s5cmd rm --all-versions → list 余量 → 删 metrics 配置 → 删桶）
- `analyze_small.py <run...>`（输出 `raw/<run>/analysis.json`）
- `repl-policy.json`、`batch-policy.json`、`ec2-s3.json`、`trust-*.json`
- 每次运行的 `runs/<run>/`：`replication.json`、`replication.applied.json`、`job0.manifest-generator.json`、`job0.report.json`、`jobs.txt`、`poll.log`、`describe-<JobId>.json`、`dst_buckets.txt`、`verify.txt`、`analysis.json`；`runs_<run>.out` 运行日志；`runs/src_keys.txt.gz` 源 (size,key) 列表

### 5.1 桶 / IAM / SG
```bash
E=1792770913; SRC=s3-crr-src-small-$E
aws s3api create-bucket --bucket $SRC --region us-east-2 --create-bucket-configuration LocationConstraint=us-east-2
aws s3api put-bucket-versioning --bucket $SRC --versioning-configuration Status=Enabled --region us-east-2
# 目标桶在数据生成前就建好并开 1 分钟 request metrics（官方：约 15 分钟后才开始上报）
for r in s1 s2; do D=s3-crr-dst-$r-$E
  aws s3api create-bucket --bucket $D --region us-west-2 --create-bucket-configuration LocationConstraint=us-west-2
  aws s3api put-bucket-versioning --bucket $D --versioning-configuration Status=Enabled --region us-west-2
  aws s3api put-bucket-metrics-configuration --bucket $D --region us-west-2 --id all --metrics-configuration Id=all
done
aws iam create-role --role-name s3crr-repl-$E  --assume-role-policy-document file://trust-s3.json
aws iam put-role-policy --role-name s3crr-repl-$E --policy-name repl --policy-document file://repl-policy.json
aws iam create-role --role-name s3crr-batch-$E --assume-role-policy-document file://trust-batch.json
aws iam put-role-policy --role-name s3crr-batch-$E --policy-name batch --policy-document file://batch-policy.json
aws iam create-role --role-name s3crr-gen-ec2-$E --assume-role-policy-document file://trust-ec2.json
aws iam put-role-policy --role-name s3crr-gen-ec2-$E --policy-name s3 --policy-document file://ec2-s3.json
aws iam attach-role-policy --role-name s3crr-gen-ec2-$E --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name s3crr-gen-ec2-$E
aws iam add-role-to-instance-profile --instance-profile-name s3crr-gen-ec2-$E --role-name s3crr-gen-ec2-$E
aws ec2 create-security-group --region us-east-2 --group-name s3crr-gen-$E --description "s3crr gen small" --vpc-id <DEFAULT_VPC>
```
`repl-policy.json`：
```json
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:GetReplicationConfiguration","s3:ListBucket"],"Resource":"arn:aws:s3:::s3-crr-src-small-<E>"},
{"Effect":"Allow","Action":["s3:GetObjectVersionForReplication","s3:GetObjectVersionAcl","s3:GetObjectVersionTagging"],"Resource":"arn:aws:s3:::s3-crr-src-small-<E>/*"},
{"Effect":"Allow","Action":["s3:ReplicateObject","s3:ReplicateDelete","s3:ReplicateTags"],"Resource":["arn:aws:s3:::s3-crr-dst-*-<E>/*"]}]}
```
`batch-policy.json`：
```json
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:InitiateReplication"],"Resource":"arn:aws:s3:::s3-crr-src-small-<E>/*"},
{"Effect":"Allow","Action":["s3:GetReplicationConfiguration","s3:PutInventoryConfiguration"],"Resource":"arn:aws:s3:::s3-crr-src-small-<E>"},
{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":"arn:aws:s3:::s3-crr-src-small-<E>/*"},
{"Effect":"Allow","Action":["s3:PutObject"],"Resource":"arn:aws:s3:::s3-crr-src-small-<E>/*"}]}
```

### 5.2 数据生成
```bash
aws ec2 run-instances --region us-east-2 --image-id <AL2023-arm64-AMI> --instance-type c7gn.16xlarge --key-name <KEY> \
  --iam-instance-profile Name=s3crr-gen-ec2-$E \
  --network-interfaces '[{"DeviceIndex":0,"SubnetId":"<SUBNET_us-east-2b>","Groups":["<SG>"],"AssociatePublicIpAddress":true}]' \
  --instance-initiated-shutdown-behavior terminate --user-data file://gen_small.sh
# gen_small.sh 主体：
dd if=/dev/urandom of=/dev/shm/src.bin bs=512K count=1; sync
python3 -c "import hashlib
with open('/root/cmds.txt','w') as f:
  for i in range(1024000):
    h=hashlib.md5(str(i).encode()).hexdigest()[:3]
    f.write(f'cp /dev/shm/src.bin s3://<SRC>/{h}/obj_{i:07d}\n')"
./s5cmd --numworkers 2048 --retry-count 10 run cmds.txt
AWS_REGION=us-east-2 ./s5cmd ls "s3://<SRC>/*" | awk '{print $4}' | sort > have.txt   # 比对 cmds 找缺失并补传
./s5cmd --numworkers 512 --retry-count 10 run retry.txt
./s5cmd du "s3://<SRC>/*"; shutdown -h now
```

### 5.3 单次运行（以 S1 为例）
`runs/s1/replication.json`：
```json
{"Role":"arn:aws:iam::<ACCOUNT_ID>:role/s3crr-repl-<E>","Rules":[{"ID":"rule0","Priority":1,"Status":"Enabled","Filter":{"Prefix":""},
 "DeleteMarkerReplication":{"Status":"Disabled"},
 "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-s1-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}}]}
```
```bash
aws s3api put-bucket-replication --bucket $SRC --region us-east-2 --replication-configuration file://runs/s1/replication.json
sleep 300
aws s3control create-job --region us-east-2 --account-id <ACCOUNT_ID> \
  --operation '{"S3ReplicateObject":{}}' \
  --report '{"Bucket":"arn:aws:s3:::<SRC>","Prefix":"reports/s1/job0","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}' \
  --manifest-generator '{"S3JobManifestGenerator":{"ExpectedBucketOwner":"<ACCOUNT_ID>","SourceBucket":"arn:aws:s3:::<SRC>","EnableManifestOutput":false,"Filter":{"EligibleForReplication":true}}}' \
  --priority 10 --role-arn arn:aws:iam::<ACCOUNT_ID>:role/s3crr-batch-<E> --no-confirmation-required --description crr-small-s1-job0
# 轮询（30 s）
aws s3control describe-job --region us-east-2 --account-id <ACCOUNT_ID> --job-id <JOB_ID> \
  --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed,ProgressSummary.Timers.ElapsedTimeInActiveSeconds]'
# 目标桶 1 分钟写入
aws cloudwatch get-metric-statistics --region us-west-2 --namespace AWS/S3 --metric-name BytesUploaded \
  --dimensions Name=BucketName,Value=<DST> Name=FilterId,Value=all --period 60 --statistics Sum --start-time ... --end-time ...
```
S2 相同，只把目标桶换成 `s3-crr-dst-s2-<E>`、report Prefix 换成 `reports/s2/job0`（S1 校验后先删 S1 目标桶，再 put-bucket-replication 指向 S2 桶）。

### 5.4 校验 / 清理
```bash
AWS_REGION=us-east-2 s5cmd --numworkers 256 ls "s3://<SRC>/*" | awk '{print $3,$4}' | grep -E ' [0-9a-f]{3}/obj_' | sort > src_keys.txt
AWS_REGION=us-west-2 s5cmd --numworkers 256 ls "s3://<DST>/*" | awk '{print $3,$4}' | grep -E ' [0-9a-f]{3}/obj_' | sort > dst_keys.txt
comm -3 src_keys.txt dst_keys.txt | wc -l        # 0
aws s3api head-object --bucket <DST> --key <key> --region us-west-2 --query '[ContentLength,ReplicationStatus,ETag,ServerSideEncryption]'
# 清理
aws s3api delete-bucket-replication --bucket $SRC --region us-east-2
AWS_REGION=us-west-2 s5cmd --numworkers 256 rm --all-versions "s3://<DST>/*"
aws s3api delete-bucket-metrics-configuration --bucket <DST> --id all --region us-west-2; aws s3api delete-bucket --bucket <DST> --region us-west-2
AWS_REGION=us-east-2 s5cmd --numworkers 256 rm --all-versions "s3://$SRC/*"; aws s3api delete-bucket --bucket $SRC --region us-east-2
```

## 6. 清理状态（2026-10-23 18:18 UTC 全部完成）

| 资源 | 状态 |
|---|---|
| EC2（c7gn.16xlarge） | 生成完自行 shutdown → terminated（16:04 后） |
| 生成机 SG | 已删 |
| IAM：s3crr-gen-ec2-1792770913（role + instance profile）、s3crr-repl-1792770913、s3crr-batch-1792770913 | 已删（list-roles / list-instance-profiles 按 epoch 过滤为空） |
| 源桶复制配置 | 已删（17:59） |
| `s3-crr-dst-s1-1792770913` | s5cmd rm --all-versions（1,039,481 个版本，0 错误）→ 余量 0 → 删 metrics 配置 → 删桶（17:12:53） |
| `s3-crr-dst-s2-1792770913` | 同上（1,039,484 行，0 错误）→ 删桶（18:11:04） |
| `s3-crr-src-small-1792770913` | rm --all-versions（1,039,485 行，0 错误）→ list-object-versions Versions=0、DeleteMarkers=0 → 删桶（18:17） |
| Batch job | 无 Active/Preparing/New/Suspended 作业 |
| 已有资源 | 未触碰 s3lambdatest2 及其他已有资源（s3lambdatest2 head-bucket 正常） |

源桶 `reports/` 下的 manifest.json 已检查（FailedTasksOnly，两次均无失败报告 CSV）。
