# GCP 网络 vs AWS —— 差异比较总结

> GCP 网络 20 题批改后的核心差异总结。重点：**作用域差异**是两家网络最大的不同。

## 一、⭐ 作用域差异（最核心）

| 组件 | GCP | AWS |
|---|---|---|
| **VPC** | 🌍 **全球**（一个 VPC 跨所有 region，跨区天然互通，无需 peering） | 📍 **区域级**（每 region 一个 VPC，跨区靠 Peering/TGW） |
| **子网 Subnet** | 📍 **区域级**（跨该 region 所有 zone） | 🔹 **AZ 级**（一个子网绑一个 AZ） |
| **L7 负载均衡** | 🌍 全球 App LB（**单一 Anycast IP**，自动跨 region failover） | ALB **区域级**；全球要叠 CloudFront / Global Accelerator |
| **Cloud NAT / Internal LB** | 📍 区域级（跨 zone 冗余） | NAT GW 绑 AZ（每 AZ 一个才冗余） |
| **VM / 普通磁盘** | 🔹 zone 级 | 🔹 AZ 级 |

**一句话**：GCP 把"全球"做进基础设施（VPC 全球、子网跨 zone、LB 单 Anycast IP）；AWS 更区域自治，跨区域要显式拼 peering/TGW/CloudFront/GA。

## 二、服务对照

| 能力 | GCP | AWS |
|---|---|---|
| 两 VPC 直连 | VPC Peering（不传递） | VPC Peering（不传递） |
| 多网络中心互联 | Network Connectivity Center | Transit Gateway |
| 一网络多项目共用 | Shared VPC | RAM 共享子网（无完全对等） |
| 出站 NAT | Cloud NAT（无设备，SDN，区域级） | NAT Gateway（真实设备，绑 AZ） |
| 私网访问云 API | Private Google Access（子网开关） | VPC Endpoint |
| 私有 IP 访问服务/SaaS | Private Service Connect | PrivateLink |
| **数据外泄边界** | **VPC Service Controls** | **无直接对等** |
| WAF + DDoS | Cloud Armor（挂全球 LB） | AWS WAF + Shield |
| L7 DDoS ML 防护 | Adaptive Protection | Shield Advanced |
| 托管 DNS | Cloud DNS | Route 53 |
| CDN | Cloud CDN（挂 LB 的开关）/ Media CDN | CloudFront（独立产品） |
| 专线 | Dedicated / Partner Interconnect | Direct Connect |
| 托管 BGP 路由 | Cloud Router | VGW / TGW BGP |
| 连通性诊断 | Connectivity Tests / Network Intelligence Center | Reachability Analyzer |
| 流量镜像 | Packet Mirroring | Traffic Mirroring |
| **零信任访问** | **IAP / BeyondCorp** | **Verified Access（无 VPN 靠 SSM）** |
| 网络虚拟化底层 | Andromeda（SDN） | Nitro |
| 全球数据库 | Cloud Spanner | Aurora Global / DynamoDB Global |

## 三、AWS 没有直接对等的 GCP 特性（面试区分点）

- **全球 VPC**（AWS VPC 是区域级）
- **VPC Service Controls**（数据外泄边界，AWS 靠 IAM 条件+SCP 拼凑）
- **Cloud CDN 是 LB 的开关**（CloudFront 是独立产品）
- **Cloud NAT 无网关设备**（NAT GW 是真实实例）

## 四、GKE vs EKS Pod 网络

| | GKE | EKS |
|---|---|---|
| Pod IP 来源 | 子网 **secondary CIDR range**（Alias IP） | ENI 上的 **secondary IP 地址** |
| Pod 数上限 | 默认 110（/24 别名块对齐） | 按机型 ENI×IP 算，常 <110，靠 Prefix Delegation 提密度 |
| L7 Ingress | 全球 App LB + NEG | ALB + LB Controller |
| 容器原生 LB | NEG 直连 Pod（跳过 NodePort） | ALB IP target 模式 |
| Pod 微分段 | Network Policy（Calico/Dataplane V2） | Network Policy（Calico） |

## 五、批改得分（20 题，Q1-Q4 未答）

| 模块 | 题 | 得分 |
|---|---|---|
| 互联 | Q5/Q6 | 5.5 / 5 |
| 出口/NAT | Q7/Q8 | 5 / 3.5 |
| DNS/CDN | Q9/Q10 | 4.5 / 5 |
| 分层安全 | Q11/Q12 | 4.5 / 5 |
| 可观测 | Q13/Q14 | 2.5 / 7 |
| GKE 网络 | Q15/Q16 | 4 / 2 |
| 多区域 | Q17/Q18 | 5.5 / 3 |
| 安全边界/选型 | Q19/Q20 | 0 / 5.5 |

**薄弱重点**（需补）：零信任 IAP/BeyondCorp、VPC Service Controls、GKE 网络（VPC-native 三段IP / NEG 容器原生 LB / Network Policy）、Network Intelligence Center。
