# AWS 安全练习题库（30 题）

> 生成日期：2026-09-04
> 目的：针对伟伟的薄弱点（云安全）做强化训练。范围对标 AWS Security Specialty + 实战。
> 范围：IAM/权限模型、STS/角色/联合身份、网络安全(SG/NACL/VPC)、数据加密(KMS/S3/EBS)、密钥与密文管理、检测与审计(CloudTrail/Config/GuardDuty/SecurityHub)、主机/实例安全(SSM/IMDS/Inspector)、边界与治理(SCP/Org/权限边界)、DDoS/WAF、合规。
> 用法：伟伟每次过 **2 道**，AI 逐题完整批改（①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点）。
> 铁律：批改必须完整展开五板块；答完即停，不预告不催。每批改完立即写入 NOTES_ZH.md 并推 GitHub。
> 回答任何点必须先查 AWS 官方文档核实，不确定标注；"旧缺点/旧限制"须查最新文档验证是否仍成立。

---

## 一、IAM 与权限模型

**Q1.** IAM 的 User / Group / Role / Policy 各是什么？Identity-based policy 和 Resource-based policy 有什么区别？一次请求的权限是怎么被评估出来的（allow/deny 的判定逻辑）？

**Q2.** IAM Role 和 IAM User 的本质区别是什么？为什么"给 EC2/Lambda 用 Role 而不是把 Access Key 写进代码"是最佳实践？Role 是怎么拿到临时凭证的（STS AssumeRole）？

**Q3.** 什么是 Permissions Boundary（权限边界）？它和 SCP、Identity policy、Session policy 的关系是什么？最终有效权限是如何"取交集"的？

**Q4.** 什么是 SCP（Service Control Policy）？它在 AWS Organizations 里作用于谁？SCP 能授予权限吗？SCP 和 IAM policy 一起时如何生效？

**Q5.** IAM policy 的结构（Effect/Action/Resource/Condition/Principal）是怎样的？Condition 常见键（aws:SourceIp、aws:PrincipalOrgID、aws:MultiFactorAuthPresent 等）怎么用？显式 Deny 优先吗？

## 二、STS、跨账号与联合身份

**Q6.** STS 是什么？AssumeRole / AssumeRoleWithSAML / AssumeRoleWithWebIdentity 三者分别用于什么场景？临时凭证包含哪些字段、能撤销吗？

**Q7.** 跨账号访问怎么做（Role trust policy + AssumeRole + ExternalId）？ExternalId 解决什么问题（confused deputy 混淆代理人）？

**Q8.** 什么是 IAM Identity Center（原 AWS SSO）？和联合身份（SAML/OIDC）、IdP 的关系？和 Cognito 的区别（内部员工 vs 外部用户）？

**Q9.** EKS 里 IRSA（IAM Roles for Service Accounts）和 EKS Pod Identity 是什么？如何让 Pod 拿到 AWS 权限而不用长期密钥？对照 GCP Workload Identity。

## 三、网络安全

**Q10.** Security Group（安全组）和 Network ACL（NACL）有什么区别？（有状态/无状态、allow/deny、作用层级、规则顺序）分别在什么层级生效？

**Q11.** VPC 里如何做网络隔离与最小暴露？公有/私有子网、NAT Gateway、Internet Gateway、路由表如何配合让私有实例只出不进？

**Q12.** VPC Endpoint（Gateway Endpoint vs Interface Endpoint / PrivateLink）是什么？如何让流量不经公网访问 S3/其他服务？对照 GCP Private Google Access / PSC。

**Q13.** 什么是 AWS WAF、Shield（Standard/Advanced）、Cloud Armor 对照？各防护什么（应用层攻击 vs DDoS）？⚠️注意别和 GCP Shielded VM 混。

## 四、数据加密与密钥管理

**Q14.** KMS 是什么？CMK（现叫 KMS key）的类型（AWS managed / customer managed / AWS owned）区别？Envelope Encryption（信封加密）原理是什么？

**Q15.** KMS key policy 和 IAM policy 在授权 KMS 使用时如何配合？为什么 KMS 的访问控制"双重把关"？Grants 是什么？

**Q16.** S3 加密方式：SSE-S3 / SSE-KMS / SSE-C / 客户端加密 各是什么区别？SSE-KMS 的 Bucket Key 解决什么成本问题？

**Q17.** EBS 加密、RDS 加密、快照加密是怎么工作的？默认加密（account-level default encryption）如何开启？跨账号/跨区共享加密快照要注意什么（KMS key 授权）？

**Q18.** Secrets Manager 和 SSM Parameter Store（SecureString）有什么区别？Secrets Manager 的自动轮换（rotation）如何工作？为什么不该把密钥写进环境变量/代码？

## 五、检测、审计与监控

**Q19.** CloudTrail 是什么？记录什么（management events / data events / insights）？如何保证审计日志不可篡改（log file validation、S3 Object Lock、多账号聚合）？

**Q20.** AWS Config 是什么？它和 CloudTrail 的区别（配置状态快照/合规评估 vs API 调用审计）？Config Rules 如何做合规检查与自动修复（remediation）？

**Q21.** GuardDuty 是什么？它靠哪些数据源检测威胁（VPC Flow Logs / DNS logs / CloudTrail）？发现（findings）如何处理？对照 GCP Security Command Center。

**Q22.** Security Hub 是什么？它如何聚合 GuardDuty/Inspector/Config 的发现并对照标准（CIS/PCI/AWS FSBP）？和单个检测服务的关系？

**Q23.** VPC Flow Logs、CloudWatch Logs、Athena 在安全分析里各扮演什么角色？如何用它们排查一次可疑访问？

## 六、主机 / 实例 / 工作负载安全

**Q24.** EC2 的 IMDS（实例元数据服务）是什么？IMDSv1 和 IMDSv2 的区别（session token 防 SSRF）？为什么强制 IMDSv2 是安全最佳实践？对照 GCP metadata 的 Metadata-Flavor 头。

**Q25.** SSM Session Manager 相比开放 22 端口 SSH 有什么安全优势？为什么推荐"无公网 IP + 无入站 SG + IAM 鉴权"访问实例？

**Q26.** Amazon Inspector 是什么？扫描什么（EC2/ECR 镜像/Lambda 的漏洞 CVE）？和 GuardDuty（威胁检测）的分工区别？

**Q27.** 什么是 Nitro Enclaves、NitroTPM、EC2 Secure Boot？它们分别防护什么？对照 GCP Confidential VM / Shielded VM。

## 七、边界、治理与最佳实践

**Q28.** AWS Organizations 的多账号策略（OU 结构、SCP、集中日志账号、安全账号）如何设计？为什么"多账号"本身就是一种安全隔离？

**Q29.** 最小权限（least privilege）如何落地？IAM Access Analyzer、Access Advisor（last accessed）、策略模拟器如何帮你收敛权限？

**Q30.** 综合：一个"纵深防御（defense in depth）"的 AWS 安全架构应该覆盖哪些层（身份/网络/数据/检测/主机/治理）？把前 29 题的手段串成一套体系，并对照 GCP 的等价能力。

---
