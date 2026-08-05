# AWS vs GCP 网络产品深度对比（Review 稿）

> 目的：供伟伟 review，确认后做成 PPT（NetApp 风，上传 S3+GitHub）。
> 铁律：每条论点/数字均来自 AWS/GCP **官方文档**并标来源；官方未明确处标"我不确定/官方未明确"，绝不臆造。
> 核实日期：2026-08-05。

---

## 维度 1：全球骨干网 & 网络分层

| 项目 | AWS | GCP |
|---|---|---|
| 网络分层机制 | **无 Premium/Standard 用户可选分层**（官方无该产品） | **Network Service Tiers 两层可选**：Premium / Standard |
| 默认路由 | 跨区/跨AZ 流量"始终走 AWS 全球骨干，从不经公网" | Premium=cold potato（尽早入网/尽晚出网）；Standard=hot potato（尽早交ISP） |
| 入向路由 | 官方未提层级化 BGP metric（不确定） | Premium：全球 PoP 等价 BGP metric，最近 PoP 入网；Standard：仅通告 region 最近 PoP |
| 物理层加密 | 所有数据中心间流量物理层自动加密 | Premium 骨干保护到最后一英里 |
| SLA | 无单独骨干 SLA（未取到，不臆造） | Premium 99.99% / Standard 99.9%（引 Compute SLA） |
| 骨干规模 | 近 2000 万公里光缆、39 Region/123 AZ/750+ CloudFront PoP | 官方公开光缆里程未取到（不确定） |
| Standard 限制 | — | 仅区域外部IP/区域LB/Cloud NAT；不支持全局IP、Cloud CDN、Cloud VPN网关、全局ALB |

**核心结论**：GCP 把"全球骨干 vs ISP 出网"做成**可计费选择产品**（Premium cold-potato / Standard hot-potato）；**AWS 无等价分层**，默认全程走自有加密骨干（相当于只给 Premium 那一档，不暴露"降级省钱"选项）。
来源：cloud.google.com/network-tiers/docs/overview · docs.aws.amazon.com/vpc/latest/peering · aws.amazon.com/about-aws/global-infrastructure/

---

## 维度 2：VPC / 内网架构 & 互联

**2.1 VPC 模型（最根本差异）**
- **AWS VPC = 区域级**（子网锁单 AZ）；**GCP VPC = 全局级**（子网区域级，一个 VPC 可横跨多 region）。均官方核实。

**2.2 Peering**
- AWS VPC Peering 支持跨区走骨干加密；GCP VPC Network Peering 延迟/吞吐同 VPC 内。
- **两家都不支持传递路由**（GCP 官方明确；AWS 为通识，本次未取到明确否定原文→标注）。

**2.3 中心化互联：TGW vs NCC**
| | AWS Transit Gateway | GCP Network Connectivity Center |
|---|---|---|
| 模型 | 网络中转 hub | 全局 hub-and-spoke，单 hub 跨多 region spoke |
| 加密 | 可开 Encryption control 强制 VPC 间加密 | 未提强制加密开关（不确定） |
| 多云 | — | 原生 Cross-Cloud Interconnect 连 AWS(Partner,Preview)/OCI |
| MTU | VPC/DX 间 8500，VPN 1500 | Interconnect VLAN 可 8896 jumbo |

**2.4 PrivateLink vs Private Service Connect (PSC)**
- 概念高度对应（私有暴露/消费服务）。**PSC 多出 "Interfaces" 生产者→消费者反向双向通信**（官方明确）；AWS 侧未见等价原语（不确定）。

**核心结论**：模型层最大差异 = AWS VPC 区域级 vs GCP VPC 全局级。NCC 的多云 spoke + PSC 的反向双向连接是 GCP 的差异亮点。
来源：docs.cloud.google.com/vpc/docs/vpc · /vpc-peering · /network-connectivity/.../overview · /vpc/docs/private-service-connect · docs.aws.amazon.com/vpc/latest/{userguide,peering,tgw,privatelink}

---

## 维度 3：混合云互联

**3.1 专线：Direct Connect vs Cloud Interconnect**
| | AWS DX | GCP Cloud Interconnect |
|---|---|---|
| 形态 | Dedicated / Hosted(Partner) | Dedicated / Partner |
| 光模块 | 1/10/100/400G 单模 | 10/100/400G 单模 + LACP+EBGP+802.1Q |
| 聚合上限(LAG) | **最多 2×100G 或 2×400G；或 4×<100G**（官方 lags.html） | Dedicated 到 8×400G=**3200G**；Partner 到 800G |
| 加密 | **支持 IEEE 802.1AE MACsec**（仅 dedicated+LAG，hosted 不支持；static CAK/AES-256；无额外费用） | **官方支持 MACsec**（Dedicated/Partner 均可） |
| SLA | **多站点冗余 99.99% / 多站点非冗余 99.9% / 单连接 ~95%**（官方 directconnect/sla） | 生产级(冗余)99.99%；单连接 No SLA |

**3.2 VPN：Site-to-Site VPN vs Cloud VPN**
| | AWS S2S VPN | GCP Cloud VPN |
|---|---|---|
| 结构 | 单产品，每连接**2 隧道**HA | **HA VPN**(99.99%) / **Classic VPN**(99.9%) 两代 |
| 路由 | BGP + 静态 | HA=仅BGP；Classic=仅静态 |
| 带宽 | 标准 1.25Gbps/隧道，**Large Bandwidth 5Gbps/隧道**(挂TGW) | 官方未列每隧道带宽数字（不确定） |
| IPv6 | 支持（outer 仅 TGW/Cloud WAN） | HA 支持双栈/IPv6-only；**Classic 不支持 IPv6** |
| 加密专线组合 | 未取到官方命名 | **HA VPN over Cloud Interconnect**（官方命名） |

**核心结论**：专线结构对应，GCP 明确 MACsec + 3200G 聚合 + Partner L2/L3；AWS 侧 MACsec/SLA/聚合上限未取到官方原文（标注不确定）。VPN 上 GCP 用 HA/Classic 两代 + 明确 SLA，AWS 用单产品双隧道 + 5Gbps 大带宽隧道。
来源：docs.cloud.google.com/network-connectivity/docs/{interconnect,vpn} · docs.aws.amazon.com/directconnect · /vpn

---

## 维度 4：负载均衡 & 外网入口

| 层 | AWS ELB | GCP Cloud LB |
|---|---|---|
| L7 | ALB (HTTP/HTTPS/gRPC) | Application LB (Global/Classic/Regional/Cross-region) |
| L4 代理 | NLB (TCP/UDP/TLS, 静态/弹性IP) | Proxy Network LB (可选 SSL offload) |
| L4 直通 | NLB 保留源IP | Passthrough Network LB (UDP/ESP/GRE/ICMP) |
| 网关型 | GWLB (L3网关+L4) | 官方未列等价（不确定） |

**关键差异（已查证）**：
- **GCP 全局 LB = 单 anycast IP 全球分发**（官方原文 "single anycast IP … closest backend"）。
- **AWS ELB 区域级**，全球入口需叠加 Global Accelerator / Route 53。
- 静态IP：AWS 仅 NLB 原生；GCP 全局 anycast IP 仅 Premium Tier。

来源：aws.amazon.com/elasticloadbalancing/features/ · docs.cloud.google.com/load-balancing/docs/choosing-load-balancer

---

## 维度 5：加速

| | AWS Global Accelerator | GCP |
|---|---|---|
| IP | 2 个静态 anycast IPv4（独立 network zone） | Premium Tier 全局 anycast IP |
| 路径 | 全程走 AWS 骨干 | Premium Tier 走 Google 骨干 |
| 协议 | TCP/UDP（边缘丢 TCP 分片） | 依 LB 类型 |
| 缓存 | 不缓存 | 不缓存（缓存靠 Cloud CDN） |

- AWS 官方："improves performance by as much as 60%"、"drops TCP fragments at the edge"。
- **GCP 无同名对标产品**——用 Premium Tier + 全局 anycast LB 达成功能等价（官方未打包命名为"加速器"，据实措辞）。
- **S3 Transfer Acceleration**（走 CloudFront 边缘回源）**GCP 无完全对标产品**（Storage Transfer Service 是迁移服务，机制不同）。

来源：docs.aws.amazon.com/global-accelerator/.../introduction-how-it-works.html · aws.amazon.com/global-accelerator/faqs/

---

## 维度 6：CDN

| | CloudFront | Cloud CDN | Media CDN |
|---|---|---|---|
| 定位 | Web 静态+动态通用 | web acceleration（必挂外部 ALB） | media delivery，高吞吐流媒体 |
| 源站 | S3/MediaPackage/HTTP | 依附 ALB 后端 | 任意公网 HTTP，可独立回源 |
| 缓存 | 边缘 location | GFE hit/miss/partial | router+cache+cache filler |

**关键差异**：AWS 单一 CloudFront 通吃（明确支持 static **and dynamic**）；GCP 拆成 Cloud CDN + Media CDN，Cloud CDN 必须挂 ALB 不能独立。

**边缘节点数（官方）**：
- CloudFront：**750+ CloudFront POPs + 15 Regional edge caches**（含大量嵌入式 PoP）。来源 aws.amazon.com/about-aws/global-infrastructure/
- GCP Cloud CDN：**100+ locations**（复用 Google 服务同款 CDN edge PoP）。来源 cloud.google.com/cdn/docs/locations
- ⚠️ 口径不完全可比（AWS 750+ 含嵌入式 PoP）。

**定价（官方）**：
- CloudFront：Invalidation 每月前 1000 免费后 $0.005/条；Origin fetch(AWS源→边缘)免费；Anycast Static IPs $3000/月。⚠️ **每 GB 分区 DTO 单价官方表 JS 渲染未抓到**（不臆造）。
- Cloud CDN：cache egress **$0.02–$0.20/GiB**（NA/EU 0–10TiB 档 $0.08，China $0.20）；cache fill $0.01–$0.04/GiB；lookup $0.0075/万次。来源 cloud.google.com/cdn/pricing
- ⚠️ **Media CDN 官方定价页 404 未定位到**（不臆造）。

- ⚠️ **"Media CDN 基于 YouTube 基础设施"官方无背书**——官方只说 "Google's global edge-caching infrastructure"，无 YouTube 字样。

来源：docs.aws.amazon.com/AmazonCloudFront/.../Introduction.html · docs.cloud.google.com/cdn/docs/overview · /media-cdn/docs/overview

---

## 维度 7：DNS

| | Route 53 | Cloud DNS |
|---|---|---|
| 路由策略 | **8 种**：Simple/Failover/Geolocation/Geoproximity/Latency/IP-based/Multivalue/Weighted | **3 类**：WRR/Geolocation(含geofence)/Failover |
| 健康检查 | 内建 | 支持自动 failover |
| 私有 DNS | 所有策略可用于 private zone | 部分 zone 类型不支持路由策略 |
| 域名注册 | ✔（三大功能之一） | 官方未提（不确定） |

**关键差异**：Route 53 路由策略更细（含 Latency/Geoproximity/IP-based/Multivalue）+ 自带域名注册；Cloud DNS 仅 3 类。

**DNSSEC（官方）**：
- Route 53：支持 DNSSEC signing；**KSK 用你自有的 KMS 非对称 key（需自管轮换）**，ZSK 由 Route 53 管；启用后 TTL 限最长 1 周；不支持多厂商配置。
- Cloud DNS：支持 DNSSEC，**DNSKEY 创建+轮换+RRSIG 签名全自动托管**（比 Route 53 更全托管）；验证侧点名 Google Public DNS。

**DNS 专属 SLA（官方）**：
- Route 53：SLA **100% uptime 承诺**（低于则给 credit：<100%≥99.99% 赔10%；<99.95% 赔100%）。「不可用」=某分钟内该 zone 全部 4 个虚拟 name server 都不响应。
- Cloud DNS：SLO **100% uptime**（只要 ≥1 台权威服务器响应即算可用）；credit 封顶 50%（<95% 赔50%）。
- 差异：Route 53 最严重档赔 100%，Cloud DNS 封顶 50%。

**GCP 无对标 S3 Transfer Acceleration 的产品**（据实）：GCS 上传只有 multipart/parallel composite/resumable 等客户端策略 + Google 骨干，无独立"边缘就近上传加速端点"；Storage Transfer Service 是迁移服务不算。

来源：docs.aws.amazon.com/Route53/.../routing-policy.html · docs.cloud.google.com/dns/docs/routing-policies-overview

---

## 维度 8：网络安全（防火墙层）★深水区

- **AWS** = Security Group（有状态，实例/ENI 级，**仅 allow 无 deny**，规则聚合评估）+ Network ACL（**无状态**，子网级，**allow+deny 按编号升序命中即停**）双层 + Firewall Manager 跨账号。
- **GCP** = 单一分布式防火墙（**天生有状态**）+ 全局/区域/**层级(hierarchical)策略** + tag/service account 微隔离。

### 三者深水区对比总表（官方核实）
| 维度 | AWS Security Group | AWS Network ACL | GCP VPC Firewall |
|---|---|---|---|
| 有状态性 | **有状态**(return自动放行) | **无状态**(return需显式放行) | **有状态**(5-tuple,10分钟活跃窗) |
| 作用层级 | 实例/ENI 级 | 子网级 | 网络级定义,按 target(tag/SA) 应用到 VM |
| 动作 | **仅 allow** | **allow + deny** | **allow + deny**(策略层另有 goto_next/L7检测) |
| 优先级 | 无编号,所有规则聚合(有allow即通) | 编号 **1–32766** 升序命中即停 | **priority 0–65535**(0最高);策略层 0–2,147,483,547;同级冲突 **deny 胜出** |
| 默认姿态 | 新建SG:入站全拒/出站全放 | 默认NACL全放;自定义NACL全拒 | **隐含 deny 全入站 + 隐含 allow 全出站**(priority 65535,不可删) |
| return流量 | 自动(连接跟踪) | **手动,需开 ephemeral port(示例 TCP 1024-65535)** | 自动(5-tuple) |
| 微隔离 | **引用另一个 SG**(sg-id作源,按成员私网IP) | 仅 CIDR | **network tag / service account** 作 target 与 source |
| 关键配额 | 每SG 60入/60出;每ENI 5(≤16)个SG;**规则×SG数 ≤1000** | 每NACL 20规则(可到40+40);每VPC 200 NACL | 连接跟踪封顶 1,040,000;per-network limits 见 quota 页 |

### GCP 评估顺序（深水区，官方 AFTER_CLASSIC 默认）
层级策略(组织→文件夹) → 区域系统策略 → VPC 经典规则 → 全局网络策略 → 区域网络策略 → 隐含规则。每层按 priority 高→低,命中即停;可切 BEFORE_CLASSIC。

**NGFW**：AWS Network Firewall（官方逐字：**stateful managed firewall + IDS/IPS**，用开源 **Suricata** 引擎、支持 deep packet inspection、按协议而非端口过滤 HTTPS、**TLS inspection 解密检测**）vs GCP Cloud NGFW（L3/L4/L7 + IDS/IPS + URL filtering，Essentials 免费 / Standard 收费）。

**核心结论**：
1. **状态性分野**：AWS 一层有状态(SG)+一层无状态(NACL);GCP 只有一种、天生有状态,NACL 式无状态子网 ACL 在 GCP 无直接对应。
2. **allow/deny+优先级**：SG 只有 allow 无优先级;NACL 用编号顺序;GCP 用 priority+allow/deny 且同级冲突 deny 胜出——GCP 把"显式拒绝+优先级"做进主防火墙,AWS 下放到无状态 NACL。
3. **微隔离哲学**：AWS 靠 SG 引用 SG(角色到角色);GCP 靠 tag/service account(更贴近身份),都与 IP 解耦。
4. **纵深防御**：AWS 天然两层(SG实例级+NACL子网级);GCP 单一有状态模型 + 层级/全局/区域策略多级评估管线做组织级治理(含 L7 检测 apply_security_profile_group)。

---

## 维度 9：WAF & 应用层防护

- **AWS WAF**：覆盖 9 类资源（CloudFront/ALB/API GW/AppSync/Cognito/App Runner/Verified Access 等）、原生 CAPTCHA/Challenge。
- **GCP Cloud Armor**：明确基于 **OWASP CRS 4.22** + Google 威胁情报 + Adaptive Protection。

**核心结论**：AWS WAF 挂载点更广、原生 CAPTCHA；Cloud Armor 规则基于 OWASP CRS + Google 威胁情报。

---

## 维度 10：DDoS 防护（重点）

**免费层**
- AWS **Shield Standard**（默认免费）vs GCP **Cloud Armor Standard**：都只做 L3/L4 自动缓解，都不做签名匹配。

**付费层（官方明确数字）**
| | AWS Shield Advanced | GCP Cloud Armor Enterprise |
|---|---|---|
| 核心 | 24/7 SRT 人肉响应 + **费用保护**(cost protection) + **500亿 WAF 请求/月**额度 + L7 DDoS 托管规则 | ML 驱动 Adaptive Protection |
| 训练期 | — | Advanced network 24h / Adaptive ≥1h |

⚠️ **诚实标注**：
- 两家均**无 DDoS 专属 SLA**、**无官方可缓解规模数字(Tbps/pps)**。
- GCP 是否有等同 SRT 的 24/7 响应团队/费用保护 → 官方页未明确（不确定）。

**核心结论**：AWS Shield Advanced 强在 24/7 SRT + 费用保护 + WAF 请求额度；GCP Cloud Armor Enterprise 强在 ML Adaptive Protection。

---

## 维度 11：稳定性 / SLA（官方核实）

| 产品 | AWS | GCP |
|---|---|---|
| 负载均衡 | ELB Multi-AZ **99.99%** | Cloud LB Premium **99.99%** |
| 专线 | Direct Connect 冗余 **99.99%** | Cloud Interconnect 生产级 **99.99%**（单连接 **No SLA**） |
| DNS | Route 53 **100%** | Cloud DNS **100%** |
| CDN | CloudFront **99.9%** | Cloud CDN 独立 SLA 未确认（cdn/sla 页 404，不确定） |
| 加速 | Global Accelerator Multi-AZ 99.99% / Single 99.5% | — |

**核心结论**：主要网络产品 SLA 两家基本对齐（LB/专线 99.99%，DNS 100%）。GCP 专线单连接无 SLA（需冗余才 99.99%）是要注意的点。

---

## ✅ 待核实点已全部补齐（2026-08-05）
之前标"待补"的项已查官方补齐：CloudFront 节点 750+/GCP 100+、Cloud CDN 定价 $0.02–0.20/GiB、两家 DNSSEC、两家 DNS SLA(均 100% SLO)、GCS 无 Transfer Acceleration 对标、DX MACsec/SLA/LAG、Network Firewall Suricata/TLS。
仅剩 2 项官方页本身无法取到（已诚实标注，非遗漏）：
- CloudFront 每 GB 分区 DTO 单价（官方定价表 JS 动态渲染，抓不到原文）
- GCP Media CDN 精确定价（官方公开定价页 404，疑走 SKU/合同报价）

---
*数据来源汇总见各维度末尾。所有硬性数字均有官方链接背书；标"不确定/待补"处为本次未取到官方原文，绝不臆造。*
