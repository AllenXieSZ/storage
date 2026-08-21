# OpenCart 完整下单（Guest COD）真实 TPS、扩容瓶颈与持久连接优化实测

> 环境：AWS us-east-2 · OpenCart 4.0.2.0 · EC2 c7i.xlarge（ASG）· Aurora MySQL（r6g.xlarge~4xlarge）· internal ALB
> 时间：2026-08-21

## TL;DR

1. **完整下单（COD）真实稳定上限 ≈ 25-30 TPS，与 app 台数几乎无关**（3 台 ~24，36 台 ~29）。
2. **≠ cart.add 的 5000 TPS**：完整下单是 8 步 HTTP + 重写事务，比 cart.add 重 20-30 倍。
3. **加机器反而有害**：36 台高并发把 Aurora 连接数打满 2000，300 TPS 成功率 <1%。
4. **RDS Proxy 对 OpenCart 下单无效**（PHP 事务 + LAST_INSERT_ID 触发 connection pinning）。
5. **✅ mysqli 持久连接（改 1 行 config）是关键突破**：连接数 2000→300（-85%），60 TPS 成功率 78%→99.6%。但延迟型瓶颈仍在，单靠它 TPS 仍 ~23。

## 完整 Guest COD 下单流程（7 步，缺一不可）

| 步 | route | 作用 |
|---|---|---|
| 1 | `checkout/cart.add` | 加购（选无必填 option 商品，pid 28/29/31…；42/30/35/47 有必填选项会失败） |
| 2 | `checkout/register.save` | guest + 地址（字段带 `shipping_`/`payment_` 前缀） |
| 3 | `checkout/shipping_method.quote` → `.save` | 先 quote 算方式，再 save（`flat.flat`） |
| 4 | `checkout/payment_method.getMethods` → `.save` | 先 getMethods，再 save（`cod.cod`） |
| 5 | `checkout/confirm` | 建单，但 **order_status_id=0（后台不显示）** |
| 6 | **`extension/opencart/payment/cod.confirm`** | **关键！addHistory 把状态改 Pending(1) → 后台可见** |
| 7 | `checkout/success` | 清购物车 |

**踩坑**：只做到第 5 步 `confirm`，订单停在 status=0（"Missing Order"），Dashboard 只统计 status>0 所以显示 0 单。必须调第 6 步支付模块 confirm 才真正确认。数据库以 `SELECT order_status_id,COUNT(*) FROM oc_order GROUP BY order_status_id` 为准。

## 扩容实测：瓶颈层层转移

| 配置 | 目标 TPS | 成功率 | 下单 TPS | 延迟中位 | 瓶颈 |
|---|---|---|---|---|---|
| 3 台 + xlarge | 20 | 100% | 19 | 1.7s | 健康 |
| 3 台 | 50 | 100% | ~24 | 7.9s | 饱和（纯排队） |
| 36 台 + xlarge | 300 | <1% | 0 | 全超时 | **Aurora 连接数打满 2000（CPU 仅 18.7%）** |
| 36 台 + RDS Proxy | 300 | <1% | 0.4 | 全超时 | Proxy pinning 失效，连接仍 ~2000 |
| 36 台 + 4xlarge | 300 | 1.5% | 1.2 | 全超时 | 连接缓解但瞬时并发压垮 app |
| 36 台 + 4xlarge | 60 | 78% | 19.5 | 7.5s | 接近上限（连接争用） |
| 36 台 + 4xlarge | 30 | 98% | ~29 | 1.3s | ✅ 稳定 |

**核心发现**：从 3 台加到 36 台（12×），稳定 TPS 只从 24→29。瓶颈不在 app 算力，而在连接数 + 每单串行往返。

## ✅ mysqli 持久连接优化（关键突破，改动极小）

### 改法（1 行）
OpenCart mysqli 驱动 `system/library/db/mysqli.php` 用 `real_connect($hostname, ...)`，hostname 来自 `config.php` 的 `DB_HOSTNAME`。只需给 `DB_HOSTNAME` 加 **`p:` 前缀**（config.php + admin/config.php 都改）：
```php
define('DB_HOSTNAME', 'p:opencart-aurora.cluster-xxx.rds.amazonaws.com');
```
`p:` 让 php-fpm 每个 worker 复用到 DB 的 TCP 连接，连接数 ≈ **总 worker 数**，而非并发请求数。

### 实测对比（60 TPS，3 台 app）

| 指标 | 非持久连接 | **持久连接（p:）** | 改善 |
|---|---|---|---|
| Aurora 连接数峰值 | ~2000（打满上限） | **~300（稳定，仅 15%）** | **-85%** |
| 60 TPS 成功率 | 78%（大量 add 失败） | **99.6%（5380/5400）** | +22pt |
| 下单 TPS | 19.5 | 23.2 | +19% |

**结论**：持久连接彻底解决"连接数打满"死结——连接数稳定在 ~300（≈php-fpm worker 数），不再随并发暴涨。这是 OpenCart 下单扩容的**关键第一步**。

### 局限（诚实标注）
持久连接解决**连接数瓶颈**，但**解决不了"每单 8 次串行 HTTP + 重写事务"的延迟型瓶颈**——所以单靠它下单 TPS 仍卡 ~23、延迟仍高（60 TPS 时中位 12.9s）。要冲更高需应用层重构：合并 checkout 的 8 步 AJAX、批量化 SQL、减少每单往返。

## PHP 连接池方案对比

| 方案 | 原理 | 效果 | 改动 |
|---|---|---|---|
| **mysqli 持久连接 `p:`** ✅ | php-fpm worker 复用连接 | 连接数-85%，实测有效 | 1 行 config |
| RDS Proxy | 托管连接池 | ❌ PHP 事务触发 pinning，退化透传，无效 | 建 proxy |
| ProxySQL（本地） | 每台装，multiplexing | 理论有效（未测） | 每台装+配 |
| 减少每单往返 | 合并步骤/批量 SQL | 治本（延迟型瓶颈） | 大改 |

## 冲更高下单 TPS 的正确路径
1. **持久连接**（已验证，先做）——解决连接数墙。
2. **渐进爬坡**，绝不一次砸满（300 一次砸满=0 成功；30 稳定 98%）。
3. **减少每单往返**（应用层重构 8 步 checkout）——解决延迟型瓶颈。
4. app 台数无需很多（CPU 远没打满），重点在 DB 连接管理 + 应用优化。

---
测试日期：2026-08-21 (UTC) · 结论：完整下单真实 TPS ≈ 25-30；瓶颈=连接数+串行往返（非算力）；持久连接实测降连接数 85%、成功率升至 99.6%，是低成本关键优化。
