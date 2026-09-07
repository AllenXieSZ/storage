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

| Q17 | 3/5 | VGW单VPC/TGW多VPC对；漏route propagation=BGP学到路由自动填路由表；BGP双向自动交换 |
| Q18 | 3.5/5 | 4种路由策略对；Alias vs CNAME→Alias能zone apex裸域/免查询费/自动跟随IP,CNAME不能apex |
| Q19 | 2.5/5 | VPC内置DNS(.2)+Private Hosted Zone没答；inbound/outbound方向说反(inbound=on-prem查AWS,outbound=AWS查on-prem) |
| Q20 | 3.5/5 | ALB L7/NLB L4/GWLB对；漏NLB三卖点(保留源IP+静态IP+PrivateLink)+GWLB=GENEVE串安全设备 |
| Q21 | 2.5/5 | ALB跨AZ对；cross-zone没答(ALB默认开且免费,NLB默认关开了收跨AZ费) |
| Q22 | 3/5 | TG三类型点到；IP类型是容器/on-prem/跨VPC的IP非另个ALB；粘性靠cookie(AWSALB)非instance id |
| Q23 | 3/5 | CDN本质/Origin/OAC替代OAI对；Cache Policy空白；缓存键漏header/cookie；"动态不能加速"错(不能缓存≠不能加速,边缘TLS+骨干回源仍加速);OAC锁源站非防盗链(防盗链=Signed URL/Cookie) |
| Q24 | 3.5/5 | GA加速网络非内容/L4/游戏场景对；CloudFront半没展开；漏GA 2个静态anycast IP；漏跨region秒级故障切换(无DNS延迟) |

**下次从 Q25 继续**（VPC Flow Logs；然后 Q26 EC2 网络带宽/单流5Gbps）。

## 穿插答疑补充（09-07）
- 为什么GA是2个IP → 来自2个独立network zone,互为**网络入口层冗余备份**;单IP=入口单点故障;2个IP不是负载均衡是互备;客户端两个都配才拿满冗余。与"跨region故障切换"是两层不同高可用(入口层 vs 后端region层)。
- GCP LB为何单IP而GA要2个 → GCP全局anycast IP锚定"Google全球网络整体"(所有POP统一通告),冗余**内建对用户透明**,网内reroute;AWS GA把"network zone故障隔离单元"**显式暴露**给你=2个IP。融合产品(GCP LB+CDN+骨干一体) vs 拆分服务(AWS ELB/CloudFront/GA各管一块)。GA主打固定IP写白名单,故必须2个避免固定IP成单点。

## ⚠️ 待求证疑点（09-07，伟伟标记，后续找人核实）
**单流(per-flow)带宽上限 AWS vs GCP 差异**：
- AWS官方文档明确：单流5Gbps(非CPG)/10Gbps(同CPG)/25Gbps(ENA Express同AZ)；出IGW多流<32vCPU限5Gbps。来源 docs.aws.amazon.com/AWSEC2/.../ec2-instance-network-bandwidth.html
- GCP官方文档(docs.cloud.google.com/compute/docs/network-bandwidth)：**出VPC(外部路由)单流硬上限=3Gbps**；VPC内部普通机型无到处引用的单流硬数字(可接近实例总带宽)，高端C4N机型明确标50Gbps单流。
- ⚠️我(助手)先前口头给的"GCP单流~20Gbps"**无官方依据,已撤回**。
- **疑点**：GCP普通机型"VPC内部单流"到底有没有统一硬上限?官方未给统一值。需实测或找GCP官方确认具体机型的内部单流上限。伟伟将找人求证。

## 穿插答疑补充（09-07，续）
- **ENA Express 客户端要不要改/走不走TCP** → 完全透明,普通IP+TCP/UDP socket零改动;应用看到的还是TCP,Nitro网卡底层用SRD搬运(多路径+硬件重排序)到对端还原成TCP。要改/用专门库(libfabric/MPI/NCCL)的是**EFA**(OS-bypass),别和ENA Express混。启用只需实例侧开EnaSrdEnabled(双方都开,同AZ),UDP要额外开EnaSrdUdpEnabled。
- **MTU/巨型帧对性能提升多大** → 不是银弹,分场景:①高吞吐大块+CPU因海量小包吃紧(存储/备份/25G+跑满)→有帮助,主要**降CPU+略提有效吞吐**,量级个位数~十几%,**非翻倍**;②延迟型/小包/小事务/NFS小文件/出公网→几乎无用。原理=省per-packet开销(传1GB:1500需70万包,9001只需11.6万包,少6倍)+提有效载荷比(头部占比3-4%→0.5%)。**现代ENA的GRO/TSO/LRO卸载已吃掉巨型帧大部分CPU优势**,差距比十年前小。⚠️全路径一致才有效,出VPC回落1500。5-15%是估计非实测,能测就测(实测高于推理)。

## 批改进度补充（Q25-Q30，09-07 完成，全题库收官）
| 题 | 分数 | 关键点/纠错 |
|---|---|---|
| Q25 | 2.5/5 | Flow Logs记IP/端口/连接对;**"不记录什么"没答**(流元数据非抓包,看内容用Traffic Mirroring;不记Amazon DNS/IMDS/DHCP等);层级漏子网/VPC;目的地漏CloudWatch Logs/Firehose;字段漏**ACCEPT/REJECT**;排查=5-tuple过滤+看REJECT+配CloudTrail(谁改规则)+GuardDuty(拿Flow Logs当数据源) |
| Q26 | 2/5 | 带宽范围不准(小实例<10G);不懂单流5Gbps原理(ECMP多路径+同流走单路径保序);**把ENA Express和EFA搞混**(突破单流是ENA Express/SRD,EFA是HPC OS-bypass);EFA非TCP;CPG单流10G对;up to=突发对 |
| Q27 | 3/5 | ENI多网卡对;**ENI/ENA非同类升级**(逻辑接口 vs 底层适配器两维度);ENA=SR-IOV增强联网;ENA Express=ENA+SRD透明;EFA=含ENA(有IP)+OS-bypass通道(libfabric给MPI/NCCL);"EFA可无IP"不准;漏OS-bypass灵魂;漏ENI故障转移(可迁移网卡) |
| Q28 | 3/5 | MTU定义/1500/9001/分片对;**VPC内9001 vs 出IGW 1500边界没答**(同region peering 9001/TGW 8500/出IGW·跨region·VPN回落1500);巨型帧好处(省per-packet开销)没展开;**黑洞机制**=大包带DF位撞小MTU被丢+PMTUD的ICMP(Type3Code4)被NACL拦→发送方收不到通知→大包反复丢→能ping不能传大文件;修复=NACL放行ICMP或MSS clamping |
| Q30 | 3.5/5 | 主入口链(Route53 geo→WAF+CloudFront→LB多AZ+TG)+Web/DB隔离+S3 Gateway Endpoint省钱+DX主VPN备接TGW 答得好;漏出网NAT GW/其他API Interface Endpoint/NACL兜底/Route53 Resolver双向DNS/可观测(Flow Logs+GuardDuty);"Web VPC/DB VPC"应为private-app/private-data子网 |
| Q29 | 讲解(未答) | IPv6**无NAT**(地址天生全球唯一可路由);VPC双栈,子网/64;**EIGW=专为IPv6而生**=去掉地址翻译的NAT GW,有状态只出不进;IGW=IPv6双向;实现只出不进=路由::/0→EIGW。EIGW为IPv6而生根因:IPv6干掉NAT,而NAT顺便承担的"只出不进"没人管了,故抽出其挡入站能力(去翻译)做EIGW |

**✅ AWS网络题库 Q1-Q30 全部收官(09-07)。**

## 穿插答疑补充（09-07,尾）
- **EIGW为什么为IPv6而生** → IPv4"只出不进"由NAT Gateway顺便实现(翻译+挡入站打包);IPv6无NAT(地址天生可路由),挂IGW是双向不安全,"只出不进"空缺→AWS把NAT的"有状态出站+挡入站"抽出、去掉地址翻译,做成EIGW专给IPv6。IPv4有NAT兜底不需要EIGW。本质:NAT=翻译+挡入站(IPv4);EIGW=只挡入站不翻译(IPv6)。
