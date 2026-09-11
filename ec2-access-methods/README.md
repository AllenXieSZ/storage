# EC2 访问方式对比：SSH Key / Instance Connect / SSM + 堡垒机

## 三种访问方式核心对比

| 维度 | 传统 SSH Key | EC2 Instance Connect (EIC) | SSM Session Manager |
|---|---|---|---|
| **长期 key** | 要（key 常驻实例 authorized_keys） | 不要（临时公钥，60 秒有效） | 不要 |
| **公网 IP** | 要（或经堡垒机） | 要（除非用 EIC Endpoint 连私有实例） | **不要** |
| **入站端口** | 要开 22 | 要开 22 | **不用开任何入站端口** |
| **走什么协议** | SSH | SSH | 不走 SSH（SSM Agent 反向连 AWS） |
| **授权靠** | 谁持有私钥 | **IAM 权限** | **IAM 权限** |
| **客户端需求** | SSH 客户端 + 私钥 | AWS CLI + SSH 客户端 | AWS CLI + Session Manager 插件（浏览器也行） |
| **实例内需求** | sshd | sshd + EIC 组件（AL2/AL2023 预装） | **SSM Agent 已注册**（关键前提） |
| **审计** | 弱 | CloudTrail 记录推 key 动作 | 强（会话录制到 S3/CloudWatch） |
| **暴露面** | 大（长期 key + 公网端口） | 中（临时 key + 公网端口） | **最小（无端口无公网）** |

## 堡垒机 vs 普通 EC2

| 维度 | 堡垒机（Bastion） | 普通业务 EC2 |
|---|---|---|
| 本质 | 就是普通 EC2，特殊在定位+加固 | — |
| 机型 | 越小越省（t3.micro/small，只转发不跑业务） | 按业务负载选大机型 |
| 子网 | **公有子网** | **私有子网** |
| 公网 IP | 有（Elastic IP 固定入口） | 无 |
| 出网路由 | 经 IGW | 经 NAT Gateway |
| SG 入站 | 只放可信运维 IP（绝不 0.0.0.0/0）的 22 | 只放"来自堡垒机 SG"的 22（SG 引用 SG） |
| 软件 | 最小化 + SSH 加固（禁 root/禁密码/fail2ban/MFA） | 按业务装 |
| 不存长期私钥 | 用 agent forwarding / 临时凭证 | — |

## 关键要点

- **EIC 的 60 秒**：临时公钥只活 60 秒，约束的是"发起新连接"，连上后会话不受限；长任务前要重推 key。
- **EIC Endpoint**：较新特性，可连**无公网 IP 的私有实例**（早期 EIC 只能连有公网 IP 的）。
- **SSM 是现代首选**：无公网、无端口、无 key、IAM 授权 + 强审计，取代传统堡垒机。前提是 **SSM Agent 正常注册**（instance profile 有权限 ≠ agent 已注册）。
- **堡垒机不是特殊产品**：= 普通 EC2 + 网络位置（公有子网+EIP）+ SG 分层（私有机只信堡垒机 SG）+ 加固审计。
- **选型**：能用 SSM 优先 SSM（零暴露）；只能走 SSH 又不想留长期 key → EIC；多台私有机集中入口+审计 → 堡垒机（或 SSM 取代）。

## 实践对照（本环境）
- **btmart 实例**：SSM Agent 未注册 → 退而用 **EIC**（临时开 SG + 推 60s key + 60s 内连）。
- **FSx 测试机 / 跳板机**：用 **SSM Session Manager**（`aws ssm start-session`，无 key 无端口）。
