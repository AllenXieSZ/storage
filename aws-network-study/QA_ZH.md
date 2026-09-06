# AWS 网络面试题 30 道（2026-09-06 出题存档）

> 伟伟云网络强化训练题库。风格同 GCP/AWS 安全系列：每题含【标准答案要点】+【AWS↔GCP 对照】。
> 覆盖 10 大模块：VPC/子网/路由 · SG vs NACL · IGW/NAT/出网 · VPC Endpoint/PrivateLink · 跨 VPC 互联(Peering/TGW) · 混合云(DX/VPN) · DNS(Route 53) · 负载均衡(ELB) · CDN/边缘(CloudFront/Global Accelerator) · 可观测与限制(Flow Logs/带宽/MTU)。
> ⚠️ 技术细节以 AWS 官方文档为准；服务特性会更新，回答/批改前查最新 User Guide 核实。

---

## 一、VPC / 子网 / 路由基础

**Q1.** VPC 是什么？CIDR 如何规划？一个 VPC 可以有多大网段、能否事后扩容？子网为什么必须落在单个 AZ？
- 【要点】VPC = 逻辑隔离的虚拟网络，创建时定主 CIDR（/16~/28，RFC1918 私网段推荐）。可**额外关联最多 4 个（默认配额，可提额到 5）secondary CIDR** 扩容，但不能改主 CIDR。子网从 VPC CIDR 里切，**每个子网绑定一个 AZ**（子网不跨 AZ，这是高可用设计的基本单元）。每子网 AWS 保留 5 个 IP（.0 网络号 / .1 VPC 路由器 / .2 DNS / .3 预留 / .255 广播）。
- 【AWS↔GCP】AWS VPC = **区域内**但子网**绑 AZ**；GCP VPC 是**全局资源**，子网是**区域级**（跨该区域所有 zone），这是最大差异——GCP 子网不绑单个 zone。

**Q2.** 路由表（Route Table）如何工作？主路由表 vs 自定义路由表？子网如何决定用哪张表？最长前缀匹配是什么？
- 【要点】每个子网关联**恰好一张**路由表；未显式关联的用 VPC 主路由表（main）。路由条目 = 目的 CIDR → target（local/igw/nat/tgw/pcx/eni/endpoint 等）。`local` 路由（VPC CIDR→local）不可删。转发按**最长前缀匹配（most specific）**：10.0.1.0/24 优先于 0.0.0.0/0。
- 【AWS↔GCP】AWS 路由表**绑子网**；GCP 路由是 **VPC 级全局**的（按 instance tag/优先级），没有"子网各自一张表"的概念。

**Q3.** 公有子网和私有子网的本质区别是什么？只靠"名字"区分吗？
- 【要点】**唯一本质区别 = 路由表里有没有指向 IGW 的 0.0.0.0/0**。公有子网：默认路由 → IGW，且实例有公网 IP/EIP。私有子网：没有到 IGW 的路由，出网走 NAT。"public/private"只是习惯命名，实际由路由决定。
- 【AWS↔GCP】同理 GCP：有无外部 IP + 是否走 Cloud NAT / 默认路由到 default-internet-gateway 决定。GCP 实例默认可出网（若有外部 IP 或 Cloud NAT）。

---

## 二、Security Group vs NACL

**Q4.** Security Group 和 Network ACL 的区别？（有状态/无状态、allow/deny、作用层级、规则顺序、默认行为）
- 【要点】SG：**有状态**（放行入站，出站自动允许回程）、**只有 allow**、作用在 **ENI（实例）层**、所有规则一起评估（无顺序）、默认拒绝入站/允许所有出站。NACL：**无状态**（进出都要显式放行，回程要单独开高端口 1024-65535）、**有 allow + deny**、作用在**子网层**、**按规则号从小到大顺序匹配**、默认 NACL 允许全部/自定义 NACL 默认拒绝全部。
- 【AWS↔GCP】GCP 只有 **VPC Firewall Rules**（有状态、可 allow/deny、按 priority 排序、按 network tag/service account 作用），**没有 NACL 这层**。相当于把 SG+NACL 合并成一套有状态规则。

**Q5.** SG 能引用另一个 SG 作为源吗？为什么这很有用？跨 VPC 能引用吗？
- 【要点】能——源可以写另一个 SG ID（"允许来自 web-sg 的实例访问 db-sg 的 3306"），实现按角色而非 IP 授权，实例扩缩容 IP 变了规则不用改。同一 VPC 或**通过 Peering/TGW 已连通且开启 SG 引用**的场景可跨 VPC 引用（同区域 peering 支持 SG 引用；跨区域有限制）。
- 【AWS↔GCP】GCP 用 **source tags / source service accounts** 实现同样的"按身份授权"。

**Q6.** 一个数据包从公网进到私有实例，要依次穿过哪些网络控制点？
- 【要点】顺序大致：IGW → 目的子网的 **NACL（入站）** → **SG（入站）** → 实例。回程：实例 → SG（有状态自动放行）→ NACL（出站，需显式规则）→ IGW。私有实例无公网入口，只能经 ALB/NAT/跳板。记住 **NACL 在子网边界、SG 在网卡边界**。

---

## 三、IGW / NAT / 出网

**Q7.** Internet Gateway 是什么？它做 NAT 吗？没有公网 IP 的实例能通过 IGW 上网吗？
- 【要点】IGW = VPC 到互联网的水平扩展、高可用、无带宽瓶颈的托管网关。它对**有公网 IP/EIP 的实例做 1:1 NAT**（把私有 IP ↔ 公有 IP 映射）。**没有公网 IP 的实例即使路由指向 IGW 也上不了网**——因为 IGW 不给它做地址转换。这类实例出网必须走 NAT Gateway。
- 【AWS↔GCP】GCP 的等价物是隐式的 **default-internet-gateway 路由**；无外部 IP 出网靠 **Cloud NAT**。

**Q8.** NAT Gateway 是什么？和 NAT 实例的区别？它能接收主动入站连接吗？跨 AZ 高可用怎么做？
- 【要点】NAT GW = 托管的出网 NAT，让私有子网实例**主动出站**（下载更新等），**不接受外部主动入站**。它是**单 AZ 资源**，高可用要**每个 AZ 放一个 NAT GW**，各 AZ 私有子网路由指向本 AZ 的 NAT GW（避免跨 AZ 流量费 + 单 AZ 故障牵连）。NAT 实例是自建 EC2 版（要自己管带宽/HA/源目的检查关闭），基本已被 NAT GW 取代。计费：按小时 + 处理的 GB。
- 【AWS↔GCP】GCP **Cloud NAT** 是**区域级、分布式软件定义**的（不是单 zone 网关设备），天然跨 zone 高可用，这点比 AWS NAT GW 省心。

**Q9.** 私有子网实例访问 S3，有哪几种路径？各自成本/安全差异？
- 【要点】①走 NAT GW 出公网访问 S3 公共端点（有 NAT 处理费 + 数据费，走公网）；②用 **S3 Gateway Endpoint**（免费、走 AWS 内部、路由表加条目、不出 VPC）——推荐；③Interface Endpoint(PrivateLink) 也行但收费，Gateway 型对 S3/DynamoDB 免费更划算。
- 【AWS↔GCP】GCP 用 **Private Google Access**（子网开关）或 **Private Service Connect** 让私网访问 Google API 不出公网。

---

## 四、VPC Endpoint / PrivateLink

**Q10.** Gateway Endpoint 和 Interface Endpoint（PrivateLink）的区别？分别支持哪些服务？
- 【要点】**Gateway Endpoint**：只支持 **S3 和 DynamoDB**，通过**路由表条目**实现，**免费**，不占 ENI/私有 IP。**Interface Endpoint（PrivateLink）**：支持 **100+ 服务**（含大部分 AWS API、自定义服务），在子网里创建 **ENI + 私有 IP**，走 DNS 解析到私有 IP，**按小时 + 数据量收费**。
- 【AWS↔GCP】GCP **Private Service Connect (PSC)** ≈ Interface Endpoint（私有 IP 端点访问服务）；Private Google Access ≈ Gateway 思路访问 Google API。

**Q11.** PrivateLink 如何让消费者不经公网访问提供者的服务？谁发起连接？
- 【要点】提供者把服务放在 **NLB** 后面并创建 **Endpoint Service**；消费者在自己 VPC 建 **Interface Endpoint** 指向该服务名。流量**单向从消费者发起**，经 AWS 骨干直达提供者 NLB，**不经互联网、双方 CIDR 可重叠**（PrivateLink 不打通网络，只暴露单个服务端点，比 Peering 更安全隔离）。
- 【AWS↔GCP】GCP PSC producer/consumer 模型基本一一对应。

---

## 五、跨 VPC 互联：Peering / Transit Gateway

**Q12.** VPC Peering 是什么？有哪些关键限制（传递性、CIDR 重叠、跨区域/账号）？
- 【要点】Peering = 两个 VPC 间点对点私有互联，走 AWS 骨干。**不支持传递路由**（A-B、B-C 通，A 不能经 B 到 C）。**CIDR 不能重叠**。支持跨区域、跨账号。每对都要单独建连接 + 双方路由表加对端路由 + SG 放行。VPC 多了会成 N² 网状，难管理。
- 【AWS↔GCP】GCP **VPC Network Peering** 也不传递、CIDR 不能重叠，概念一致。

**Q13.** Transit Gateway 解决什么问题？和 Peering 网状比优势在哪？它支持传递路由吗？
- 【要点】TGW = 区域级的**云路由器中枢（hub-and-spoke）**，把多个 VPC/VPN/DX 挂上来集中路由，**支持传递**（通过 TGW route table 控制哪些 attachment 互通），把 N² 网状简化成星型。支持跨区域 TGW peering、多账号共享（RAM）。有 attachment 费 + 数据处理费。
- 【AWS↔GCP】GCP 无完全等价单品；近似用 **Network Connectivity Center (NCC)** 做 hub-spoke，或用共享 VPC / Peering 组合。

**Q14.** 三个 VPC（CIDR 都不重叠）要全互通，用 Peering 需要几条连接？用 TGW 呢？
- 【要点】Peering：全网状需 **n(n-1)/2 = 3 条**（AB/AC/BC），且每 VPC 路由表要加到另两个的路由。TGW：**3 个 attachment 挂到 1 个 TGW**，路由集中在 TGW route table，扩到第 4 个 VPC 只加 1 个 attachment（Peering 要再加 3 条）。VPC 越多 TGW 越划算。

---

## 六、混合云：Direct Connect / VPN

**Q15.** Site-to-Site VPN 和 Direct Connect 的区别？各自带宽/延迟/成本/上线速度？
- 【要点】**VPN**：over 公网的 IPSec 隧道，**分钟级上线、便宜**，但带宽/延迟受公网波动（单隧道上限 ~1.25Gbps），适合快速/备份链路。**Direct Connect (DX)**：物理专线接入 AWS，**稳定低延迟、专用带宽（1/10/100Gbps）**，但**上线要数周、贵**，适合大流量/稳定性要求高。二者常组合：DX 为主 + VPN 做加密/备份（DX 本身不加密，可跑 VPN over DX）。
- 【AWS↔GCP】GCP 对应 **Cloud VPN** 和 **Cloud Interconnect（Dedicated/Partner）**，模型一致。

**Q16.** DX 上如何隔离多个 VPC/网络？公有 VIF vs 私有 VIF vs Transit VIF？
- 【要点】DX 上建虚拟接口（VIF）：**Private VIF** → 连单个 VPC（经 VGW）；**Public VIF** → 访问 AWS 公共服务（S3 等公网端点）走专线；**Transit VIF** → 连 **TGW**，一条 DX 打通多个 VPC（推荐大规模混合云）。
- 【AWS↔GCP】GCP Interconnect 用 **VLAN attachment** 关联到 Cloud Router (BGP)，概念类似。

**Q17.** VGW（Virtual Private Gateway）和 TGW 在混合云连接里怎么选？BGP/路由传播是什么？
- 【要点】VGW = 挂在单个 VPC 上的 VPN/DX 终结点（一对一）。TGW = 中枢，一处终结 VPN/DX 后分发给多个 VPC。**路由传播（route propagation）**：VGW/TGW 学到的 BGP 动态路由可自动传播进关联的路由表，免手工维护。多 VPC 混合云选 TGW。

---

## 七、DNS：Route 53

**Q18.** Route 53 有哪些常见记录类型和路由策略？Alias 记录相比 CNAME 的优势？
- 【要点】记录类型 A/AAAA/CNAME/MX/TXT/NS/SOA 等。**路由策略**：Simple、**Weighted**（权重分流/灰度）、**Latency**（就近低延迟）、**Failover**（主备+健康检查）、**Geolocation/Geoproximity**（按地理）、**Multivalue**（多值+健康检查）。**Alias**：AWS 专有，可指向 ELB/CloudFront/S3 网站/API GW 等 AWS 资源，**能用在 zone apex（裸域 example.com，CNAME 不行）**、免查询费、目标 IP 变化自动跟随。
- 【AWS↔GCP】GCP **Cloud DNS**；路由策略较少（有 geo/weighted routing policy），Alias 概念用 Cloud DNS + 其他方式。

**Q19.** VPC 内的私有 DNS 怎么工作？Route 53 Resolver（inbound/outbound endpoint）解决什么？
- 【要点】VPC 有内置 DNS（.2 地址 = AmazonProvidedDNS），需开 `enableDnsSupport` + `enableDnsHostnames`。**Private Hosted Zone** 给 VPC 内部私有域名解析。**Route 53 Resolver endpoints**：**Inbound**（让本地/on-prem 查询 VPC 内的私有域名）、**Outbound + 转发规则**（让 VPC 内查询转发到 on-prem DNS），是混合云 DNS 双向解析的关键。
- 【AWS↔GCP】GCP Cloud DNS 私有区域 + **DNS 转发/inbound-outbound server policy** 对应。

---

## 八、负载均衡：ELB

**Q20.** ALB / NLB / GWLB / CLB 的区别？各自工作在哪一层、典型场景？
- 【要点】**ALB（L7 HTTP/HTTPS）**：基于路径/主机/header 路由、支持 WebSocket/gRPC/重定向、目标组、WAF 集成——Web 应用首选。**NLB（L4 TCP/UDP/TLS）**：超高性能低延迟、保留源 IP、支持静态/弹性 IP、每 AZ 一个 IP——极高吞吐/低延迟/非 HTTP 场景。**GWLB（L3/网关）**：串联第三方虚拟安全设备（防火墙/IDS），用 GENEVE 封装。**CLB**：老一代，已不推荐。
- 【AWS↔GCP】GCP：**Global External HTTP(S) LB**（≈ALB 但全局任播）、**Network LB / Proxy LB**（L4/TCP-UDP）、**Internal LB**。GCP 外部 HTTP LB 是全局单 anycast IP，AWS ALB 是区域级。

**Q21.** ALB 的跨区域/跨 AZ 高可用怎么保证？什么是 cross-zone load balancing？
- 【要点】ALB 在多个 AZ 各放节点（子网），DNS 轮询各 AZ 节点。**Cross-zone LB**：开启后每个 LB 节点可把流量分发到**所有 AZ 的目标**（不只本 AZ），使后端负载更均衡。ALB 默认开启且不收跨 AZ 费；**NLB 默认关闭**（开启会产生跨 AZ 数据费）。健康检查剔除不健康目标。
- 【AWS↔GCP】GCP 后端服务的 balancing mode + 健康检查，全局 LB 天然跨区域。

**Q22.** 什么是目标组（Target Group）？IP/Instance/Lambda 目标类型的差异？连接如何保持（sticky session）？
- 【要点】目标组 = ALB/NLB 把流量转发的一组后端 + 健康检查配置。类型：**instance**（按 EC2 ID）、**ip**（按 IP，可指 on-prem/容器/Peering 对端）、**lambda**（ALB 触发 Lambda）。**粘性会话**：ALB 用 cookie（AWSALB/自定义 app cookie）把同一客户端固定到同一目标。一个目标组可被多个 LB/规则复用。

---

## 九、CDN / 边缘：CloudFront / Global Accelerator

**Q23.** CloudFront 是什么？缓存策略、Origin、OAC 是什么？动态内容能加速吗？
- 【要点】CloudFront = 全球边缘 CDN。**Origin**：S3 / ALB / 自定义 HTTP。**Cache Policy / Origin Request Policy** 控制缓存键（哪些 header/cookie/querystring 参与）与回源。**OAC（Origin Access Control，取代旧 OAI）** 让只有 CloudFront 能访问私有 S3。静态内容缓存命中零回源；**动态/POST 不缓存**但仍受益于边缘 TLS 终结 + 到 origin 走优化骨干（比公网直连快）。
- 【AWS↔GCP】GCP **Cloud CDN**（挂在外部 HTTP LB 上）+ Media CDN。

**Q24.** CloudFront 和 Global Accelerator 有什么本质区别？分别适合什么？
- 【要点】**CloudFront**：**缓存 HTTP 内容**在边缘，适合网站/静态/流媒体，按内容分发。**Global Accelerator**：**不缓存**，提供 **2 个静态 anycast IP**，把 TCP/UDP 流量从最近边缘经 AWS 骨干送到后端区域，**加速任意 TCP/UDP（游戏/API/非 HTTP）+ 快速区域故障切换**。一句话：CloudFront 缓存内容，GA 加速网络路径。
- 【AWS↔GCP】GCP 外部 HTTP LB 的全局 anycast IP + Premium Tier 骨干 ≈ 融合了 CDN + GA 的部分能力。

---

## 十、可观测 / 限制 / 底层

**Q25.** VPC Flow Logs 记录什么？不记录什么？发到哪？如何排查一次可疑访问？
- 【要点】记录 ENI/子网/VPC 级的**流元数据**（源/目的 IP、端口、协议、包/字节数、ACCEPT/REJECT、时间窗），**不记录 payload 内容**。可发到 CloudWatch Logs / S3 / Firehose。排查：按 5-tuple 过滤、看 REJECT 判断被 SG/NACL 拦、结合 CloudTrail（谁改了规则）+ GuardDuty（威胁检测，Flow Logs 是其数据源之一）。
- 【AWS↔GCP】GCP **VPC Flow Logs**（子网级开关）+ Firewall Rules Logging，类似。

**Q26.** EC2 实例的网络带宽由什么决定？单流 5Gbps 限制是什么？如何突破？
- 【要点】带宽由**实例规格**决定（越大越高，标 "up to" 的是突发型）。**单个网络流（five-tuple）在非 cluster placement group 内封顶 5 Gbps**；**同一 CPG 内单流可到 10Gbps**；多流可跑满实例总带宽。突破单流限制：用 **CPG + 多流**，或 **ENA Express（基于 SRD，单流可到 25Gbps 并降尾延迟）**。跨 region/公网还有额外限制。
- 【依据】AWS EC2 网络性能文档；ENA Express 特性需查最新支持机型。

**Q27.** ENI、EFA、ENA、ENA Express 分别是什么？HPC/AI 场景为什么要 EFA？
- 【要点】**ENI** = 虚拟网卡（可挂多个、可迁移、带 SG/私有IP/EIP）。**ENA** = 增强网络驱动（高带宽低 CPU 开销，现代实例标配）。**EFA（Elastic Fabric Adapter）** = 在 ENA 基础上加 **OS-bypass + SRD 协议**，给 MPI/NCCL 做超低延迟 RDMA-like 通信，HPC/分布式训练（多 GPU allreduce）必备。**ENA Express** = 用 SRD 提升普通 TCP/UDP 单流带宽与尾延迟。
- 【AWS↔GCP】GCP 对应 gVNIC + (Titanium/自研) ；HPC 用 GPUDirect/RDMA over Falcon 等。

**Q28.** MTU 和巨帧（Jumbo Frames 9001）在 VPC 里怎么用？什么时候 MTU 会被限制到 1500？
- 【要点】VPC 内实例间支持 **9001 字节巨帧**（提高大吞吐效率）。但**经 IGW 出公网、跨 VPC Peering（历史上限 1500，现部分支持更高需确认）、经某些 VPN/DX、经 TGW** 时 MTU 会被钳到 **1500**（或更低），否则丢包/分片。要注意路径 MTU 发现（PMTUD）与 ICMP 放行。跨这些边界的高吞吐要测有效 MTU。
- 【依据】AWS VPC MTU 文档；跨边界 MTU 支持随特性更新，需查最新。

**Q29.** IPv6 在 VPC 里怎么支持？egress-only internet gateway 是什么？
- 【要点】VPC/子网可分配 IPv6 CIDR，实例拿 IPv6（**IPv6 全球可路由，无 NAT 概念**）。要让 IPv6 私有实例**只出不进**，用 **Egress-Only Internet Gateway（EIGW）**（IPv6 版的"NAT 语义"——有状态允许出站、拒绝入站；因为 IPv6 不做 NAT，所以专门有这个网关）。IGW 处理 IPv6 双向。
- 【AWS↔GCP】GCP 也支持双栈子网 IPv6；出入控制靠 firewall + 路由。

**Q30.** 综合题：设计一个"三层 Web 应用 + 混合云"的生产 VPC 网络，覆盖高可用、最小暴露、私网访问 AWS 服务、连 on-prem，把前 29 题的手段串成体系。
- 【要点参考架构】
  1. **多 AZ VPC**（≥2 AZ），每 AZ 一套：public 子网（ALB + NAT GW）、private-app 子网（EC2/ECS）、private-data 子网（RDS）。
  2. **入口**：CloudFront(+WAF) → ALB(public 子网, 多 AZ, cross-zone) → app 目标组。DNS 用 Route 53（alias 到 CloudFront/ALB，failover/latency 策略）。
  3. **出网**：private-app 走**每 AZ 的 NAT GW** 出公网；访问 S3/DynamoDB 走 **Gateway Endpoint**（免费不出 VPC）；访问其他 AWS API 走 **Interface Endpoint(PrivateLink)**。
  4. **隔离**：SG 按角色链式引用（alb-sg→app-sg→db-sg），NACL 在子网边界兜底；data 子网无到 IGW 路由。
  5. **混合云**：**TGW** 做中枢，Transit VIF 走 **Direct Connect**（主）+ **Site-to-Site VPN**（备/加密）连 on-prem；**Route 53 Resolver** inbound/outbound endpoint 做双向 DNS。
  6. **可观测**：VPC Flow Logs → S3/CloudWatch，配合 GuardDuty/CloudTrail。
  7. **多 VPC 扩展**：用 TGW 星型互联（不用 Peering 网状）。
- 【AWS↔GCP】GCP 对照：Shared VPC + 区域子网(跨zone天然HA) + 全局 HTTP LB + Cloud NAT + PSC/Private Google Access + Cloud Interconnect/VPN + NCC + Cloud DNS。

---

## 附：10 模块 ↔ AWS↔GCP 速查

| 模块 | AWS | GCP 对应 |
|---|---|---|
| 虚拟网络 | VPC（区域，子网绑AZ） | VPC（全局，子网绑区域） |
| 防火墙 | SG(有状态,实例) + NACL(无状态,子网) | Firewall Rules（有状态,tag/SA，无NACL层） |
| 出网 NAT | NAT Gateway（单AZ，每AZ一个） | Cloud NAT（区域级分布式） |
| 私网访问服务 | Gateway Endpoint(S3/DDB免费) / Interface Endpoint(PrivateLink) | Private Google Access / PSC |
| 跨VPC | Peering(不传递) / Transit Gateway(中枢) | VPC Peering / Network Connectivity Center |
| 混合云 | Direct Connect / Site-to-Site VPN + VGW/TGW | Cloud Interconnect / Cloud VPN + Cloud Router |
| DNS | Route 53 + Resolver endpoints | Cloud DNS + server policy |
| 负载均衡 | ALB(L7)/NLB(L4)/GWLB | Global HTTP LB / Network LB / Proxy LB |
| CDN/边缘 | CloudFront(缓存) / Global Accelerator(加速) | Cloud CDN / (全局LB anycast) |
| 观测/底层 | Flow Logs / ENA·EFA·ENA Express / 单流5Gbps / 巨帧9001 | Flow Logs / gVNIC / MTU 8896 |

---
> 出题日期 2026-09-06。批改时按 SOUL.md 铁律：每题完整展开五板块（逐点对照/参考答案+原理/概念详解/AWS↔GCP对照/评分+记忆点），答完即停不预告。
