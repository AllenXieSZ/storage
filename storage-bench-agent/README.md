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
- [x] T3 插件框架 core.py + plugin_fio.py（provision 真实实现: EBS 建卷/mkfs/mount + FSx NFS 挂载）
- [x] T4 archive_report（S3 上传 report.md/PNG/raw + presign 带 region）
- [x] T5 API Lambda（api_lambda.py: submit/status/list/cleanup）+ orchestrator_lambda.py（异步编排）
- [x] T6 单页网页 web/index.html（提交表单/历史/5s轮询）
- [x] T7 飞书通知（notify_feishu 留桩，解耦: 写 DynamoDB 供外层推送）
- [x] config.py 默认值（VPC/subnet/AMI 查询自实环境）
- 全部 py 文件 compile 通过

## 进行中 / TODO
- [ ] 部署: 打包 Lambda(含 boto3 layer/matplotlib layer) + 建 API Gateway + API Key + IAM 执行角色
- [ ] T8 端到端联调: **起真实 EBS 实验跑通**（需伟伟确认预算, 单次<$1）→ 再 FSx ONTAP
- [ ] 编排上 Step Functions（避免单 Lambda 15min 上限）
- [ ] T9 IAM 最小权限收敛 + cleanup 二次确认

## 文件结构
```
core.py                 骨架: TaskStore + TestPlugin抽象 + orchestrate + archive/notify
plugin_fio.py           fio 插件(ebs/fsx-ontap), 内置踩坑规避
config.py               默认配置(VPC/subnet/AMI/bucket)
api_lambda.py           API Gateway 后端(4路由)
orchestrator_lambda.py  异步编排入口
web/index.html          单页网页(提交/历史/轮询)
requirements.txt        boto3 + matplotlib
```

## 资源清单（用于清理，避免遗忘计费）
- DynamoDB: `storage-bench-tasks` (us-east-2) — 空表按需计费 ~$0
- 默认: VPC vpc-0c28d2a9082ef222e / subnet-0c551a33e366d52d4(2c) / AMI ami-06475e8f54266e38e / ohio key
- 报告 bucket: s3lambdatest2/storage-bench-reports/
- Account: 386094880462 / region us-east-2
