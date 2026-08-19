# 生产链路压测与加固性能验证 —— 关键发现

对 OpenCart（CloudFront VPC Origins + 私有 ALB + ASG + Aurora + WAF）做真实生产链路压测，记录几个高价值发现。

> ⚠️ 所有敏感值（域名、账号 ID、CloudFront ID、资源 ID）已用占位符。

---

## 测试方法

- **发压端**：6 台 c7i.2xlarge，`wrk 4.2.0`（AL2023 上编译需 `make WITH_OPENSSL=/usr` + 装 `perl-FindBin`，否则自带 openssl 编译失败）。
- **入口**：全部打**生产自定义域名** `https://www.<YOUR_DOMAIN>`（走完整链路：域名 → CloudFront → VPC Origin → 私有 ALB → ASG → Aurora），而非直连 CloudFront 默认域名或 ALB。
- **读**：`wrk -t8 -c400 -d30s` GET 首页（走 CloudFront 缓存）。
- **写**：`wrk -t8 -c350 -d300s` POST `cart.add`（不可缓存，全透传后端）。
- **配置**：ASG 预扩到 24 台（避免冷启动死锁），Aurora 1 writer + 3 reader。

---

## 结果

| 指标 | 数值 |
|---|---|
| 读 QPS（GET，CloudFront 缓存）| **20-23 万 req/s**，零错误 |
| 写 TPS（cart.add，5 分钟稳态）| **≈6400-6700 TPS**，错误率 ~0.1% |
| 目标（10 万并发 × 5% 下单 = 5000 TPS）| **达成并超越** |

压测时 Aurora writer CPU 峰值 ~76%（健康），internal ALB 收到 29-35 万请求/分钟。

---

## 发现 1：读走缓存、写透传 —— 入口方式对写路径无差异

- **读（GET）**：CloudFront 边缘缓存命中，几乎不回源。走自定义域名还是 CloudFront 默认域名，性能一致（都是同一个分发的边缘缓存）。
- **写（POST cart.add）**：CloudFront 不缓存，全透传回源。性能取决于后端，与入口域名无关。

> 结论：**CDN 对读密集电商是压倒性优化**（读 QPS 是写 TPS 的 30 倍以上）；写路径必须靠后端水平扩展。

---

## 发现 2：VPC Origins 加固后，写性能零损失

把 origin 从"公网 ALB"改成"CloudFront VPC Origin → 私有 ALB"（安全加固，见 `hardening-vpc-origins.md`）后，同压力下写 TPS 与加固前**基本一致（6400 vs 6700，正常波动）**。

> 结论：**VPC Origins 私有链路不影响正常业务吞吐**。（注意：VPC origin 有连接配额，可在 Service Quotas 申请提升，但真实业务极难触及。）

---

## 发现 3（重要）：WAF Web ACL 有 10 万 RPS 默认配额 —— 压测超高频会被误伤

**现象**：给 CloudFront 关联 WAF 后，`cart.add` 压测**从很低并发就 100% 返回 `403 Error from cloudfront`**，且 internal ALB 的 RequestCount ≈ 0（请求根本没到后端）。但**单发/低频 cart.add 完全正常（200）**。

**排查过程（一次只改一个变量，拿真实证据，不推理）**：
1. 直连后端 `localhost`（绕过 CloudFront+WAF+ALB）：`ab` 3000 请求 **0 失败** → 后端正常。
2. **解绑 WAF**（`WebACLId=""`）后重压：`cart.add` **全成功 0 错误**，请求正常到后端 → **WAF 是变量**。
3. WAF 规则**全改 Count 模式**（匹配也不拦）：仍大量失败，且**所有规则 Blocked/Counted 计数 = 0** → **不是规则拦截，是 Web ACL 整体层面**。

**根因（AWS 官方文档坐实）**：
> AWS WAF quotas：**"Maximum requests per second per web ACL = 100,000"**（默认配额，可申请提升）。
> https://docs.aws.amazon.com/waf/latest/developerguide/limits.html

压测 wrk 极高频（6 台合计报告 ~19 万 req/s）**超过单 Web ACL 的 10 万 RPS 配额 → 超出部分在规则评估之前被 CloudFront 直接 403 拒绝**（所以规则 Block/Count 全 0）。

**完美解释所有现象**：解绑就好 / 规则 Count 仍坏 / 规则计数全 0 / 低并发真实业务正常 / 后端直连正常。

**是"速率"不是"内容相似"（对照实验实测确认）**：
为区分"纯速率限制"vs"相同请求被去重/异常检测"，做对照实验（WAF 关联状态，同并发各 20s）：
- 组 A（内容完全相同，固定 body）：246 万请求，**100% Non-2xx**
- 组 B（内容各异，每次随机 product_id + 随机 nonce + 随机 URL 参数）：237 万请求，**同样 100% Non-2xx**

→ **内容随机化完全不改变结果，确凿证明是纯速率限制（RPS），与请求内容/是否相似无关。** 两组都约 12 万 req/s，正好超 10 万 RPS 配额。

**仍待核实（诚实标注）**：读 QPS 20 万也超 10 万 RPS 却没报错，可能与"缓存命中请求是否计入 WAF RPS 统计"有关，此点未完全查证，不臆断。

---

## 教训

1. **压测只看 TPS 会骗人**：WAF 超配额时返回 403 极快，wrk 报告"19 万 TPS"实为 100% 错误响应。**必须同时看错误率（Non-2xx）+ 后端 RequestCount**，否则会把"全失败"误读成"性能暴涨"。
2. **排障一次只改一个变量 + 拿真实证据**：直连后端 / 解绑 WAF / 规则改 Count，逐步隔离，比任何推理都可靠。
3. **WAF 对真实生产无影响**：生产流量极难到 10 万 RPS（如 cart.add 单实例真实约 100 TPS，几十台也就几千 RPS）。要压测高 TPS 写，需**临时解绑 WAF** 或**申请 WAF RPS 配额提升**（Service Quotas，`wafv2`）。
4. **AL2023 编译 wrk**：`dnf install perl-FindBin perl-IPC-Cmd openssl-devel` + `make WITH_OPENSSL=/usr`。
5. **SSM send-command 传脚本用 base64**，避免引号/换行被 JSON 转义破坏；`get-command-invocation` 输出多行时用 Python 解析，别用 shell 算术（多行会报语法错误）。

---

## 附：加固项与性能影响总表

| 加固项 | 层 | 对读 | 对写（真实业务）| 对写（压测超高频）|
|---|---|---|---|---|
| VPC Origins（私有 ALB）| 网络 | 无影响 | 无影响 | 有连接配额（可提升）|
| WAF（托管规则 + 限流 + IP 白名单）| 边缘 | 无影响 | 无影响 | **10 万 RPS 配额会被触发** |
| 安全响应头 + 强制 HTTPS | 边缘 | 无影响 | 无影响 | 无影响 |
| SEO URL | 应用 | 无影响 | 无影响 | 无影响 |
