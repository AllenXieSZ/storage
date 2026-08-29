# storage-bench-agent

存储/性能实验助手 Agent。网页提交 → 异步执行 → 出报告。可扩展到任意"起环境→跑命令→收指标→出图→归档"的可重复实验。

- 设计: `DESIGN.md`（总体架构，目标 AWS Bedrock AgentCore）
- 阶段一落地: `PHASE1.md`（先用 Lambda+StepFunctions+DynamoDB 跑通价值，暂不上 AgentCore）

## 插件化设计（可扩展做其他测试）

骨架（起环境/收指标/画图/归档/清理/异步编排）与测试类型解耦。新增测试类型 = 实现一个 `TestPlugin` 子类：

```
core.py         # 通用骨架: TaskStore(DynamoDB) + TestPlugin抽象 + orchestrate编排器 + REGISTRY
plugin_fio.py   # 第一个插件: fio 存储压测 (ebs / fsx-ontap)
plugin_<x>.py   # 未来: iperf3(网络) / sysbench(DB) / s3-throughput / gds ... 照模板加
```

`params.testType` 决定用哪个插件（默认 fio）。加新测试只改：①新增 plugin 文件 ②前端多一个下拉项。**表结构/API/编排/报告/归档全通用，不改骨架。**

## 已完成（2026-08-29）
- [x] T1 DynamoDB 表 `storage-bench-tasks`（us-east-2, PAY_PER_REQUEST, GSI=status-createdAt-index）ACTIVE
- [x] T3 插件框架骨架 core.py + plugin_fio.py（注册机制冒烟通过）

## 进行中 / TODO
- [ ] T3 续: plugin_fio.provision 真实实现（先跑通 EBS gp3）
- [ ] T4 archive_report（S3 上传 + presign 带 region）+ Step Functions 编排
- [ ] T5 API Lambda（submit/status/list/cleanup）+ API Gateway + API Key
- [ ] T6 单页网页（提交/状态/历史）
- [ ] T7 飞书完成通知
- [ ] T8 端到端联调（EBS → FSx ONTAP）
- [ ] T9 IAM 最小权限 + cleanup 确认流

## 资源清单（用于清理，避免遗忘计费）
- DynamoDB: `storage-bench-tasks` (us-east-2) — 空表按需计费 ~$0
- Account: 386094880462 / region us-east-2 / EC2 默认 ohio key
