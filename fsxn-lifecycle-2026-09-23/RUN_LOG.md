# RUN LOG — FSxN 全生命周期实验

**开始**: 2026-09-23 ~09:55 UTC
**账号/区域**: 386094880462 / us-east-2
**VPC**: vpc-0c28d2a9082ef222e
**跳板机**: i-0dffb881b2a90daa2 (us-east-2c, subnet-0c551a33e366d52d4)

## 环境准备
- ohio key: ~/.ssh/ohio.pem ✓
- storage repo: ~/.openclaw/workspace/storage (main) ✓
- fsxadmin 密码(拟设): FsxOntap#2026Ohio

## 时间线

### FS 创建
- 09:55 UTC `aws fsx create-file-system` → **fs-0806e114696713d2c** (CREATING)
  - Gen2 SINGLE_AZ_2, 1 HA pair, throughput 1536 MBps, SSD 2048 GiB
  - AutomaticBackupRetentionDays=0 (无自动备份)
  - subnet-0c551a33e366d52d4 (us-east-2c), sg-00ca35d004d81089b (vpc-internal)

### fio 客户端 EC2
- 09:57 UTC 启动 **i-0f94cb684f2cb38bb** (c6in.4xlarge, AL2023 x86_64, 172.31.35.22, us-east-2c)
  - key=ohio, SG=vpc-internal+MyIP, profile=fio-i7i-ssm-profile (SSM)

### FS AVAILABLE
- 10:03 UTC fs-0806e114696713d2c → AVAILABLE (创建耗时 ~11min: 09:52→10:03)
- 管理端点 (fsxadmin 登录): **172.31.44.166**

### SVM + FlexVol
- 10:05 UTC SVM **svm-02d9b4728dd51dcbd** (lifesvm) CREATED
- FlexVol **fsvol-0f92a7bfb7cd9692d** (lifevol, /lifevol, UNIX, 1.6TB, SE off, tiering NONE) CREATING
- ONTAP 版本: 9.18.1P6
- aggr: aggr1 (1.77TB, 1 HA pair)

### 数据写入
- 10:06→10:12 UTC 写 200×1GiB=200GB (~6min), NFS IP 172.31.47.6:/lifevol
- 注: FSx 把 rsize/wsize 钳制为 64K (已知行为)

### fio 启动 (1M randrw)
- 10:14:22 UTC fio 启动 (PID 28843): bs=1M randrw 50/50, direct=1, numjobs=4, iodepth=16, size=8G/job, runtime=14400s
- config: /tmp/life.fio, log: /tmp/fio_ts.log (status-interval=10s)
- **baseline 阶段 10:14 开始**，跑 5 分钟后开始扩 HA

### baseline 结果 (1HA/1536)
- 10:19 UTC: read ~513 MiB/s + write ~515 MiB/s = **~1028 MiB/s total**, ~1028 IOPS(1M块)

### 扩 HA (1→2)
- 10:19:53 UTC update-file-system HAPairs 1→2, StorageCapacity 4096, throughput/HA 1536
- 10:30:35 UTC HA 扩展 COMPLETED (**~10.5min**), HAPairs=2, StorageCapacity=4096, 2 aggregate
- aggr1: 1.53TB avail / 1.77TB; aggr2: 1.77TB avail / 1.77TB
- lifevol 当前在 aggr1, FlexVol

### FlexVol → FlexGroup 转换
- 10:31:04→10:31:20 UTC `volume conversion start` (diag) **~16秒 Job 64 succeeded** → 单constituent FlexGroup

### expand constituent 到每 aggr 8个
- 先 resize FlexGroup 320GB (member 320GB, 便于加constituent不超aggr容量, 空间guarantee=none薄置备)
- 10:33:15→10:34:27 expand +7 each aggr (Job 71, ~72s)
- 10:34:40→10:34:46 expand +1 aggr2 (Job 83, ~6s)
- **结果: 16 constituent, aggr1:8 / aggr2:8 (完全均衡)**; FlexGroup total 5.00TB, used 268GB (5%)
- 每 constituent ~320GB (数据摊在16个上, 各~17GB)

### fio 期间性能 (扩HA/转换/expand 过程)
- 10:35 fio 累计均值 read ~499 + write ~500 = ~999 MiB/s (扩HA/转换/expand 期间在线业务未中断, 稳定)

### 缩容 4096 → 2048 GiB
- 10:35:30 UTC 缩容请求 4096→2048 (未被80%水位拦截, 数据仅5%)
- 10:38 IN_PROGRESS 起, 进入 storage optimization 阶段, 进度缓慢爬升 (~0.7%/min)
- 11:08 fio 累计均值 ~878 MiB/s (缩容优化I/O占用略降吞吐, 业务未中断)
- 11:11 进度 ~20%

### 缩容 PAUSED (12:44, 进度45%)
- Message: "Redirecting client access for Volume(s) [lifevol__0001] has failed due to insufficient SSD IOPS, throughput capacity, or because the volume is full. Amazon FSx will retry in an hour."
- 根因: 原始constituent lifevol__0001 (转换来的, 数据集中) + fio 活跃占满吞吐 → 重定向失败
- 处置: 查各constituent用量 → volume rebalance 均衡 → 降fio压力/重试

### 诊断 (12:45)
- lifevol__0001 (原始constituent) 用 443.9GB/63%, 其余15个 constituent 各 ~0.5GB/0% → 严重偏斜
- Imbalance 92%, Max Constituent Imbalance **1474%** (数据全集中在转换来的原始constituent)
- 缩容正把 0001 从 aggr1_old 迁到新 aggr1 (temp__1027__93__lifevol__0001), fio吞吐占满导致重定向失败
- 快照占 234.6GB (缩容参考快照)
- 处置: volume rebalance 均衡 → 摊薄 0001 → 让 constituent 迁移可行
- 12:46 rebalance 首次失败: 快照计划在6h max-runtime窗口内 → 先 `volume modify -snapshot-policy none` 关快照策略
- 12:46:40 `volume rebalance start -max-runtime 4h` 成功启动 (state idle→scanning), Imbalance 89%, MaxConstituentImbalance 1432%
- 12:52 rebalance 进行中: lifevol__0001 443.9GB→294.8GB (46%), 数据摊向其他constituent
- 约束: "Exclude Files Stuck in Snapshot Copies: true" — 缩容参考快照(~128GB)钉住部分数据不能移, imbalance 卡在~78%
- fio 活跃占吞吐, rebalance 受限但持续推进
- 等: 缩容 PAUSED 每小时自动重试(~13:44), rebalance 摊薄后重试应成功

### 缩容第二次PAUSED (13:01, ~90%)
- Message 轮换到 lifevol__0006 重定向失败 (throughput/full)
- 发现3个快照钉住数据: convert.2026-09-23_103104 (239.7GB) + hourly_1105 (242.6GB) + hourly_1205 (243.8GB)
- 处置: 删除全部快照解钉 + 降fio压力
- 13:04 删完快照, lifevol__0001 仍 297GB(51%); fio 吞吐争用是重定向失败主因
- 处置: 降低 fio 压力(numjobs 4→1, iodepth 16→4)给缩容重定向让路, fio 不停(继续采样), 等下次重试

### 缩容反复PAUSED, 停fio放行 (13:16)
- 即使降低fio负载, 重定向仍因吞吐争用反复失败 (Message在各constituent间轮换: 0006/0014...)
- 关键结论: 缩容重定向需要短暂低I/O窗口, fio持续压测下无法完成
- 处置: **停fio**, 给缩容重定向完整吞吐余量, 让其一次完成

### 缩容完成 (13:24:42)
- 停fio后重定向顺利: 13:20 IN_PROGRESS → 13:23:56 COMPLETING/100% → **13:24:42 cap=2048 DONE**
- 缩容总耗时(含PAUSE/rebalance): 10:35:30 → 13:24:42 ≈ **2h49min** (其中反复PAUSE等待+rebalance+停fio)
- 关键: fio活跃时重定向反复失败, 停fio后~5min内完成

### 最终状态验证 (13:25)
- 2 aggregate 各 907GB (从1.77TB缩至~907GB, 2×907≈1.8TB SSD=2TB档)
- FlexGroup 保持 16 constituent, aggr1:8 / aggr2:8 (缩容未破坏结构)
- FlexGroup logical 4.98TB, used 258.8GB (5%), is-flexgroup=true ✓
- 全生命周期成功: 1HA→2HA→FlexVol转FlexGroup→expand 16 constituent→缩容2TB

### fio 各阶段吞吐均值
| 阶段 | 均值 MiB/s | min | max | IOPS(1M) |
|---|---|---|---|---|
| baseline 1HA/1536 | 1029.5 | 931.8 | 1126.4 | ~1027 |
| 扩HA 1→2 | 1003.2 | 819.2 | 1024.1 | ~1004 |
| 转FlexGroup+expand | 956.9 | 614.3 | 1126.4 | ~953 |
| 缩容优化(fio满载) | 811.9 | 193.0 | 1126.5 | ~847 |
| 缩容(fio降载) | 416.9 | 204.8 | 880.7 | ~416 |

### 耗时汇总
| 操作 | 时间 | 耗时 |
|---|---|---|
| 创建 FS | 09:52→10:03 | ~11min |
| 建SVM | 10:03→10:05 | ~2min |
| 建FlexVol | →10:06 | <1min |
| 写200GB(200×1GiB) | 10:06→10:12 | ~6min |
| fio baseline | 10:14→10:19 | 5min |
| 扩HA 1→2 | 10:19:53→10:30:35 | ~10.5min |
| FlexVol转FlexGroup | 10:31:04→10:31:20 | ~16秒 |
| expand到16 constituent | 10:33:15→10:34:46 | ~90秒 |
| 缩容4096→2048(含PAUSE/rebalance/停fio) | 10:35:30→13:24:42 | ~2h49min |
