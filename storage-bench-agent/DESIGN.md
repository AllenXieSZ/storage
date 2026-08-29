# 存储/性能实验助手 Agent — 技术方案 (v0.1 草案)

> 目标：把「起环境 → 跑存储性能压测 → 收数据 → 出图 → 写结论 → 归档」这套目前手动做的流程，
> 做成一个可通过**内部网页**触发的 Agent，部署在 **AWS Bedrock AgentCore Runtime**，**异步**执行。
> 覆盖存储类型：**S3 / EBS / FSx / EFS**。
>
> ⚠️ 文档中 AWS 服务细节基于 AWS 官方文档（bedrock-agentcore devguide）核实，标注了来源；
> 仍在快速演进的部分（AgentCore 较新）以官方最新文档为准。

---

## 0. 需求确认（伟伟 2026-08-29 拍板）

- 网页：**内部简单工具页**（填参数 → 跑 → 看结果/历史），非正式对外站。
- 存储范围：**S3、EBS、FSx（ONTAP/Lustre/OpenZFS）、EFS**。
- 执行模式：**异步**（提交后后台跑，完成通知，可接受几十分钟~2h）。
- 部署目标：**AgentCore Runtime**。

---

## 1. 关键技术前提（AWS 官方文档核实）

| 事项 | 结论 | 来源 |
|---|---|---|
| AgentCore Runtime 是什么 | serverless 托管环境，跑 agent 代码，支持长时执行/会话隔离/可观测 | docs.aws.amazon.com/bedrock-agentcore .../agents-tools-runtime.html |
| 对外接口 | Runtime 暴露 `/invocations` HTTP 端点，收 `{"prompt": ...}` JSON，返回结果；**不是网页**，网页需自建前端调它 | 官方 runtime quickstart |
| 执行时长上限 | microVM 计算：最长 **28800s (8h)**；capacity provider / runtime instances：最长 **1209600s (14天)** | .../runtime-lifecycle-settings.html |
| 部署方式 | 写 Python agent（Strands Agents / LangGraph 框架）→ `agentcore configure` → `agentcore launch`；工具自动建 IAM 角色/容器/端点 | 官方 quickstart |
| 组件套件 | Runtime / Gateway / Memory / Identity / Observability / Code Interpreter / Browser | aws.amazon.com/bedrock/agentcore/resources/ |
| 默认 region | 工具默认 us-west-2，可 `-r` 指定；我们用 **us-east-2**（跟现有实验资源同区） | 官方 quickstart |

**结论**：本项目实验最长 ~2h，AgentCore microVM 的 8h 上限足够，**可以让实验在 Runtime 内同步跑完**；
但为了网页体验（不能让用户等 2h HTTP 连接），仍采用**异步架构**（见 §3）。

---

## 2. 整体架构

```
┌─────────────────┐
│  内部网页 (前端)  │  填实验参数 / 看任务状态 / 看历史报告
└────────┬────────┘
         │ HTTPS
┌────────▼─────────────────────┐
│ API Gateway + Lambda (控制面) │  鉴权 + 提交任务 + 查状态 + 列历史
└────────┬─────────────────────┘
         │ ①写任务 ②触发
   ┌─────▼──────┐        ┌──────────────────┐
   │ DynamoDB   │◄───────┤ AgentCore Runtime │  Agent 大脑：规划+调工具
   │ (任务表)    │  状态回写 │  (存储实验助手)     │
   └────────────┘        └────────┬─────────┘
                                  │ agent 调 tool
              ┌───────────────────┼────────────────────┐
              ▼                   ▼                    ▼
      [起环境工具]          [压测工具]            [归档工具]
   创建EC2+挂存储      SSM下发fio/收数据      推GitHub + 存S3报告
   (S3/EBS/FSx/EFS)   解析+画图              + 清理(需确认)
              │                   │                    │
              └──────► [S3: 报告/图表] ◄───────────────┘
```

### 为什么这么分层
- **前端 / 控制面 / Agent / 工具** 解耦：网页只跟 API Gateway 打交道，不直连 AgentCore。
- **DynamoDB 做任务台账**：submit 立即返回 taskId，前端轮询/查状态，天然异步。
- **Agent 只负责编排**，重活（起机器、跑 fio）交给工具层执行。

---

## 3. 异步执行流程

```
1. 用户网页填参数 → POST /experiments
2. Lambda: 写 DynamoDB (status=QUEUED, taskId) → 异步 invoke AgentCore Runtime → 立即返回 {taskId}
3. AgentCore Agent 开始编排：
   - status=PROVISIONING  起 EC2 + 挂载目标存储
   - status=RUNNING       SSM 下发压测，采集结果
   - status=ANALYZING     解析数据 + 画图 + LLM 写结论
   - status=ARCHIVING     推 GitHub + 存 S3
   - status=DONE / FAILED 回写结果链接
4. 前端轮询 GET /experiments/{taskId} 看状态；DONE 后展示报告链接
5. (可选) 完成后通过飞书/邮件通知伟伟
```

- **每一步都回写 DynamoDB status**，前端实时可见进度（对标你 fio 四阶段监测的思路）。
- 实验 <2h 用 microVM 同步跑；若将来要跑几小时~几天的超长基准，改用 runtime instances(14天)。

---

## 4. Agent 的工具集（tools）

按你手动实验流程拆，每个 tool = 一个可调用函数：

| # | 工具 | 输入 | 干什么 | 复用现有 |
|---|---|---|---|---|
| 1 | `provision_env` | 机型/AZ/存储类型/规格 | 创建 EC2（默认 ohio key）+ 挂目标存储 | 你现有 SSM/create 流程 |
| 2 | `mount_storage` | 存储类型+ID | S3/EBS/FSx/EFS 各自挂载逻辑 | S3 Files/NFS 挂载笔记 |
| 3 | `run_fio` | 负载参数(bs/iodepth/rw/runtime) | SSM 下发 fio，采集 JSON 输出 | 你的 fio 压测经验 |
| 4 | `collect_metrics` | 任务ID | 拉 CloudWatch + fio 结果，解析 | parse_fio_ts.py 思路 |
| 5 | `plot_results` | 指标数据 | 生成吞吐/IOPS/延迟对比图 | 你的画图脚本 |
| 6 | `summarize` | 结果数据 | LLM 写实验结论草稿 | — |
| 7 | `archive` | 报告+图 | 推 storage 仓库 + 存 S3 + 预签名链接 | 你的 GitHub 流程 |
| 8 | `cleanup` | 资源列表 | terminate EC2/删存储（**需人工确认**） | ebs-cleanup.py 思路 |

### 各存储类型的挂载差异（工具 2 要处理）
- **EBS**：attach volume → mkfs → mount（本地块设备，最快基线）
- **S3**：mountpoint-s3 或 S3 Files（`mount -t s3files`，见 S3 Files 部署笔记）
- **FSx**：NFS 挂载（ONTAP/OpenZFS 走 NFS，Lustre 走 lustre client + 可选 EFA）
- **EFS**：`mount -t efs` (amazon-efs-utils, TLS)

---

## 5. 分阶段落地计划

### 阶段一：跑通价值（先不上 AgentCore，1~2 周）
- 用 OpenClaw 子 agent 能力实现 tool 1~7（你已有大部分脚本）
- 做最简网页：表单(参数) + 状态页 + 报告列表；后端 Lambda + DynamoDB
- 先只支持 **EBS + 1 种 FSx** 的 fio 压测，跑通"网页提交→异步跑→出报告"闭环
- **目标**：验证这条链好不好用、报告格式对不对

### 阶段二：迁移到 AgentCore（验证有价值后）
- 用 Strands Agents 框架写 agent，`agentcore configure/launch` 部署到 Runtime (us-east-2)
- 接入 AgentCore Observability（CloudWatch trace）看 agent 轨迹
- 前端/Lambda 改为 invoke AgentCore 端点
- 扩全 4 种存储 + 更多负载模式

### 阶段三：增强（可选）
- Agent Memory 记住"常用实验模板"
- 自动对比历史实验（同机型不同存储的趋势）
- 成本估算（每次实验烧多少钱）

---

## 6. 成本 & 安全注意

- **成本**：AgentCore 按调用/时长计费 + 实验起的 EC2/存储另计。异步长任务注意 Runtime 时长计费。
- **⚠️ 资源清理**：延续你"实验完资源保留"的习惯有烧钱风险 → `cleanup` 工具默认**不自动删**，
  但任务表记录所有创建的资源 ID，网页提供"一键清理"（需确认）避免遗忘计费。
- **权限**：Agent 执行角色最小权限（只在指定 VPC/tag 起资源）；删除类操作强制人工确认。
- **鉴权**：内部网页加简单鉴权（Cognito 或内网 + IAM），别裸奔在公网。

---

## 7. 待确认 / 下一步

- [ ] 网页鉴权方式（Cognito / 内网限制）？
- [ ] 阶段一先做哪种存储的 fio 跑通？（建议 EBS gp3 基线 + FSx ONTAP）
- [ ] 报告格式：Markdown + PNG 图？（复用你 PPT/报告风格）
- [ ] 完成通知渠道：飞书？
- [ ] 是否要我下一步出「阶段一详细任务清单 + 网页原型 + Lambda/DynamoDB 表结构」？

---

_v0.1 2026-08-29 初稿。AgentCore 细节以 AWS 官方文档为准，本方案随实现迭代。_
