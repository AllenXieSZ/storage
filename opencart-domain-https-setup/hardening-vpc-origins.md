# CloudFront VPC Origins 加固：让 CloudFront 成为唯一入口

把公网 internet-facing ALB（可被绕过 CloudFront 直连）改造为 **CloudFront VPC Origins → 私有 internal ALB**。
基于 AWS 官方文档：
- CloudFront DevGuide《Restrict access to Application Load Balancers》
- CloudFront DevGuide《Restrict access with VPC origins》

> ⚠️ 所有敏感值已用占位符。参见 `README.md` 的占位符对照表。

---

## 为什么

默认架构有两个"后门"：
1. CloudFront 默认域名 `<CF_DEFAULT_DOMAIN>` 可直接访问（绕过自定义域名）。
2. 公网 ALB 域名可直接访问（**绕过 CloudFront**：跳过缓存/WAF/HTTPS，直连后端）。

官方给的方案（从强到弱）：
- **方案 1（最彻底，本文）**：VPC Origins —— ALB 放私有子网，不暴露公网，CloudFront 经私有连接访问。
- 方案 2：CloudFront 加秘密自定义头 + ALB 规则只放行带该头的请求 + 强制 HTTPS。
- 方案 3：ALB 安全组只放行 CloudFront 托管前缀列表 `com.amazonaws.global.cloudfront.origin-facing`（建议与方案 2 叠加）。

---

## 硬约束（先知道）

- **ALB 的 scheme（internet-facing / internal）创建后不可改** → 必须**新建 internal ALB**。
- **一个 Target Group 不能同时关联两个 ALB** → 需**新建 TG**（并挂到 ASG，让实例自动注册）。
- VPC Origins 要求：VPC 有 IGW（仅标记可收 internet，不改路由）；私有子网 ≥1 可用 IPv4（给 service-managed ENI）；ALB 必须 **Active** 才能建 VPC origin。
- 不支持：gRPC、Lambda@Edge 的 origin request/response 触发。
- 入站 NACL 不评估（对 CloudFront→origin），但**出站 NACL 要放行临时端口 1024–65535**。

---

## 执行步骤（新建 → 验证 → 切换 → 删旧，零中断）

### 1. 新建 internal ALB 专用 SG + internal ALB

```bash
# SG
SG=$(aws ec2 create-security-group --region <REGION> \
  --group-name opencart-internal-alb-sg \
  --description "internal ALB for VPC origin - allow CloudFront only" \
  --vpc-id <VPC_ID> --query GroupId --output text)

# internal ALB（3 私有子网）
ALB=$(aws elbv2 create-load-balancer --region <REGION> \
  --name opencart-internal-alb --scheme internal --type application \
  --subnets <PRIVATE_SUBNET_A> <PRIVATE_SUBNET_B> <PRIVATE_SUBNET_C> \
  --security-groups $SG --query 'LoadBalancers[0].LoadBalancerArn' --output text)
```

### 2. 新建 TG + listener + 挂到 ASG

```bash
TG=$(aws elbv2 create-target-group --region <REGION> \
  --name opencart-tg-internal --protocol HTTP --port 80 \
  --vpc-id <VPC_ID> --health-check-path /hc.html \
  --target-type instance --query 'TargetGroups[0].TargetGroupArn' --output text)

aws elbv2 create-listener --region <REGION> --load-balancer-arn $ALB \
  --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=$TG

# 挂到 ASG（实例自动注册；未来扩缩容也覆盖）
aws autoscaling attach-load-balancer-target-groups --region <REGION> \
  --auto-scaling-group-name <ASG_NAME> --target-group-arns $TG

# APP 实例 SG 放行来自 internal ALB SG 的 80
aws ec2 authorize-security-group-ingress --region <REGION> \
  --group-id <APP_SG> --protocol tcp --port 80 --source-group $SG

# 等 ALB Active + 目标 healthy
aws elbv2 wait load-balancer-available --region <REGION> --load-balancer-arns $ALB
```

### 3. 建 CloudFront VPC Origin（指向 internal ALB）

```bash
cat > vpco.json <<EOF
{
  "Name": "opencart-internal-alb-vpco",
  "Arn": "$ALB",
  "HTTPPort": 80,
  "HTTPSPort": 443,
  "OriginProtocolPolicy": "http-only",
  "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] }
}
EOF
aws cloudfront create-vpc-origin --vpc-origin-endpoint-config file://vpco.json
# 等状态 Deploying -> Deployed（约 10-15 分钟）
aws cloudfront get-vpc-origin --id <VPC_ORIGIN_ID> --query 'VpcOrigin.Status'
```

创建后 CloudFront 会自动生成服务托管安全组 `CloudFront-VPCOrigins-Service-SG`（**不要手动改它**）。

### 4. 切 CloudFront origin 到 VPC Origin

编辑分发 config，把原 ALB origin：
- `DomainName` 改成 internal ALB 的 DNS 名
- **删掉 `CustomOriginConfig`**
- 加 `VpcOriginConfig`：

```json
"VpcOriginConfig": {
  "VpcOriginId": "<VPC_ORIGIN_ID>",
  "OriginReadTimeout": 30,
  "OriginKeepaliveTimeout": 5
}
```

```bash
aws cloudfront update-distribution --id <CF_DIST_ID> \
  --if-match <ETAG> --distribution-config file://config-only.json
```

### 5. ⚠️ 放行 CloudFront 到 internal ALB（关键坑）

切完若站点超时（HTTP 000），是因为 internal ALB 的 SG 没放行 CloudFront。**放行来自 CloudFront 服务托管 SG 的入站**（比托管前缀列表更严：只允许你自己的分发）：

```bash
# 找 service SG
CF_SG=$(aws ec2 describe-security-groups --region <REGION> \
  --filters "Name=group-name,Values=CloudFront-VPCOrigins-Service-SG*" \
  --query 'SecurityGroups[0].GroupId' --output text)

aws ec2 authorize-security-group-ingress --region <REGION> \
  --group-id $SG --protocol tcp --port 80 --source-group $CF_SG
```

（可选：用托管前缀列表 `com.amazonaws.global.cloudfront.origin-facing`，但它只锁"来自 CloudFront IP"，不锁具体分发，建议用 service SG。）

### 6. 验证 + 删旧公网 ALB

```bash
curl -I https://www.<YOUR_DOMAIN>/    # 期望 200

# 从 ASG 解绑旧 TG，删旧公网 ALB + 旧 TG
aws autoscaling detach-load-balancer-target-groups --region <REGION> \
  --auto-scaling-group-name <ASG_NAME> --target-group-arns <OLD_TG_ARN>
aws elbv2 delete-load-balancer --region <REGION> --load-balancer-arn <OLD_ALB_ARN>
aws elbv2 delete-target-group --region <REGION> --target-group-arn <OLD_TG_ARN>
```

删后旧公网 ALB 域名应无法解析（后门关闭），自定义域名仍 200。

---

## ASG 配置持久化：烘焙 AMI（走正路）

改现有实例的 `config.php` 只是临时的——ASG 扩容/自愈会用 Launch Template 的 AMI 起**旧配置**的新实例。正确做法：

```bash
# 1. 从改好的干净实例烤 AMI（--no-reboot 不影响在服务实例）
AMI=$(aws ec2 create-image --region <REGION> --instance-id <GOOD_INSTANCE> \
  --name "opencart-app-$(date +%Y%m%d-%H%M)" --no-reboot --query ImageId --output text)
aws ec2 wait image-available --region <REGION> --image-ids $AMI

# 2. LT 新版本用新 AMI（user-data 保持干净，只启动服务），设为默认
aws ec2 create-launch-template-version --region <REGION> \
  --launch-template-id <LT_ID> --source-version '$Latest' \
  --launch-template-data "{\"ImageId\":\"$AMI\"}"
aws ec2 modify-launch-template --region <REGION> --launch-template-id <LT_ID> \
  --default-version <NEW_VER>

# 3. Instance Refresh 滚动替换（保证滚动期间不断服务）
aws autoscaling start-instance-refresh --region <REGION> \
  --auto-scaling-group-name <ASG_NAME> \
  --preferences '{"MinHealthyPercentage":90,"InstanceWarmup":150}'
```

验证：`describe-instance-refreshes` 到 `Successful`，且每台 InService 实例的 ImageId 都是新 AMI。

> 教训：**改 ASG 后端配置必须同步进 Launch Template（AMI 或 user-data）**，否则新实例是旧配置——和 fstab 改完要 `daemon-reload` 一个道理。

---

## 关键坑速查

1. **ALB scheme 不可改** → 新建 internal ALB。
2. **一个 TG 不能绑两个 ALB** → 新建 TG 挂 ASG。
3. **切 origin 后站点超时** → internal ALB SG 没放行 CloudFront service SG。
4. **VPC Origin 创建异步**，等 `Deployed`（10-15 min）才能被分发引用。
5. **ASG 配置烘焙进 AMI**，别只改现有实例。
