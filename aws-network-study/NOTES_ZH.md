# AWS 网络面试题 30 道 — 批改记录（NOTES）

> 题库见 `QA_ZH.md`（10 模块 30 题，每题含标准答案要点 + AWS↔GCP 对照 + 速查表）。
> 流程：①出题干（不给答案）→ ②伟伟作答 → ③五板块批改（逐点对照/参考答案+原理/概念深入/AWS↔GCP对照/评分+记忆点）。

## 批改进度（截至 2026-09-06）

| 题 | 分数 | 关键点 / 纠错 |
|---|---|---|
| Q1-Q6 | — | 流程错误（直接讲解未让作答），仅当讲解 |
| Q7 | 2.5/5 | IGW=双向1:1 NAT答对；**"无公网IP能否经IGW上网"答反了**（正确=不能，缺的是公网IP不是路由）|
| Q8 | 4/5 | NAT GW托管/NAT实例=EC2/不接受入站/单AZ 对；漏"每AZ放一个NAT GW"高可用 |
| Q9 | 4.5/5 | 私网访问S3三路径(NAT出公网/Gateway EP/Interface EP)+推荐Gateway 全对；漏成本安全展开 |
| Q10 | 4/5 | Gateway改路由表·S3/DDB vs Interface·其他服务·收费 对；漏"Gateway免费""Interface靠ENI+私有IP" |
| Q11 | 2/5 | **PrivateLink答反了**——它**允许CIDR重叠**（答"不能重叠"错）；是"私有连接不经公网"非"加密链接"；核心=消费者Interface EP+提供者NLB/Endpoint Service，单向消费者→提供者 |
| Q12 | 3/5 | 不传递+CIDR不能重叠+跨区域跨账号 对；**"VPC多的问题"答成"性能/延迟"错**——Peering不加延迟，真痛点=管理复杂度(N²连接+路由维护)，大规模用TGW |
| Q13 | 4/5 | hub-spoke+传递+CIDR不重叠 对；**"大于5个VPC"数字不准**(无硬门槛)；漏"连接数N²→N优势""TGW route table控制互通" |
| Q14 | 5/5 | 3VPC全互联=Peering 3条/TGW 3 attachment 对；**扩第4个VPC Peering新增3条不是4条**(总6)，TGW只加1个 |
| Q15 | 4/5 | VPN走公网/DX不走公网·带宽·延迟·成本·上线 五维度对；漏"加密"维度(VPN加密/DX本身不加密→MACsec或VPN over DX)+"DX主+VPN备"组合 |
| Q16 | 0/5 | 三种VIF不会。**Private VIF=单VPC / Public VIF=AWS公共服务(S3) / Transit VIF=经TGW多VPC**。选VIF靠BGP按目的IP自动路由 |

**下次从 Q17 继续**（VGW vs TGW + BGP路由传播；然后 Q18 进 Route 53）。

## 穿插答疑（已讲透，记要点）
- 出向路由不管入向/回程 → 应答靠 NAT连接跟踪 + SG有状态(NACL无状态要手开回程端口)，回程走local路由
- AWS/GCP路由匹配规则 vs Linux OS → 两层路由：OS层(Linux固定最长前缀,与云厂商无关)+VPC SDN层(AWS绑子网/GCP priority+tag,与OS无关)
- AWS NAT是SNAT还是DNAT → NAT GW=纯SNAT只出不进；IGW对有公网IP实例=双向1:1(出SNAT入DNAT)；DNAT靠IGW1:1或ALB/NLB
- blackhole路由场景 → 被动(target删了故障状态,排查断网)+主动(TGW隔离恶意流量/阻断目的地/防环路/分段)
- EC2跨VPC访问EFS走不走PrivateLink → **不走**。EFS靠每AZ一个Mount Target(带私有IP的ENI)，跨VPC用Peering/TGW打通连私有IP(NFS 2049)。PrivateLink用于服务API(SSM/ECR/KMS)或NLB后自建/SaaS
- VPC Peering路由target = `pcx-xxxx`(peering连接ID)，Destination=对端CIDR，双向各加一条
- on-prem经DX不同VIF到不同目的地 → 靠每VIF跑BGP通告各自可达网段，on-prem路由器按目的IP最长前缀自动选VIF
