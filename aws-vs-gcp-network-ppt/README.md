# AWS vs GCP 网络产品深度对比 PPT

18 页对比演示文稿，NetApp 风模板，AWS 橙 / GCP 蓝双列对照。覆盖 **8 大维度 + SLA + 总结**：外网、内网、加速、CDN、DNS、安全、DDoS、稳定性。**每条论点/数字均基于 AWS/GCP 官方文档核实**（每页脚注标来源），不确定/官方未取到处均诚实标注，绝不臆造。

## 内容结构（18 页）

1. 封面
2. 对标关系总览（8 大维度一表）
3. 维度 1 分隔页
4. **全球骨干网 & 网络分层** — GCP Network Service Tiers（Premium cold-potato / Standard hot-potato）两档可选 vs AWS 默认全程自有骨干无分层
5. **VPC / 内网架构 & 互联** — AWS VPC 区域级 vs GCP VPC 全局级；TGW vs NCC；PrivateLink vs PSC
6. **混合云互联** — Direct Connect vs Cloud Interconnect（MACsec/聚合/SLA）；S2S VPN vs Cloud VPN（HA/Classic）
7. 维度 4-5 分隔页
8. **负载均衡 & 外网入口** — GCP 单 anycast IP 全球分发 vs AWS 区域级 ELB
9. **加速** — AWS Global Accelerator vs GCP（无同名产品，Premium Tier + 全局 anycast LB 等价）
10. 维度 6-7 分隔页
11. **CDN** — CloudFront 一体（750+ POPs）vs Cloud CDN（100+）+ Media CDN 拆分
12. **DNS** — Route 53（8 种路由策略 + 域名注册）vs Cloud DNS（3 类）；DNSSEC；SLA
13. 维度 8 分隔页
14. **防火墙层（深水区）** — SG（有状态）+ NACL（无状态）vs GCP 单一有状态防火墙 + 层级策略
15. **WAF & 下一代防火墙** — AWS WAF / Network Firewall(Suricata/TLS) vs Cloud Armor / Cloud NGFW
16. **DDoS 防护（重点）** — Shield Standard/Advanced vs Cloud Armor Standard/Enterprise
17. **稳定性 / SLA 汇总** — 主要网络产品官方 SLA
18. 总结：关键差异一览

## 关键差异（官方核实）

1. **全球骨干**：GCP 分层可选（Premium cold-potato / Standard hot-potato）；AWS 默认全程自有骨干、无用户可选分层
2. **VPC 模型**：AWS VPC 区域级 vs GCP VPC 全局级 —— 最根本架构差异
3. **全球入口**：GCP 单 anycast IP 内建全球化 vs AWS 区域级 ELB + Global Accelerator/Route 53 补全球
4. **加速/CDN**：AWS 有独立 Global Accelerator + 一体 CloudFront；GCP 靠 Premium Tier + Cloud CDN/Media CDN 拆分
5. **DNS**：Route 53 路由策略更丰富（8 vs 3）+ 自带域名注册；两家 SLA 均 100% SLO（Route 53 最严重档赔 100%，Cloud DNS 封顶 50%）
6. **防火墙**：AWS SG（有状态，实例级，仅 allow）+ NACL（无状态，子网级，allow+deny）双层；GCP 单一有状态 + priority(0-65535，同级冲突 deny 胜出) + tag/SA 微隔离
7. **DDoS**：Shield Advanced = 24/7 SRT + 费用保护 + 500 亿 WAF 请求/月额度；Cloud Armor Enterprise = ML Adaptive Protection；两家均无 DDoS 专属 SLA、无官方可缓解规模数字
8. **专线**：两家都到 400G 单口 + MACsec；GCP 明确 8×400G=3200G 聚合；GCP 单连接 No SLA（需冗余才 99.99%）

## 官方来源（每页脚注标注）

**AWS**：docs.aws.amazon.com/vpc（VPC/peering/tgw/privatelink/security-groups/network-acls/limits）· /directconnect（MACsec/lags/sla）· /vpn · /global-accelerator · /AmazonCloudFront · /Route53（routing-policy/dnssec）· /network-firewall · /waf；aws.amazon.com/{elasticloadbalancing,cloudfront/pricing,route53/sla,shield,about-aws/global-infrastructure,network-tiers}
**GCP**：cloud.google.com/network-tiers · /vpc/docs（vpc/vpc-peering/private-service-connect/quota）· /network-connectivity/docs（interconnect/vpn/ncc）· /load-balancing · /cdn（overview/locations/pricing）· /media-cdn · /dns（routing-policies/dnssec/sla）· /firewall/docs · /armor · /storage/docs/uploads

## 诚实标注（官方本身未提供，非遗漏）

- CloudFront 每 GB 分区 DTO 单价（官方定价表 JS 动态渲染，抓不到原文）
- GCP Media CDN 精确定价（官方公开定价页 404，疑走 SKU/合同报价）
- 两家 DDoS 均无专属 SLA、无官方可缓解规模数字（Tbps/pps）
- "Media CDN 基于 YouTube 基础设施" 官方无背书（只说 Google global edge-caching infrastructure）

## 文件

- `aws_vs_gcp_network_ppt.py` — python-pptx 生成脚本
- `AWS_vs_GCP_Network.pptx` — 成品（18 页）
- `AWS_vs_GCP_Network.pdf` — PDF 预览
- `aws_vs_gcp_network_review.md` — 详细 review 文档（11 维度全文 + 官方来源清单）

## 生成方式

```bash
python3 aws_vs_gcp_network_ppt.py
soffice --headless --convert-to pdf AWS_vs_GCP_Network.pptx
```
