# 存储实验助手 Agent — 阶段一落地方案 (PHASE1.md)

> 承接 DESIGN.md。阶段一目标：**先不上 AgentCore**，用最小组件跑通
> 「网页提交实验 → 异步执行 → 出 Markdown+图报告」完整闭环。
> 先支持 **EBS gp3 基线 + FSx ONTAP(NFS)** 两种存储的 fio 压测。
>
> 默认决策（伟伟可改）：鉴权=内网+API Key；报告=Markdown+PNG 存 S3 预签名；通知=飞书。

---

## 1. 阶段一架构（最小可用）

```
[网页(静态S3+CloudFront)] ──HTTPS+API Key──► [API Gateway]
                                                  │
                                          ┌───────┴────────┐
                                          ▼                ▼
                                  [Lambda: submit]   [Lambda: status/list]
                                          │                │
                                          ▼                ▼
                                  [DynamoDB 任务表]◄────────┘
                                          │ 触发(异步)
                                          ▼
                                  [Lambda: orchestrator] (或 Step Functions)
                                          │ 编排各步
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                   provision_env      run_fio         archive
                   (boto3 起EC2)     (SSM下发)       (S3+GitHub)
                          │               │               │
                          └──────► [S3: 报告bucket] ◄──────┘
                                          │ 完成
                                          ▼
                                   [飞书通知 伟伟]
```

- 阶段一用 **Lambda + (可选)Step Functions** 做编排，不引入 AgentCore（降低复杂度，先验证价值）。
- 长任务（fio 跑几十分钟）：orchestrator 用 **Step Functions**（支持等待/长流程）或 Lambda 异步链，避免单 Lambda 15min 上限。
- ⚠️ 单 Lambda 上限 15 分钟，**压测执行必须异步**：Lambda 只负责"下发 SSM 命令 + 轮询/回调"，实际 fio 在 EC2 上跑，Step Functions 轮询完成。

---

## 2. DynamoDB 任务表设计

**表名**：`storage-bench-tasks`
**主键**：`taskId` (String, 分区键) — 用 UUID

| 字段 | 类型 | 说明 |
|---|---|---|
| taskId | S | UUID，主键 |
| status | S | QUEUED / PROVISIONING / RUNNING / ANALYZING / ARCHIVING / DONE / FAILED |
| createdAt | S | ISO8601 |
| updatedAt | S | ISO8601 |
| params | M | 实验参数(见下) |
| resources | M | 创建的资源ID（ec2InstanceId / fsId / volumeId…）用于清理 |
| progress | S | 当前步骤人类可读描述 |
| resultUrl | S | 报告 S3 预签名链接（DONE 时填） |
| githubCommit | S | 归档 commit（可选） |
| errorMsg | S | FAILED 时的错误 |
| cost估算 | N | 可选，本次实验估算费用 |

**params 结构示例**：
```json
{
  "storageType": "ebs" | "fsx-ontap",
  "region": "us-east-2",
  "instanceType": "c6in.4xlarge",
  "az": "us-east-2c",
  "storageSpec": { "size": 500, "throughput": 1536, "volumeType": "gp3" },
  "fio": { "rw": "randread", "bs": "4k", "iodepth": 32, "numjobs": 4, "runtime": 300, "size": "10G" }
}
```

**GSI（可选）**：`status-createdAt-index`（按状态+时间查，做历史列表/看跑中任务）。
**TTL（可选）**：给已完成任务加 30 天过期，自动清老记录。

---

## 3. API 契约

Base: `https://<apigw>/v1`，Header: `x-api-key: <key>`

| 方法 | 路径 | 作用 | 请求体 | 响应 |
|---|---|---|---|---|
| POST | `/experiments` | 提交实验 | `params`（见上） | `{ "taskId": "..." }` (202) |
| GET | `/experiments/{taskId}` | 查单个任务 | — | 完整任务对象 |
| GET | `/experiments` | 列历史（分页） | `?status=&limit=&next=` | `{ items:[...], next: "..." }` |
| POST | `/experiments/{taskId}/cleanup` | 清理该任务资源 | — | `{ "status": "cleaning" }` |

- `POST /experiments` 立即写 QUEUED + 触发 orchestrator，**202 立即返回 taskId**（异步核心）。
- cleanup 单独接口 + 前端二次确认（延续"删除需人工确认"铁律）。

---

## 4. 网页原型（单页应用，静态托管）

三个区块，纯 HTML+JS（阶段一不需要框架）：

### ① 提交实验（表单）
```
存储类型:  [下拉: EBS gp3 / FSx ONTAP]
区域:      [us-east-2 (锁定)]
机型:      [c6in.4xlarge ▼]
AZ:        [us-east-2c ▼]
─ 存储参数 ─
  (EBS)  容量GB[500]  类型[gp3]  吞吐[1000]  IOPS[16000]
  (FSx)  容量GB[1024] 吞吐/HA[1536]  部署[SINGLE_AZ_2]
─ fio 负载 ─
  读写模式[randread ▼]  块大小[4k]  iodepth[32]  numjobs[4]  时长秒[300]  文件大小[10G]
             [ 提交实验 ]
```

### ② 任务状态（提交后跳转，轮询）
```
Task: 7f3a...  状态: ● RUNNING
进度: [PROVISIONING ✓] → [RUNNING ●] → [ANALYZING] → [ARCHIVING] → [DONE]
当前: fio 压测中 (已运行 2m30s / 5m)
资源: ec2 i-xxx | fsx fs-xxx
[ 取消/清理 ]     (每 5s 轮询 GET /experiments/{taskId})
```

### ③ 历史列表
```
时间           存储      负载        吞吐/IOPS      报告        状态
08-29 12:00   FSx ONTAP randread4k  7.4GB/s        [查看▶]     DONE
08-29 10:30   EBS gp3   randwrite   16000 IOPS     [查看▶]     DONE
...                                                            [清理未删资源]
```

托管：网页静态文件放 S3 + CloudFront（复用你的 OAC 部署笔记）。

---

## 5. 报告格式（Markdown + PNG，存 S3）

每个实验产出一个目录 `s3://<report-bucket>/<taskId>/`：
- `report.md` — 参数、环境、结果表、结论
- `throughput.png` / `iops.png` / `latency.png` — 对比图
- `fio_raw.json` — 原始 fio 输出（存档）

report.md 模板：
```markdown
# 存储实验报告 <taskId>
## 环境
- 存储: FSx ONTAP (fs-xxx, 1024GB, 1536MB/s/HA)
- 机型: c6in.4xlarge @ us-east-2c
## 负载
- randread 4k, iodepth=32, numjobs=4, 300s
## 结果
| 指标 | 值 |
|---|---|
| 吞吐 | 7.4 GB/s |
| IOPS | ... |
| P99 延迟 | ... |
## 结论
(LLM 生成草稿 + 对比历史同类实验)
```
- 报告链接：`aws s3 presign ... --region us-east-2 --expires-in 604800`（延续你的 presign 铁律，带 region）。

---

## 6. 工具实现要点（阶段一只做 4 个）

| 工具 | 阶段一实现 | 复用 |
|---|---|---|
| provision_env | boto3 run-instances (ohio key, 显式 AssociatePublicIp) + 建 EBS/FSx | 你的 EC2/FSx 创建经验 |
| mount+run_fio | SSM send-command 下发 fio，`--output-format=json` | fio 经验 + ssmrun.sh |
| collect+plot | 解析 fio JSON → matplotlib 出图 | parse_fio_ts.py |
| archive | 上传 S3 + presign + (可选)推 storage 仓库 | GitHub 流程 |

**关键坑规避（来自你的笔记）**：
- EC2 默认不分配公网 IP → run-instances 显式 `AssociatePublicIpAddress:true`。
- 改 fstab 换设备后 `daemon-reload`（若涉及）。
- FSx nconnect 首挂锁定、NFS rsize/wsize 可能被钳到 64K。
- fio group_reporting 是累计平均，要瞬时须 diff 相邻快照。

---

## 7. 阶段一任务清单（按顺序）

- [ ] T1. 建 DynamoDB 表 `storage-bench-tasks` + GSI
- [ ] T2. 建报告 S3 bucket（us-east-2）+ 网页托管 bucket + CloudFront/OAC
- [ ] T3. 写 4 个工具函数（provision / run_fio / collect_plot / archive），本地/子agent先跑通一次真实 EBS 实验
- [ ] T4. 写 orchestrator（Step Functions 状态机：QUEUED→…→DONE，每步回写 DynamoDB）
- [ ] T5. 写 3 个 API Lambda（submit / status+list / cleanup）+ API Gateway + API Key
- [ ] T6. 写单页网页（提交/状态/历史）+ 部署静态站
- [ ] T7. 接飞书完成通知
- [ ] T8. 端到端联调：网页提交 EBS 实验 → 看到报告；再联调 FSx ONTAP
- [ ] T9. IAM 最小权限收敛 + cleanup 确认流

**里程碑**：T1~T3 = 后端能跑通一次实验；T4~T8 = 网页闭环；T9 = 收尾加固。

---

## 8. 待伟伟确认

- [ ] 鉴权用「内网+API Key」阶段一 OK 吗？还是要 Cognito？
- [ ] Step Functions 做编排 OK 吗？（比纯 Lambda 链更适合长流程）
- [ ] 阶段一先做真实 EBS 实验跑通，同意吗？
- [ ] 报告要不要顺带推 storage 仓库归档，还是只存 S3？
- [ ] 确认后我从 **T1（建表）+ T3（工具函数）** 开始实际动手（起真实资源前会先跟你报预算）。

---
_v0.1 2026-08-29。阶段一刻意避开 AgentCore，先用成熟组件验证价值；价值确认后按 DESIGN.md 阶段二迁移。_
