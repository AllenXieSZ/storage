# GCP 网络 —— 20 题题库（每 2 题一组过）

> 方向：GCP 网络。共 20 题，分 10 个模块，每 2 题一组。
> 作答后批改采用五板块：①逐点对照 ②完整参考答案+原理详解 ③关键概念深入 ④GCP↔AWS 对照 ⑤评分+记忆点。
> 进度：待小帅从 Q1、Q2 开始作答。

---

## 第一模块：VPC 基础与全球架构（Q1 / Q2）

**Q1（VPC 模型与全球性）**
1. GCP 的 VPC 是什么？它和 AWS VPC 最本质的区别是什么？（提示：region 边界、全球 vs 区域）
2. GCP VPC 里的 Subnet（子网）是 region 级还是 zone 级的？一个 subnet 能跨 zone 吗？
3. Auto mode VPC 和 Custom mode VPC 有什么区别？生产环境推荐哪种、为什么？
4. 什么是 Shared VPC？它解决什么组织级的网络管理问题？

**Q2（IP、路由与防火墙基础）**
1. GCP VPC 里的路由（Routes）是怎么工作的？系统默认路由有哪些？
2. GCP 的防火墙规则（Firewall Rules）有什么特点？（提示：作用在实例级、有优先级、隐式规则、方向）
3. 防火墙规则用什么来匹配目标实例？（提示：network tag、service account）
4. 什么是分层防火墙策略（Hierarchical Firewall Policies）？和 VPC 防火墙规则什么关系？

---

## 第二模块：负载均衡（Q3 / Q4）

**Q3（负载均衡器分类）**
1. GCP 负载均衡器怎么分类？（提示：全球 vs 区域、外部 vs 内部、应用层 L7 vs 网络层 L4）
2. 全球外部应用负载均衡器（Global External Application LB）为什么能做到"全球单一 Anycast IP"？它和 AWS ALB 最大的架构区别是什么？
3. 什么场景用 L7（应用）负载均衡器，什么场景用 L4（网络）负载均衡器？
4. 内部负载均衡器（Internal LB）解决什么问题？

**Q4（后端与健康检查）**
1. 负载均衡的后端可以是哪些类型？（提示：实例组 MIG、NEG）
2. 什么是 NEG（Network Endpoint Group）？Serverless NEG / Zonal NEG / Internet NEG 各用在什么场景？
3. 健康检查（Health Check）在负载均衡里的作用？GCP 健康检查探测流量来自哪里（有个特殊的 IP 段）？
4. 什么是后端服务的容量与均衡模式（balancing mode：RATE / UTILIZATION / CONNECTION）？

---

## 第三模块：混合连接与互联（Q5 / Q6）

**Q5（云上互联 VPC 之间）**
1. VPC Peering 是什么？它有什么关键限制？（提示：不传递、CIDR 不能重叠）
2. Shared VPC 和 VPC Peering 有什么区别，分别适合什么组织结构？
3. 什么是 Network Connectivity Center（NCC）？它解决多 VPC / 混合网络的什么痛点？
4. 为什么 VPC Peering 不能"传递"（A-B、B-C peering 后 A 不能通 C）？

**Q6（连接本地数据中心 / 混合云）**
1. GCP 连本地数据中心有哪几种方式？（提示：Cloud VPN、Dedicated Interconnect、Partner Interconnect、Cross-Cloud Interconnect）
2. Cloud VPN 的 HA VPN 和 Classic VPN 有什么区别？HA VPN 的 SLA 靠什么保证？
3. Dedicated Interconnect 和 Partner Interconnect 怎么选？各自适合多大带宽/什么接入条件？
4. 什么是 Cloud Router？它在混合连接里扮演什么角色（提示：BGP 动态路由）？

---

## 第四模块：网络出口与 NAT（Q7 / Q8）

**Q7（外网访问与 NAT）**
1. GCP 里一个没有外部 IP 的 VM 怎么访问公网？（提示：Cloud NAT）
2. Cloud NAT 是什么架构？它和 AWS NAT Gateway 最大的区别是什么？（提示：是否有 NAT 实例/网关设备）
3. Cloud NAT 的端口分配、耗尽问题怎么处理？
4. 什么情况下 VM 需要外部 IP，什么情况下不需要？

**Q8（Private Google Access & 服务连接）**
1. 什么是 Private Google Access？没有外部 IP 的 VM 怎么访问 Google API（如 GCS）？
2. Private Service Connect（PSC）是什么？它解决什么问题？（提示：私有访问 Google/第三方/自有服务）
3. VPC Service Controls 是什么？它防的是什么风险（提示：数据外泄边界）？
4. Private Google Access、PSC、VPC Service Controls 三者的关系与区别？

---

## 第五模块：DNS 与内容分发（Q9 / Q10）

**Q9（Cloud DNS）**
1. Cloud DNS 是什么？公有区域（Public Zone）和私有区域（Private Zone）分别用在什么场景？
2. GCP VPC 内部的实例默认用什么做内部 DNS 解析？内部 DNS 名字格式是怎样的？
3. 什么是 DNS Peering / DNS Forwarding？混合云环境下怎么解析本地内网域名？
4. Cloud DNS 怎么保证高可用和低延迟（提示：Anycast）？

**Q10（Cloud CDN & Media CDN）**
1. Cloud CDN 是什么？它和负载均衡器什么关系（提示：挂在哪个 LB 上）？
2. Cloud CDN 缓存命中/未命中怎么工作？缓存键（cache key）能自定义吗？
3. Cloud CDN 和 Media CDN 有什么区别，各自适合什么场景？
4. GCP 的 Cloud CDN 对标 AWS 什么服务？架构上有何不同？

---

## 第六模块：网络分层安全（Q11 / Q12）

**Q11（Cloud Armor & DDoS）**
1. Cloud Armor 是什么？它挂在哪一层、防什么？（提示：WAF + DDoS，配合全球 LB）
2. Cloud Armor 的安全策略（security policy）能基于什么做规则？（提示：IP、地理、L7 规则、预配置 WAF 规则如 OWASP）
3. 什么是 Adaptive Protection（自适应防护）？
4. GCP 的 DDoS 防护分哪几层（网络层 vs 应用层）？

**Q12（防火墙进阶与网络隔离）**
1. 什么是防火墙规则的隐式规则（implied rules）？默认放行/拒绝什么？
2. Firewall Rules 和新的 Network Firewall Policies（Global/Regional）有什么区别与演进？
3. 什么是标签（network tag）驱动的微分段？和用 service account 做匹配相比优劣？
4. 什么是 Packet Mirroring？用来做什么（提示：IDS/流量分析）？

---

## 第七模块：可观测与流量分析（Q13 / Q14）

**Q13（网络监控与日志）**
1. VPC Flow Logs 是什么？记录什么、用来干什么？采样率怎么影响成本？
2. Firewall Rules Logging 记录什么？和 Flow Logs 区别？
3. Network Intelligence Center 是什么？它有哪几个模块（Connectivity Tests / Performance Dashboard / Network Topology 等）？
4. Connectivity Tests 怎么帮你排查"两个实例通不通"？

**Q14（性能与优化）**
1. GCP 的网络层级（Network Service Tiers）Premium Tier 和 Standard Tier 有什么区别？各自走什么骨干？
2. 为什么 Premium Tier 能做到全球 Anycast + Google 骨干？对延迟/成本的影响？
3. 什么是 MTU / jumbo frames，GCP VPC 里 MTU 怎么配、有什么坑？
4. Andromeda 是什么（GCP 网络虚拟化的底层）？（提示：SDN 数据面，了解概念即可）

---

## 第八模块：Kubernetes / 容器网络（Q15 / Q16）

**Q15（GKE 网络模型）**
1. GKE 的 VPC-native（别名 IP，Alias IP）模式是什么？和 routes-based 模式有什么区别？
2. Pod、Service、Node 各自的 IP 从哪来？（提示：secondary ranges）
3. 什么是 Pod 的别名 IP 范围（alias IP range）？为什么 VPC-native 是推荐模式？
4. GKE 里 Service 的 ClusterIP / NodePort / LoadBalancer / Ingress 分别怎么暴露服务？

**Q16（GKE 高级网络）**
1. GKE 的 Ingress 底层用什么实现？（提示：GCP LB + NEG）
2. 什么是 Container-native load balancing（容器原生负载均衡）？为什么比传统 NodePort 转发更优？
3. 私有 GKE 集群（Private Cluster）的网络架构是怎样的？控制平面怎么访问？
4. 什么是 Network Policy？GKE 里怎么做 Pod 间微分段？

---

## 第九模块：多区域 / 高可用架构（Q17 / Q18）

**Q17（跨区域网络架构）**
1. 一个 GCP VPC 天生就是全球的——这对多区域架构带来什么好处（对比 AWS 每 region 一个 VPC + peering）？
2. 全球负载均衡怎么把用户就近路由到最近的健康后端？（提示：Anycast IP + 就近接入 + 后端选择）
3. 跨区域内部负载均衡（Cross-region Internal LB）解决什么问题？
4. 设计一个"用户全球访问、后端多区域容灾"的 Web 架构，你会用哪些网络组件串起来？

**Q18（容灾与故障隔离）**
1. Zone、Region 级故障对 GCP 网络组件（VPC/Subnet/LB/Cloud NAT）各有什么影响？哪些是区域级、哪些是全球级？
2. HA VPN 怎么做到 99.99% 可用性？（提示：两个接口 + BGP）
3. 如果某个 region 整体挂了，全球外部 LB 会怎么处理流量？
4. 什么网络设计能避免单点故障（子网/NAT/LB/Interconnect 各层）？

---

## 第十模块：安全边界 & 综合选型（Q19 / Q20）

**Q19（零信任与安全网络综合）**
1. 什么是 BeyondCorp / Identity-Aware Proxy（IAP）？它怎么实现"无 VPN 的零信任访问"？
2. IAP 和传统"堡垒机 + VPN"访问内部资源相比有什么优势？
3. 把 Cloud Armor、IAP、VPC Service Controls、防火墙策略组合，怎么搭一套纵深防御的网络安全架构？
4. VPC Service Controls 的"服务边界（perimeter）"具体防的是什么攻击链（提示：凭证被盗后的数据外泄）？

**Q20（综合选型场景题）**
给 3 个场景，说你会怎么用 GCP 网络组件搭方案：
1. **场景A**：一个全球用户访问的电商网站，要低延迟、防 DDoS/WAF、后端多区域容灾。→ 怎么搭？
2. **场景B**：企业本地数据中心要和 GCP 打通，要求高带宽（10Gbps+）、专线级 SLA、动态路由。→ 怎么搭？
3. **场景C**：一堆没有公网 IP 的内部 VM，既要能访问 GCS/Google API、又要能受控访问公网更新补丁、还要防止数据被外泄到组织外。→ 怎么搭？

---

## 批改进度追踪

| 模块 | 题号 | 状态 | 得分 |
|---|---|---|---|
| 1 VPC 基础 | Q1/Q2 | 待作答 | — |
| 2 负载均衡 | Q3/Q4 | 待作答 | — |
| 3 互联 | Q5/Q6 | ✅已批改 | 5.5 / 5 |
| 4 出口/NAT | Q7/Q8 | ✅已批改 | 5 / 3.5 |
| 5 DNS/CDN | Q9/Q10 | ✅已批改 | 4.5 / 5 |
| 6 分层安全 | Q11/Q12 | ✅已批改 | 4.5 / 5 |
| 7 可观测 | Q13/Q14 | 待作答 | — |
| 8 GKE 网络 | Q15/Q16 | 待作答 | — |
| 9 多区域 | Q17/Q18 | 待作答 | — |
| 10 安全边界/选型 | Q19/Q20 | 待作答 | — |

> **下次从 Q13、Q14（可观测与流量分析）开始。**
> Q1-Q4 跳过未答；已批改 Q5-Q12（8 题），平均约 4.75/10。
