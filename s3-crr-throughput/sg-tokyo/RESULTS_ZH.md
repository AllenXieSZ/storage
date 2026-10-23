# S3 CRR + Batch Replication 2 TiB 吞吐实测（第二轮）：新加坡 → 东京（场景 A）

> 实测日期：2026-10-23（UTC）。源 ap-southeast-1（新加坡），目标 ap-northeast-1（东京）。
> 本轮只跑场景 A（1 条复制规则 + 1 个 Batch Replication 作业）。B/C 等伟伟决定。
> 口径：MB = 10^6 字节，GB = 10^9 字节；费用按 GiB 计（同第一轮）。
> Ohio us-east-2 → Oregon us-west-2 的主测试见 [`../README_ZH.md`](../README_ZH.md)（12 次交替重复运行）。
> 注：下面表格中引用的 Ohio→Oregon 数字（381 s / 582 s / 267 s）来自 2026-10-22 的早期单次运行，已被主测试取代；主测试 12 次端到端均值 309 s（268～338 s），1 分钟峰值 10～16.7 GB/s。

## 1. 结论速览

| 线路 / 场景 | 规则 / 作业 | 端到端耗时（作业 CreationTime → TerminationDate） | Batch Active 时间 | MB/s（端到端） | MB/s（按 Active） | 对象/s（端到端） | 目标桶 1 分钟写入峰值 | 峰值分钟 PUT 数 | 准备阶段（→Active） | 失败 |
|---|---|---|---|---|---|---|---|---|---|---|
| **新加坡→东京 A** | 1 / 1 | **408 s**（6.8 min） | 351 s | **5,390** | 6,265 | 321 | **17,914 MB/s**（1,074.9 GB/min） | **64,067**（≈1,068 对象/s） | ≤31 s | 0 |
| Ohio→Oregon A | 1 / 1 | 381 s（6.4 min） | 326 s | 5,770 | 6,745 | 344 | （当时没开 request metrics） | — | ≤31 s | 0 |
| Ohio→Oregon A2（复测） | 1 / 1 | 582 s（9.7 min） | 526 s | 3,780 | 4,181 | 225 | 13,977 MB/s（838.6 GB/min） | 49,986 | ≤32 s | 0 |
| Ohio→Oregon C（4 规则，峰值最高的一次） | 4 / 4 | 267 s | 219 s | 8,251 | 10,041 | 492 | 14,384 MB/s（863.0 GB/min） | 51,443 | ≤36 s | 0 |

数据完全一样：**131,072 个对象 × 16 MiB = 2,199,023,255,552 B（2 TiB）**，key 布局 `g{0,1}/p{0..3}/<md5前2位>/obj_NNNNN`，跟第一轮一致。

**结论：**
1. **已实测**：新加坡→东京的端到端耗时是 **408 s**，落在 Ohio→Oregon 同配置两次实测（381 s、582 s）之间。**换到这条亚太线路后没有变慢**，作业整体耗时处在第一轮"同配置重复跑"的波动范围内。
2. **已实测**：数据面峰值反而比 Ohio→Oregon 高。东京目标桶最高的 1 分钟写了 **1,074.9 GB / 64,067 个 PUT（约 17.9 GB/s、143 Gbps，约 1,068 对象/s）**；第一轮所有场景的峰值都在 13.3～14.4 GB/s、每分钟约 5 万个 PUT。
3. **已实测**：这次的写入曲线**爬坡更慢、峰更尖**。第一轮是"半分钟爬坡 → 2 分钟稳定 14 GB/s → 收尾"；这次作业进入 Active 后头约 3 分钟只写了少量数据（00:07 那分钟 19 GB，00:08 那分钟 41 GB），然后在 00:09～00:11 这 3 分钟里搬完约 2,138 GB（占 97%）。两轮的"真实数据窗口"都在 2.5～3 分钟左右。
4. **已实测**：准备阶段（S3 自动生成 manifest，13 万对象）也很稳定：创建后 ≤31 s 进入 Active，跟第一轮的 31～36 s 一样。
5. **已实测**：Batch 进度计数还是成批跳（0 → 1,156 → 3,808 → 43,346 → 127,051 → 131,072）。真实速度要看目标桶的 1 分钟 request metrics。
6. 推测（未实测）：东京峰值更高、但爬坡更慢，可能是 S3 Batch Replication 的后台并发是按区域/时段动态分配的（比如这次的 UTC 00:05 是新加坡早上 8 点，负载可能更低），而不是跨区距离（新加坡↔东京约 5,300 km，Ohio↔Oregon 约 3,000 km）造成的。每条线路只有 1～2 个样本，不能下"亚太线路更快"的结论。
7. 推测（未实测）：从这两轮看，2 TiB / 16 MiB 对象级别的 Batch Replication 耗时主要受服务端调度（爬坡和尾巴）影响，跨区 RTT 不是主要因素。如果换成 KB 级小对象（每个对象一次跨区往返），RTT 的影响可能会明显变大，需要另测。

**一句话：** 2 TiB 新加坡→东京，Batch Replication 端到端 6.8 分钟，真实搬数据约 3 分钟，峰值 17.9 GB/s，速度跟 Ohio→Oregon 同一量级（还略快）。但**每 GB 的费用是后者的 4.5 倍**（$0.09 对比 $0.02/GB）。

## 2. 环境

| 项 | 值 |
|---|---|
| 源桶 | `s3-crr-src-sg-<E>`，ap-southeast-1，Versioning=Enabled，SSE-S3 默认加密 |
| 目标桶 | `s3-crr-dst-a-tk-<E>`，ap-northeast-1，Versioning=Enabled，开 1 分钟 request metrics（`Id=all`）；**作业创建前**就已开启 |
| 数据 | 131,072 × 16 MiB，同一个 `/dev/urandom` 源文件反复上传（ETag `29a4c7fea2bc41052c9153cc46a08131`，单段上传） |
| 数据生成 | **c8gn.16xlarge**（ap-southeast-1a，AL2023 arm64，200 Gbps；新加坡没有 c7gn，换成同为 64 vCPU arm64 的 c8gn），s5cmd v2.3.0 `--numworkers 1024`，通过 user-data 执行，不需要 SSH/SSM 登录。**122 s 传完 2 TiB（约 18.0 GB/s）**，0 错误 |
| 复制配置 | 1 条规则 `Prefix=""`（全桶），DeleteMarkerReplication=Disabled，StorageClass=STANDARD，开 Replication Metrics，**没开 RTC** |
| Batch 作业 | `S3ReplicateObject`，S3 自动生成 manifest（`S3JobManifestGenerator`，`EligibleForReplication=true`，不按复制状态过滤），Priority=10，不需要确认，报告 FailedTasksOnly，写到源桶 `reports/a/job0` |
| 计时 | `describe-job` 每 30 s 轮询一次；耗时取 API 返回的 `CreationTime` → `TerminationDate` |
| 跟第一轮的差别 | 只改了 region、桶名后缀（`-sg-`/`-tk-`）和生成机机型；脚本、规则、作业参数完全相同 |

第一轮的 A 有 131,074 个任务（多了 `reports/` 下面的小文件），这次源桶是新的，复制前 `reports/` 是空的，所以**正好 131,072 个任务**。作业结束后才写入的 2 个 report 文件（manifest.json 210 B + .md5 32 B）被 CRR 实时规则顺手复制到了目标桶，所以目标桶比源桶多 2 个对象，字节数可以忽略。

## 3. 原始计时

### 3.1 poll.log（30 s 轮询）
```
2026-10-23T00:05:43Z +0s   New        0      0      0 active=0
2026-10-23T00:06:14Z +31s  Active 131072      0      0 active=8
2026-10-23T00:06:45Z +62s  Active 131072      0      0 active=39
2026-10-23T00:07:16Z +93s  Active 131072      0      0 active=70
2026-10-23T00:07:47Z +124s Active 131072      0      0 active=100
2026-10-23T00:08:17Z +155s Active 131072      0      0 active=131
2026-10-23T00:08:48Z +185s Active 131072   1156      0 active=162
2026-10-23T00:09:19Z +216s Active 131072   1156      0 active=193
2026-10-23T00:09:50Z +247s Active 131072   3808      0 active=224
2026-10-23T00:10:21Z +278s Active 131072   3808      0 active=255
2026-10-23T00:10:52Z +309s Active 131072  43346      0 active=285
2026-10-23T00:11:22Z +340s Active 131072  43346      0 active=316
2026-10-23T00:11:53Z +370s Active 131072 127051      0 active=347
2026-10-23T00:12:24Z +401s Completing 131072 131072  0 active=351
2026-10-23T00:12:55Z +432s Complete   131072 131072  0 active=351
```
describe-job：`CreationTime 00:05:42.792` → `TerminationDate 00:12:30.783` = **407.99 s**，`ElapsedTimeInActiveSeconds=351`，Total/Succeeded/Failed = 131072/131072/0。

### 3.2 目标桶（东京）CloudWatch 1 分钟写入
```
00:06   2 PUT       0.0 GB        1 MB/s
00:07   1,154 PUT  19.3 GB      322 MB/s
00:08   2,446 PUT  41.0 GB      684 MB/s
00:09  34,113 PUT 572.3 GB    9,538 MB/s
00:10  64,067 PUT 1,074.9 GB 17,914 MB/s   ← 峰值
00:11  29,295 PUT 491.5 GB    8,191 MB/s
00:12   1 PUT       0.0 GB        0 MB/s   （作业结束后写入的 report 小文件）
```
- 合计 131,078 个 PUT / 2,199.0 GB，与源一致（多出的几个是 report 小文件）。
- 对比第一轮 A2（Ohio→Oregon，1 条规则）：`5,701 → 13,977 → 13,458 → 3,513 MB/s`，是 4 个分钟桶的"梯形"；这次是 00:09～00:11 的"尖峰"，前面还有约 2 分钟的低速爬坡。

### 3.3 数据生成
```
upload_start 2026-10-22T23:57:28Z
upload_end   2026-10-22T23:59:30Z   (122 s, 131072 成功, 0 错误)
s5cmd du: 2199023255552 bytes in 131072 objects
EC2 启动 23:57:17Z → terminate 00:00:32Z（约 3.3 min）
```

### 3.4 校验
- 源桶 `g*` 的 (size, key) 列表和目标桶全量列表排序后用 `comm -3` 比较：**缺失 0**，目标桶只多出 2 个 `reports/a/job0/.../manifest.json(.md5)` 小文件。目标桶 16 MiB 对象数 = 131,072。
- 抽样 head-object：目标 ContentLength=16777216，ETag=`29a4c7fe…` 与源一致，ReplicationStatus=REPLICA；源对象 ReplicationStatus=COMPLETED。
- 作业 `NumberOfTasksFailed=0`；失败报告只有 manifest.json（没有失败条目）。
- 源桶复制指标 `OperationsFailedReplication` 每分钟都是 0。

## 4. 费用估算（不含存储费）

单价都来自 **AWS Price List API（2026-10-23 拉取）**：

| 项 | 单价 | 来源（usagetype） |
|---|---|---|
| 跨区传输 新加坡 → 东京 | **$0.09/GB** | AWSDataTransfer `APS1-APN1-AWS-Out-Bytes`（"Asia Pacific (Singapore) data transfer to Asia Pacific (Tokyo)"） |
| 复制 PUT（按**目标**区域计价） | **$0.0047/1,000** | AmazonS3 `APN1-Requests-Tier1`（东京 STANDARD PUT） |
| Batch 作业费 | $0.25/作业 | `APS1-BatchOperations-Jobs` |
| Batch 对象费 | $1.00/百万对象 | `APS1-BatchOperations-Objects` |
| Batch 生成 manifest | $0.015/百万个源桶对象 | `APS1-BatchOperations-Manifest` |
| RTC（本测试**没开**） | $0.015/GB | `APS1-APN1-S3RTC-Out-Bytes` |
| 对照：Ohio→Oregon 传输 | $0.02/GB | `USE2-USW2-AWS-Out-Bytes`（第一轮） |

### 4.1 复制本身的费用（2,048 GiB、131,072 对象）
| 线路 / 场景 | 传输 GiB | 传输费 $ | 复制 PUT 数 | PUT 费 $ | 作业费 $ | Batch 对象费 $ | Manifest 费 $ | **小计 $** |
|---|---|---|---|---|---|---|---|---|
| **新加坡→东京 A** | 2,048 | **184.32** | 131,072 | 0.616 | 0.25 | 0.131 | 0.002 | **185.32** |
| Ohio→Oregon A（第一轮） | 2,048 | 40.96 | 131,074 | 0.655 | 0.25 | 0.131 | 0.002 | 42.00 |
| 推测（未实测）：新加坡→东京 B（2 规则） | 2,048 | 184.32 | 131,072 | 0.616 | 0.50 | 0.131 | 0.004 | 185.57 |
| 推测（未实测）：新加坡→东京 C（4 规则） | 2,048 | 184.32 | 131,072 | 0.616 | 1.00 | 0.131 | 0.008 | 186.08 |

- **99.5% 是跨区传输费。** 新加坡出区 $0.09/GB 是 Ohio→Oregon 的 4.5 倍，所以同样 2 TiB 的复制，费用从 $42 涨到 $185。
- 推测（未实测）：定价页 Replication 部分没有列源端 GET 费用；Replication Metrics 和目标桶 request metrics 只开了约 15～20 分钟，按 CloudWatch 计费的部分 < $0.05，没放进表里。需要等次日 Cost Explorer 核对。
- B/C 两行是按单价套算的，**没有实测**。按第一轮的结论，它们的速度应该不会更快。

### 4.2 测试附带成本（单列）
| 项 | 用量 | 单价 | 费用 $ |
|---|---|---|---|
| EC2 c8gn.16xlarge（生成数据） | 约 3.3 min（23:57:17 → 00:00:32） | $4.3539/h（Price List API，ap-southeast-1 Linux On-Demand） | ~0.24 |
| 生成数据的 PUT | 131,072 | $0.005/1,000（`APS1-Requests-Tier1`） | ~0.66 |
| 删除目标桶版本（DELETE） | 131,074 | 免费 | 0 |
| LIST（校验） | 约 270 次 | $0.005/1,000 | < 0.01 |
| 存储 | — | 按要求不算 | — |

**本轮实际花费约 $186.2**（预算 $220，上限 $260）。

### 4.3 保留的源桶存储费（等待 B/C）
- 源桶 `s3-crr-src-sg-<E>`（ap-southeast-1）有 2,048 GiB 的 STANDARD 数据（外加 3 个 report 小文件）。
- 单价 $0.025/GB-月（`APS1-TimedStorage-ByteHrs`，前 50 TB 档）→ **$51.2/月，约 $1.68/天（约 $0.07/小时）**。
- 不再跑 B/C 的话，应尽快删除源桶（删除步骤见 5.4）。

## 5. 完整可复现命令

所有文件都在 `s3-crr-bench/sg-tokyo/`：`gen_sg.sh`（user-data 数据生成）、`run_scenario.sh`（第一轮脚本只改了 region 和桶名：`SR=ap-southeast-1`、`DR=ap-northeast-1`）、`analyze.py`（CloudWatch region 改成 ap-northeast-1）、`repl-policy.json`、`batch-policy.json`、`ec2-s3.json`、`trust-*.json`，以及 `runs/a/` 下的 replication.json、job0.manifest-generator.json、job0.report.json、poll.log、describe-*.json。

### 5.1 桶 / IAM / SG
```bash
E=$(date +%s); SR=ap-southeast-1; DR=ap-northeast-1
SRC=s3-crr-src-sg-$E; DST=s3-crr-dst-a-tk-$E
aws s3api create-bucket --bucket $SRC --region $SR --create-bucket-configuration LocationConstraint=$SR
aws s3api put-bucket-versioning --bucket $SRC --versioning-configuration Status=Enabled --region $SR
aws s3api create-bucket --bucket $DST --region $DR --create-bucket-configuration LocationConstraint=$DR
aws s3api put-bucket-versioning --bucket $DST --versioning-configuration Status=Enabled --region $DR
aws s3api put-bucket-metrics-configuration --bucket $DST --region $DR --id all --metrics-configuration Id=all   # 作业前开 1 分钟 request metrics
aws iam create-role --role-name s3crr-repl-$E  --assume-role-policy-document file://trust-s3.json
aws iam put-role-policy --role-name s3crr-repl-$E --policy-name repl --policy-document file://repl-policy.json
aws iam create-role --role-name s3crr-batch-$E --assume-role-policy-document file://trust-batch.json
aws iam put-role-policy --role-name s3crr-batch-$E --policy-name batch --policy-document file://batch-policy.json
aws iam create-role --role-name s3crr-gen-ec2-$E --assume-role-policy-document file://trust-ec2.json
aws iam put-role-policy --role-name s3crr-gen-ec2-$E --policy-name s3 --policy-document file://ec2-s3.json
aws iam attach-role-policy --role-name s3crr-gen-ec2-$E --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name s3crr-gen-ec2-$E
aws iam add-role-to-instance-profile --instance-profile-name s3crr-gen-ec2-$E --role-name s3crr-gen-ec2-$E
SG=$(aws ec2 create-security-group --region $SR --vpc-id <DEFAULT_VPC> --group-name s3crr-gen-$E --description "s3crr gen egress only" --query GroupId --output text)
```
`repl-policy.json`（目标用通配符，方便 B/C 复用同一个角色）：
```json
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:GetReplicationConfiguration","s3:ListBucket"],"Resource":"arn:aws:s3:::<SRC>"},
{"Effect":"Allow","Action":["s3:GetObjectVersionForReplication","s3:GetObjectVersionAcl","s3:GetObjectVersionTagging"],"Resource":"arn:aws:s3:::<SRC>/*"},
{"Effect":"Allow","Action":["s3:ReplicateObject","s3:ReplicateDelete","s3:ReplicateTags"],"Resource":["arn:aws:s3:::s3-crr-dst-*-tk-<E>/*"]}]}
```
`batch-policy.json`：同第一轮（`s3:InitiateReplication`、`GetReplicationConfiguration`、`PutInventoryConfiguration`、`GetObject(Version)`、`PutObject`，资源都是源桶）。

### 5.2 数据生成（c8gn.16xlarge，user-data = gen_sg.sh）
```bash
aws ec2 run-instances --region ap-southeast-1 --image-id <AL2023-arm64-AMI> --instance-type c8gn.16xlarge \
  --iam-instance-profile Name=s3crr-gen-ec2-$E \
  --network-interfaces '[{"DeviceIndex":0,"SubnetId":"<SUBNET_1a>","Groups":["<SG>"],"AssociatePublicIpAddress":true}]' \
  --instance-initiated-shutdown-behavior terminate --user-data file://gen_sg.sh
```
`gen_sg.sh` 的核心部分（完整版见文件）：
```bash
export AWS_REGION=ap-southeast-1
curl -sL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-arm64.tar.gz | tar xz
dd if=/dev/urandom of=/dev/shm/src.bin bs=1M count=16; sync
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
touch /root/DONE
```
完成后用 SSM `AWS-RunShellScript` 读 `/var/log/gen.log` 确认，然后 `aws ec2 terminate-instances`。

### 5.3 场景 A
```bash
./run_scenario.sh a
```
展开等价于：
```bash
aws s3api put-bucket-replication --bucket $SRC --region ap-southeast-1 --replication-configuration file://runs/a/replication.json
sleep 300
aws s3control create-job --region ap-southeast-1 --account-id <ACCOUNT_ID> \
  --operation '{"S3ReplicateObject":{}}' \
  --report '{"Bucket":"arn:aws:s3:::<SRC>","Prefix":"reports/a/job0","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}' \
  --manifest-generator '{"S3JobManifestGenerator":{"ExpectedBucketOwner":"<ACCOUNT_ID>","SourceBucket":"arn:aws:s3:::<SRC>","EnableManifestOutput":false,"Filter":{"EligibleForReplication":true}}}' \
  --priority 10 --role-arn arn:aws:iam::<ACCOUNT_ID>:role/s3crr-batch-<E> --no-confirmation-required --description crr-bench-a-job0
aws s3control describe-job --region ap-southeast-1 --account-id <ACCOUNT_ID> --job-id <JOB_ID>      # 每 30 s
python3 analyze.py a     # 汇总 + 目标桶 CloudWatch（ap-northeast-1，FilterId=all）
```
`runs/a/replication.json`：
```json
{"Role":"arn:aws:iam::<ACCOUNT_ID>:role/s3crr-repl-<E>","Rules":[
 {"ID":"rule0","Priority":1,"Status":"Enabled","Filter":{"Prefix":""},
  "DeleteMarkerReplication":{"Status":"Disabled"},
  "Destination":{"Bucket":"arn:aws:s3:::s3-crr-dst-a-tk-<E>","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}}]}
```

### 5.4 校验 / 清理
```bash
aws s3 ls s3://$SRC/g --recursive --region ap-southeast-1 | awk '{print $3,$4}' | sort > src_keys.txt
aws s3 ls s3://$DST/  --recursive --region ap-northeast-1 | awk '{print $3,$4}' | sort > dst_keys.txt
comm -3 src_keys.txt dst_keys.txt        # 只剩 reports/ 下的 2 个小文件
aws s3api delete-bucket-replication --bucket $SRC --region ap-southeast-1
aws s3api delete-bucket-metrics-configuration --bucket $DST --id all --region ap-northeast-1
AWS_REGION=ap-northeast-1 s5cmd --numworkers 256 rm --all-versions "s3://$DST/*"
aws s3api delete-bucket --bucket $DST --region ap-northeast-1
# 后续删除源桶（B/C 跑完或决定不跑时）：
AWS_REGION=ap-southeast-1 s5cmd --numworkers 512 rm --all-versions "s3://$SRC/*"
aws s3api delete-bucket --bucket $SRC --region ap-southeast-1
aws iam delete-role-policy --role-name s3crr-repl-$E --policy-name repl;   aws iam delete-role --role-name s3crr-repl-$E
aws iam delete-role-policy --role-name s3crr-batch-$E --policy-name batch; aws iam delete-role --role-name s3crr-batch-$E
```

## 6. 清理确认（2026-10-23 ~00:20 UTC）
- EC2 c8gn.16xlarge 已终止（00:00:32 发起终止，状态 terminated，运行约 3.3 min）。
- SG `s3crr-gen-<E>` 已删除。
- IAM：`s3crr-gen-ec2-<E>`（role + instance profile + 内联策略 + SSM 托管策略附加）已删除。
- 目标桶 `s3-crr-dst-a-tk-<E>`：先删 metrics 配置，再用 s5cmd 删光全部 131,074 个版本（Versions=0、DeleteMarkers=0），然后删除桶。
- 源桶复制配置已删除（`get-bucket-replication` 返回 ReplicationConfigurationNotFoundError），避免后续误复制。
- **保留**：源桶 `s3-crr-src-sg-<E>`（ap-southeast-1，2 TiB，约 $1.68/天）；IAM 角色 `s3crr-repl-<E>`、`s3crr-batch-<E>`（只有内联策略，限定这个源桶和 `s3-crr-dst-*-tk-<E>`，IAM 本身不收费），留给 B/C 复用；不跑 B/C 时跟源桶一起删。
- 没碰其他任何已有资源（账号里原有的 `s3crr_role_for_*` 角色都没动）。
