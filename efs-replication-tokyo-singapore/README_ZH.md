# EFS 跨 Region 复制延迟实测：东京 → 新加坡

测试日期：2026-10-14（UTC）
源：ap-northeast-1（东京）｜目标：ap-southeast-1（新加坡）
负载：源端持续写 1 MiB 文件，每秒 10 / 100 / 1000 个三档，每档 20 分钟

## 1. 结论

| 档位（目标） | 实际写入速率 | 文件数 | 数据量 | 延迟 P50 | 延迟 P90 | 延迟 P99 | 延迟 Max | 最后写入 → 全部可见 | 丢失 |
|---|---|---|---|---|---|---|---|---|---|
| 10 个/s | 10.0 个/s | 12,000 | 11.7 GiB | **5.9 min** | 11.0 min | 12.8 min | **13.1 min** | 7.6 min | 0 |
| 100 个/s | 100.0 个/s | 120,000 | 117.2 GiB | **8.1 min** | 12.8 min | 14.9 min | **15.4 min** | 9.0 min | 0 |
| 1000 个/s | **690.7 个/s**（见说明） | 833,047 | 813.5 GiB | **54.7 min** | 62.8 min | 67.5 min | **69.9 min** | 55.9 min | 0 |

延迟 = 新加坡端第一次看到该文件且大小 = 1 MiB 的时间 − 东京端该文件 close 完成的时间。

1. **EFS 复制不是实时的，是周期性批量同步。** 目标端文件是一批一批出现的，每档 20 分钟内只观察到 3 批可见。`LastReplicatedTimestamp` 在低负载下大约每 **10 分钟**前进一次。
2. **10 / 100 个/s（约 10–100 MB/s）：最大延迟 13–15 分钟，在官方 RPO 15 分钟以内**（100 个/s 档 Max 15.4 min，略超 15 分钟）。
3. **约 700 个/s（约 690 MB/s，20 分钟写 813 GiB）：最大延迟约 70 分钟，超出 15 分钟 RPO 4 倍以上。** 这期间 `LastReplicatedTimestamp` 有约 **64 分钟**没有前进（09:52 → 10:56），CloudWatch `TimeSinceLastSync` 最高 **4163 s（69 min）**，和逐文件测出的最大延迟一致。
4. **三档都没有丢文件，也没有观察到"文件出现了但内容不完整"（partial = 0）。**
5. **1000 个/s 没写到**：单个 EFS（Elastic 吞吐）创建 1 MiB 小文件，实测聚合上限约 600–840 个/s。同时用 4 台写入端，平均也只有 690.7 个/s。另一个**不开复制**的对照 FS 也是同样的上限，说明上限来自 EFS 本身，与复制无关。
6. **监控建议**：用 CloudWatch `TimeSinceLastSync`（维度 FileSystemId + DestinationFileSystemId）设告警，例如 > 900 s。本次实测它和逐文件延迟的最大值吻合，可以直接作为 RPO 指标。

## 2. 图

### 2.1 10 个/s

复制延迟随写入时间变化：

![rate10 延迟](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/rate10_lag.png)

累计写入（东京）vs 目标端可见（新加坡）：

![rate10 累计可见](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/rate10_vis.png)

### 2.2 100 个/s

复制延迟随写入时间变化：

![rate100 延迟](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/rate100_lag.png)

累计写入（东京）vs 目标端可见（新加坡）：

![rate100 累计可见](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/rate100_vis.png)

### 2.3 1000 个/s（实际 690.7 个/s）

复制延迟随写入时间变化：

![rate1000 延迟](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/rate1000_lag.png)

累计写入（东京）vs 目标端可见（新加坡）：

![rate1000 累计可见](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/rate1000_vis.png)

### 2.4 CloudWatch TimeSinceLastSync（三档全程）

![TimeSinceLastSync](https://raw.githubusercontent.com/AllenXieSZ/storage/main/efs-replication-tokyo-singapore/results/time_since_last_sync.png)

## 3. 时间线（UTC）与 LastReplicatedTimestamp

| 时间 | 事件 |
|---|---|
| 08:45:28 – 09:05:28 | 10 个/s 档写入 |
| 09:14:59 – 09:34:59 | 100 个/s 档写入 |
| 09:55:33 – 10:15:39 | 1000 个/s 档写入（实际 690.7 个/s） |
| 11:11:33 | 1000 个/s 档最后一个文件在新加坡可见 |

`describe-replication-configurations` 中 `LastReplicatedTimestamp` 的变化（每 5 分钟采一次，完整数据见 `results/cw/last_replicated.tsv`）：

```
08:40:21 → 08:50:09 → 09:02:09 → 09:12:14 → 09:21:11 → 09:31:12 → 09:42:13 → 09:52:13
→（09:52:13 保持约 64 分钟不变，期间写入 813 GiB）→ 10:01:10（11:01 才更新到该值）→ 10:56:06
```

## 4. 测试环境

| 项目 | 配置 |
|---|---|
| 源 EFS | ap-northeast-1，Regional，加密，Elastic 吞吐，General Purpose，3 个 AZ 的 mount target |
| 目标 EFS | 由复制配置在 ap-southeast-1 自动创建（只读），2 个 AZ 的 mount target |
| 写入端 | 东京 c6in.8xlarge，AL2023，amazon-efs-utils（`mount -t efs -o tls,iam`）。10/100 档 1 台；1000 档 4 台 |
| 检测端 | 新加坡 m6i.2xlarge，AL2023，`mount -t efs -o tls,ro` 挂目标 FS |
| 时钟 | 三台都用 chrony（Amazon Time Sync），`chronyc tracking` 实测 offset < 0.1 ms，可忽略 |
| 检测粒度 | 每 5 秒扫一次新目录，延迟数值有 ±5 秒误差（相对分钟级延迟可忽略） |

## 5. 测试方法与完整命令

### 5.1 建 FS 与复制

```bash
# 源 FS（东京）
SRC=$(aws efs create-file-system --region ap-northeast-1 --encrypted --throughput-mode elastic \
  --performance-mode generalPurpose --tags Key=Name,Value=efs-repl-test --query FileSystemId --output text)
for s in <subnet-1a> <subnet-1c> <subnet-1d>; do
  aws efs create-mount-target --region ap-northeast-1 --file-system-id $SRC --subnet-id $s --security-groups <sg-tokyo>
done

# 复制到新加坡（EFS 自动创建目标 FS）
aws efs create-replication-configuration --region ap-northeast-1 --source-file-system-id $SRC \
  --destinations '[{"Region":"ap-southeast-1"}]'
DST=$(aws efs describe-replication-configurations --region ap-northeast-1 --file-system-id $SRC \
  --query 'Replications[0].Destinations[0].FileSystemId' --output text)

# 目标端 mount target（复制不会自动创建）
for s in <subnet-sg-a> <subnet-sg-b>; do
  aws efs create-mount-target --region ap-southeast-1 --file-system-id $DST --subnet-id $s --security-groups <sg-singapore>
done
```

SG：入站 TCP 2049，来源为 VPC CIDR。

### 5.2 挂载

```bash
# 写入端（东京）
sudo dnf install -y amazon-efs-utils python3
sudo mount -t efs -o tls,iam <SRC>:/ /efs
# 检测端（新加坡）
sudo mount -t efs -o tls,ro <DST>:/ /efs
```

### 5.3 写入 / 检测 / 心跳

目录结构为 `/efs/rate<R>/<epoch秒>/h<i>of<N>/f_<序号>`，每个文件 1 MiB。写入端在每个文件 close 后记录 `path,target_ts,start_ts,done_ts`。

```bash
# 心跳（东京）：每秒写 /efs/hb/<epoch秒>
nohup python3 scripts/heartbeat.py /efs &

# 检测端（新加坡）：每 5 秒扫描，记录每个文件第一次可见且 size=1MiB 的时间（seen.csv），以及不完整文件（partial.csv）
nohup python3 scripts/detector.py /efs /tmp/det10   5 rate10   &   # 每档单独启动
nohup python3 scripts/detector.py /efs /tmp/det100  5 rate100  &
nohup python3 scripts/detector.py /efs /tmp/det1000 5 rate1000 &

# 写入（东京），T0 为统一的起始 epoch 秒
python3 scripts/writer.py --root /efs --rate 10   --duration 1200 --t0 <T0> --host-index 0 --hosts 1 --procs 16 --out /tmp/w10.csv
python3 scripts/writer.py --root /efs --rate 100  --duration 1200 --t0 <T0> --host-index 0 --hosts 1 --procs 64 --out /tmp/w100.csv
# 1000 档：4 台同时跑，--host-index 0..3
python3 scripts/writer.py --root /efs --rate 1000 --duration 1200 --t0 <T0> --host-index <0-3> --hosts 4 --procs 256 --out /tmp/w1000_h<i>.csv
```

每档写完后，等目标端全部可见，再开始下一档。

### 5.4 采集与分析

```bash
# 每 5 分钟记录 LastReplicatedTimestamp
aws efs describe-replication-configurations --region ap-northeast-1 --file-system-id <SRC> \
  --query 'Replications[0].Destinations[0].[Status,LastReplicatedTimestamp]' --output text

# CloudWatch：TimeSinceLastSync（源区域，维度 FileSystemId + DestinationFileSystemId）、MeteredIOBytes、DataWriteIOBytes
SRC=<SRC> DST=<DST> bash scripts/cw_export.sh <start-iso> <end-iso> results/cw

# 逐文件延迟统计 + 图
python3 scripts/analyze.py rate10   results /tmp/det10/seen.csv   /tmp/w10.csv
python3 scripts/analyze.py rate100  results /tmp/det100/seen.csv  /tmp/w100.csv
python3 scripts/analyze.py rate1000 results /tmp/det1000/seen.csv /tmp/w1000_h0.csv /tmp/w1000_h1.csv /tmp/w1000_h2.csv /tmp/w1000_h3.csv
python3 scripts/plot_tsls.py results/cw/time_since_last_sync.csv results/time_since_last_sync.png
```

## 6. 文件说明

| 路径 | 内容 |
|---|---|
| `scripts/writer.py` | 控速写入，多进程，按秒调度 |
| `scripts/detector.py` | 目标端可见性检测 |
| `scripts/heartbeat.py` | 每秒心跳文件 |
| `scripts/analyze.py` | 逐文件延迟统计、每秒聚合、作图 |
| `scripts/cw_export.sh` / `plot_tsls.py` | CloudWatch 导出与作图 |
| `scripts/bench_create.py` | 小文件创建速率预测试 |
| `results/rate*_summary.json` | 每档统计 |
| `results/rate*_per_sec.csv` | 每秒写入数、该秒文件的延迟 P50 / Max |
| `results/cw/` | TimeSinceLastSync、MeteredIOBytes、DataWriteIOBytes、FS 大小、LastReplicatedTimestamp |

## 7. 限制

- 每档只测了一次，没有重复。延迟受 EFS 后台同步周期的相位影响，不同时间开始写，P50 可能差几分钟。
- 只测了 1 MiB 文件、只新建不修改、单目录树。大文件、频繁修改、上亿文件的场景没有测。官方文档说明这些场景可能超过 15 分钟。
- 1000 个/s 档实际只到 690.7 个/s，是单 EFS 小文件创建上限所致。
- 推测（未实测）：高负载下延迟变大，是因为一个同步周期内要传的数据量超出了单周期的复制能力（从第一个文件写入到最后一个文件可见共 76 分钟，按 813.5 GiB 折算平均约 190 MB/s）。EFS 复制的内部吞吐上限，文档没有公布。

## 8. 参考

- EFS Replication：https://docs.aws.amazon.com/efs/latest/ug/efs-replication.html
- EFS CloudWatch 指标（TimeSinceLastSync）：https://docs.aws.amazon.com/efs/latest/ug/efs-metrics.html
