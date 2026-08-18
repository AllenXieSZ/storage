# OpenCart 写路径性能优化：阶梯压测逐层攻克瓶颈（目标 5000 TPS cart.add）

> 环境：AWS us-east-2 · OpenCart 4.1.0.4 · PHP 8.5 · Aurora MySQL 8.0 · ElastiCache Redis · 初始 3×EC2 t3.small
> 时间：2026-08-18
> 目标：支撑 10 万并发 × 5% 购物 = **5000 TPS 的 cart.add**（写路径）
> 方法论：**阶梯压测 → 定位瓶颈技术根因 → 针对性攻克 → 再压验证 → 瓶颈转移 → 循环**。优先技术手段（配置/代码/架构），扩容作为瓶颈确在算力时的合理手段。

## 压测工具与方法

- **发压端**：专用压测机 c7i.2xlarge（8 vCPU）+ **wrk**（C 实现，无 GIL）。单台 t3.small 用 Python threading 压测**测不准**（GIL 限制，测出的是客户端上限）。
- **发压路径**：从 VPC 内网打 ALB（cart.add 是 POST，不走 CloudFront 缓存），排除跨区网络干扰。
- **监控**：CloudWatch（EC2/Aurora/Redis CPU）+ 各机 `top`/`ps`/`ss` + MySQL `SHOW GLOBAL STATUS` 计数差值。

## 瓶颈演进链（逐层剥洋葱）

| 阶段 | cart.add QPS(c200) | 瓶颈定位 | 攻克手段 | 类型 |
|---|---|---|---|---|
| 初始 | 338 | php-fpm `pm.max_children=50` 打满，CPU 却只用 40% | 提到 80 + `pm=static` | 配置 |
| ② | 412 | 每请求 ~23 条 DB 查询（商品详情），往返延迟累积 | getProduct/getOptions Redis 读缓存 | 代码 |
| ③ | 412 | Aurora `db.t4g.medium` 单实例 **CPU 90%** | 加 1 读副本 + db.php 读写分离 | 架构+代码 |
| ④ | **570** | Aurora Writer 降至 10% / Reader 28%（数据库不再是瓶颈） | — | — |
| ⑤ | 570 卡住 | **3×t3.small app CPU 打满**（idle 5%，load 5.48/2核） | 升级 compute optimized 机型（进行中） | 扩容 |

**累计：338 → 570 TPS（+69%），全程未升级实例规格。**

## 各阶段技术细节

### 阶段①：php-fpm worker 池
- 现象：QPS 卡 330，但 app CPU 仅 40%、Aurora 10%。`pgrep -c php-fpm` = 51（=max_children 50 打满）。
- 根因：worker 不够，请求排队，而 CPU/DB 都有余量（I/O 等待型负载，worker 大量时间在等 Redis/DB 响应）。
- 修复：单进程实测仅 18.7MB，2GB 内存可容纳更多。设 `pm=static` + `pm.max_children=80`。

### 阶段②：商品详情读缓存（Cache-Aside）
- 现象：一次 cart.add ≈ 23 条 DB 查询 + 13 条 Redis 命令 = 36 次网络往返；CPU 不满但延迟高（往返累积，同 NFS 小文件/每页 122 SQL 一个道理）。
- 修复：给 `catalog/model/catalog/product.php` 的 `getProduct()` / `getOptions()` 套 OpenCart 内置 `$this->cache`（=Redis）Cache-Aside。
- **关键坑**：OpenCart `cache->get()` **未命中返回 `[]`（空数组）而非 `false`**。按 `!== false` 判断会导致 getProduct 永远返回空 → "Product could not be found" → 加购失败。必须用 `empty()` 判定未命中。（再次印证"知道概念≠知道实现细节"，改前必读源码 `system/library/cache/redis.php`）
- 收益有限（23→22）：商品详情只占少数查询，大头在 totals/库存/subscription 等分散逻辑。

### 阶段③④：Aurora 读写分离（核心突破）
- 现象：②之后 QPS 提升使请求更密集，Aurora `db.t4g.medium`（2 vCPU）**CPU 冲到 90%**，成新瓶颈。
- 事实：cart.add 的 ~20 条查询**几乎全是 SELECT**（读放大），而 Aurora 单 writer 实例扛不住。
- 手段：
  1. 加 1 个读副本 `opencart-aurora-reader`（同集群，reader endpoint 自动指向它）
  2. **改 `system/library/db.php` 实现应用层读写分离**：`query()` 拦截，`SELECT`（非事务、非 FOR UPDATE/GET_LOCK/LAST_INSERT_ID）走 reader，写和事务走 writer；reader 连不上自动降级 writer。开关常量 `DB_READER_HOSTNAME`。
- 验证：一次加购 → **Writer SELECT=1 + INSERT=1，Reader SELECT=118**（读彻底分流）。
- 结果：QPS 412→**570**，Aurora **Writer CPU 90%→10%，Reader 28%**。数据库不再是瓶颈。

> ⚠️ OpenCart 原生 `DB` 类只有单连接、不支持读写分离。本改造在 `query()` 这个唯一入口拦截分流，是干净的落点。

### 阶段⑤：app 层算力（当前瓶颈）
- 现象：数据库很闲（Writer 10%/Reader 28%），但 QPS 卡 570。3×t3.small 压测中 **CPU idle 仅 5%**、load 5.48（2 核严重过载）、fpm_busy 40+。
- 结论：瓶颈确实转移到 **app 层 CPU**。这是"瓶颈确在算力"的合理扩容点 → 升级 compute optimized（c 系列）机型。

## 关键方法论沉淀

1. **阶梯压测的价值 = 逐层剥洋葱**：每解决一个瓶颈，它就转移到下一环（fpm → DB CPU → app CPU）。不逐级验证，无法知道真瓶颈。
2. **CPU 不满但慢 = 往返延迟/排队瓶颈**，不是算力问题（阶段①②）。要看 fpm 队列、每请求查询数、往返次数。
3. **读放大用读写分离/缓存解，不是升配 writer**（阶段③）。
4. **压测工具本身不能是瓶颈**：wrk > ab > python threading。
5. **改任何"读缓存"前必读缓存库源码**，确认未命中返回值语义（`[]` vs `false` vs `null`）。

## 相关文件
- `db.php`（读写分离改造版）
- `product.php`（getProduct/getOptions 读缓存改造版）
- `cart.php`（购物车 Redis 改造版，见 opencart-cart-redis 目录）
- 后续：升级机型后的压测数据与最终 5000 TPS 达成情况将追加。
