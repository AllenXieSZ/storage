# OpenCart 自定义域名 + HTTPS + CloudFront VPC Origins 加固完整指南

把一个跑在 AWS 上的 OpenCart 电商站（ALB + EC2/ASG + Aurora + S3 图片 + CloudFront）：

1. 绑定**自定义域名**（域名在**阿里云** DNS 托管，不是 Route 53）
2. 上 **HTTPS**（ACM 证书 + SSL 卸载在 CloudFront）
3. 安全加固成 **CloudFront 是唯一入口**（VPC Origins + 私有 internal ALB，后端不暴露公网）
4. 图片走**同域名路径路由**到 S3（不暴露 S3 桶域名）

> ⚠️ 本文所有敏感值（账号 ID、桶名、CloudFront ID、ACM ARN、DNS 验证记录、域名）均已用**占位符**替换。落地时替换成你自己的值。

---

## 0. 架构总览

```
                          ┌─────────── HTTPS(443) ───────────┐
   浏览器 ────────────────►│           CloudFront             │  ← SSL 卸载点（TLS 在此终止）
   www.<YOUR_DOMAIN>       │   (唯一入口, ACM 证书 us-east-1)  │
                          └──────┬───────────────────┬───────┘
                                 │ /image/*          │ /* , /admin/* , /catalog/view/*
                                 │ (HTTP)            │ (HTTP, VPC Origin 私有连接)
                          ┌──────▼──────┐     ┌──────▼─────────────────┐
                          │  S3 (私有)  │     │  内部 ALB (internal)    │
                          │  OAC 只读   │     │  仅允许 CloudFront SG   │
                          └─────────────┘     └──────┬─────────────────┘
                                                     │ (私有子网)
                                              ┌──────▼──────┐
                                              │ ASG EC2×N    │
                                              │ (私有子网)   │
                                              └──────┬──────┘
                                                     │
                                              ┌──────▼──────┐
                                              │  Aurora      │
                                              └─────────────┘
```

占位符对照：

| 占位符 | 含义 | 示例 |
|---|---|---|
| `<YOUR_DOMAIN>` | 你的根域名 | `example.online` |
| `www.<YOUR_DOMAIN>` | 站点主域名 | `www.example.online` |
| `<ACCOUNT_ID>` | AWS 账号 ID | 12 位数字 |
| `<REGION>` | 主区域 | `us-east-2` |
| `<CF_DIST_ID>` | CloudFront 分发 ID | `E00XXXXXXXXXX` |
| `<CF_DEFAULT_DOMAIN>` | CloudFront 默认域名 | `dxxxxxxxxxxxxx.cloudfront.net` |
| `<ACM_CERT_ARN>` | ACM 证书 ARN（**us-east-1**） | `arn:aws:acm:us-east-1:<ACCOUNT_ID>:certificate/xxxx` |
| `<IMAGE_BUCKET>` | S3 图片桶 | `opencart-images-xxxx` |
| `<VPC_ID>` / `<PRIVATE_SUBNET_x>` | VPC / 私有子网 | |
| `<CF_VPCORIGIN_SG>` | CloudFront 服务托管 SG | `CloudFront-VPCOrigins-Service-SG` |

---

## 1. 域名与 DNS（阿里云托管）

域名注册在阿里云、DNS 也由阿里云解析（本例 AWS 账号被限制不能自助注册 Route 53 域名）。
**所有 DNS 记录在阿里云控制台操作。**

最终阿里云需要 **3 类 CNAME 记录**（HTTPS 场景）：

| 主机记录 | 类型 | 记录值 | 用途 |
|---|---|---|---|
| `_<ACM_TOKEN_1>.www` | CNAME | `_<ACM_TARGET_1>.<xxx>.acm-validations.aws` | ACM 验证 `www` 归属 |
| `_<ACM_TOKEN_2>`（根） | CNAME | `_<ACM_TARGET_2>.<xxx>.acm-validations.aws` | ACM 验证根域名归属 |
| `www` | CNAME | `<CF_DEFAULT_DOMAIN>` | **实际访问指路** |

> ⚠️ **验证记录 ≠ 访问记录**：前两条 `_xxx` 是一次性的"身份证明"（证书续期还会用，建议保留）；第三条 `www → cloudfront` 才是用户访问真正靠的记录。
> ⚠️ 证书里有几个域名（SAN）就有几条 `_xxx` 验证记录，**全部加齐、全部验证通过，证书才会 ISSUED**；缺一条整证书卡在 `PENDING_VALIDATION`。
> ⚠️ **CNAME 不能用于裸根域名 `@`**。裸域名访问需用阿里云"隐性 URL 转发"跳转到 `www`，或使用支持 CNAME 拉平的方案。

验证 DNS 是否生效：

```bash
dig +short www.<YOUR_DOMAIN>
# 期望：www.<YOUR_DOMAIN> -> CNAME -> <CF_DEFAULT_DOMAIN> -> 多个 CloudFront 边缘 A 记录
```

---

## 2. ACM 证书（必须在 us-east-1）

CloudFront 是全局服务，**只读 us-east-1 的 ACM 证书**。

```bash
# 申请证书（覆盖 www + 根域名），DNS 验证
aws acm request-certificate \
  --region us-east-1 \
  --domain-name "www.<YOUR_DOMAIN>" \
  --subject-alternative-names "<YOUR_DOMAIN>" \
  --validation-method DNS \
  --query CertificateArn --output text
# => <ACM_CERT_ARN>

# 取出需要在阿里云添加的 DNS 验证记录（每个域名一条 CNAME）
aws acm describe-certificate --region us-east-1 --certificate-arn <ACM_CERT_ARN> \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord' --output json
```

把返回的 CNAME 记录（Name/Value）填到阿里云 → 等状态 `PENDING_VALIDATION` → `ISSUED`（DNS 对了几分钟自动过）：

```bash
aws acm describe-certificate --region us-east-1 --certificate-arn <ACM_CERT_ARN> \
  --query 'Certificate.Status' --output text
```

---

## 3. CloudFront 绑定自定义域名 + 证书

证书 `ISSUED` 后，给分发加 Aliases + 绑证书（SNI-only, TLSv1.2_2021）：

```bash
# 取当前配置 + ETag
aws cloudfront get-distribution-config --id <CF_DIST_ID> > cf.json
# 编辑 DistributionConfig：
#   Aliases.Items = ["www.<YOUR_DOMAIN>", "<YOUR_DOMAIN>"]  (Quantity=2)
#   ViewerCertificate = {
#     "ACMCertificateArn": "<ACM_CERT_ARN>",
#     "SSLSupportMethod": "sni-only",
#     "MinimumProtocolVersion": "TLSv1.2_2021",
#     "Certificate": "<ACM_CERT_ARN>",
#     "CertificateSource": "acm"
#   }
aws cloudfront update-distribution --id <CF_DIST_ID> \
  --if-match <ETAG> --distribution-config file://config-only.json
```

验证：`curl -I https://www.<YOUR_DOMAIN>/` 应返回 200 且 SSL 校验通过。

---

## 4. 图片走同域名路径路由到 S3（不暴露 S3 桶域名）

**最佳实践：同一个 CloudFront 分发 + 多 path pattern 路由到不同 origin。** 用户始终只看到你的域名。

CloudFront behaviors（本例）：

| PathPattern | Origin | 说明 |
|---|---|---|
| `/image/*` | S3 origin（`<IMAGE_BUCKET>`，OAC 只读） | 图片，缓存优化 |
| `/catalog/view/*` | ALB origin | 静态 CSS/JS，缓存优化 |
| `/admin/*` | ALB origin | 后台，不缓存 |
| `*`（默认） | ALB origin | 动态页 |

效果（实测响应头）：
```
GET https://www.<YOUR_DOMAIN>/image/catalog/xxx.png
→ server: AmazonS3
→ x-cache: Hit from cloudfront
→ via: 1.1 xxxx.cloudfront.net (CloudFront)
```
浏览器地址栏和 HTML 里的图片 URL 都是 `https://www.<YOUR_DOMAIN>/image/...`，**S3 桶域名不出现在任何页面**，且 S3 桶为私有（仅 CloudFront OAC 可读）。

> 🚫 **不要**把图片直接改成 S3 桶域名（`<IMAGE_BUCKET>.s3.<REGION>.amazonaws.com`）——那会暴露桶、绕过 CDN 缓存、并在 HTTPS 页面引入 Mixed Content 风险。同域名路径路由才是正解。

S3 桶策略（OAC 授权，不算"公开访问"，不受 Block Public Access 影响）：
```json
{
  "Effect": "Allow",
  "Principal": { "Service": "cloudfront.amazonaws.com" },
  "Action": "s3:GetObject",
  "Resource": "arn:aws:s3:::<IMAGE_BUCKET>/*",
  "Condition": { "StringEquals": { "aws:SourceArn": "arn:aws:cloudfront::<ACCOUNT_ID>:distribution/<CF_DIST_ID>" } }
}
```

---

## 5. OpenCart 应用层配置（关键，避免露出 CloudFront/ALB 域名）

OpenCart 用 `HTTP_SERVER` 生成 `<base href>` 和所有内链。若写成 CloudFront 默认域名或 ALB 域名，页面跳转就会露出它们。

- `config.php`：
  ```php
  define('HTTP_SERVER', 'https://www.<YOUR_DOMAIN>/');
  ```
- `admin/config.php`：
  ```php
  define('HTTP_SERVER', 'https://www.<YOUR_DOMAIN>/admin/');
  define('HTTP_CATALOG', 'https://www.<YOUR_DOMAIN>/');
  ```

> ⚠️ 必须用 `https://`，否则 HTTPS 页面里混进 http 资源 → 浏览器拦截 Mixed Content → 布局裸奔。

**ASG 持久化（重要）**：EC2 在 ASG 里时，改现有实例只是临时的——必须把正确配置**烘焙进 AMI**，再更新 Launch Template + Instance Refresh 滚动替换。否则扩容出的新实例又是旧配置。（详见本目录 `hardening-vpc-origins.md`）

---

## 6. 安全加固：CloudFront VPC Origins（唯一入口）

见 [`hardening-vpc-origins.md`](./hardening-vpc-origins.md)。

核心：把 ALB 从公网 internet-facing 改成私有 internal（scheme 不可原地改，需新建），用 CloudFront VPC Origin 私有连接，internal ALB 的 SG 只允许 `CloudFront-VPCOrigins-Service-SG`。这样后端不暴露公网，谁都绕不过 CloudFront。

---

## 关键坑速查

1. **ACM 证书必须 us-east-1**（CloudFront 只读该区）。
2. **证书有几个域名就有几条 `_xxx` 验证记录**，全加齐才 ISSUED。
3. **CNAME 不能用于裸根域名**，裸域名需 URL 转发跳 www。
4. **OpenCart `HTTP_SERVER` 用 https + 自定义域名**，否则露 CloudFront 域名 / Mixed Content。
5. **ASG 场景配置要烘焙进 AMI**，改现有实例不持久。
6. **图片用同域名路径路由到 S3**，别直接用 S3 桶域名。

---

## 附：NAT Gateway 必要性实测（web server 出网需求分析）

**问题**：三层架构里 web server（app 层）在私有子网，出站默认走 NAT Gateway。NAT 有成本（约 $0.045/h + 流量费）。web server 到底有没有主动出公网需求？去掉 NAT 网站还能否正常？

**实测方法**：建 S3 Gateway Endpoint（免费）+ SSM Interface Endpoint，删私有子网路由表的 `0.0.0.0/0 → NAT`，逐项测。

**结果**：

| 功能 | 去 NAT 后 | 依赖 |
|---|---|---|
| 网站首页/商品页（用户访问）| ✅ 200 | 入站 CloudFront→ALB，不依赖 NAT |
| Aurora / Redis | ✅ | VPC 内部私网 |
| S3 图片读写 | ✅ | **S3 Gateway Endpoint**（免费，替代 NAT）|
| SSM 远程管理 | ✅ | **SSM Interface Endpoint**（替代 NAT，有小额费用）|
| **在线支付 API（如 PayPal）** | ❌ 000 超时 | **必须出公网**，VPC Endpoint 替代不了 |
| yum/dnf 更新、通用互联网 | ❌ | 需出公网 |

**结论**：
1. **网站核心功能（浏览/下单/图片/数据库）不需要 NAT** —— 入站走 ALB，内部走私网，S3/SSM 可用 VPC Endpoint 替代。去掉 NAT 网站照常运行。
2. **唯一真正需要出公网的是"后端主动调第三方 API"** —— 如在线支付（PayPal `api-m.sandbox.paypal.com`）、外部 webhook、第三方物流/短信 API 等。这类需求 VPC Endpoint 替代不了，必须保留 NAT（或用 NAT 实例/egress 方案）。
3. **省钱建议**：
   - 若无第三方 API 出站需求 → 去掉 NAT，配 **S3 Gateway Endpoint（免费）+ SSM Interface Endpoint**，网站完全正常，省 NAT 费。
   - 若有（如在线支付）→ 保留 NAT；但仍建议加 **S3 Gateway Endpoint**（免费）把 S3 流量从 NAT 分流，省 NAT 数据处理费。
   - **S3 Gateway Endpoint 免费且总应该加**（S3 流量不走 NAT，省流量费）。SSM/其它 Interface Endpoint 按需（每个约 $7/月 + 流量，多个时不一定比 NAT 省）。

> 实测已恢复原样（NAT 路由保留，测试用 endpoints 已删）。本站因有 PayPal 支付演示（需出公网），保留了 NAT。
