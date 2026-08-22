# OpenCart 下单写路径优化（addOrder / addHistory / 读缓存）

针对 OpenCart **4.1.0.4** 的下单链路，按"**减少 DB 提交/往返次数**"这一核心思路做的一组优化，
覆盖事务化、批量 INSERT、读缓存，并用 benchmark 量化每一步收益。

> 环境：AWS us-east-2，3× c7i.xlarge (ASG) + Aurora MySQL (db.r6g.xlarge, 1 writer + 1 reader) + ElastiCache Redis + ALB。
> 所有连接凭据/内网端点在本仓库中已替换为 `YOUR_*` 占位符。

---

## 一、改了什么（5 项，均对比原版 4.1.0.4 逐行核对）

改动集中在 `catalog/model/checkout/order.php` 和两个 localisation model：

| # | 位置 | 改动 | 目的 |
|---|---|---|---|
| 1 | `order.php::addOrder` | 方法体包 `START TRANSACTION ... COMMIT`（异常 `ROLLBACK`） | N 次 autocommit 合并为 1 次提交 |
| 2 | `order.php::addHistory` | 同上，方法体包事务 | 下单状态变更（含扣库存）原子化 + 减提交 |
| 3 | `order.php::addOrder` | `order_total` 循环 → 单条多值 `INSERT ... VALUES (),(),()` | 减 INSERT 往返 |
| 4 | `order.php::addOrder` | `order_product` 循环 → 单条多值 INSERT，option 用 `firstId+idx` 关联回填 | 减 INSERT 往返，与商品数解耦 |
| 5 | `localisation/country.php`, `zone.php` | `getCountry/getCountryByIsoCode2/3`、`getZone` 加 Redis cache-aside | 地址校验读走缓存，卸 Aurora 读压力 |

完整改动见 `diffs/*.diff`（unified diff）。`patched-files/` 是改造后文件，`original-files/` 是官方 4.1.0.4 原版。

---

## 二、量化结果（实测，benchmark 忠实复现下单 SQL 序列）

### 单线程「完整下单」(addOrder + addHistory) 三模式对比

| 场景 | auto（改造前，逐条 autocommit） | txn（#1+#2 事务化） | batch（+#3 total 批量） | batch2（+#4 product 批量） |
|---|---|---|---|---|
| **3~5 商品/单** | 22 TPS / 45ms | 37 TPS / 27ms | 50 TPS / 20ms | **69 TPS / 14.5ms** |
| **10~20 商品/单** | 10 TPS / 99ms | 21 TPS / 48ms | ~32 TPS | **68 TPS / 14.7ms** |

- 小订单总提升 **↑3.1x**；大订单 **↑6.8x**
- **batch2 的 TPS 几乎不随商品数下降**：order_product 从 O(商品数) 次 INSERT 压成 O(1) 次

### #5 读缓存（country/zone）

| 查询 | 冷（直连 Aurora） | 热（Redis 命中） | 提速 |
|---|---|---|---|
| getCountry(223) | 2.32 ms | 0.73 ms | **3.2x** |
| getZone(3624) | 2.56 ms | 0.80 ms | **3.2x** |

一次下单地址校验约 4 次 country/zone 读，缓存后每单省 ~6.6ms 且不打 Aurora。

### 3 台集群压测（重要结论：瓶颈是串行往返，不是算力）

通过 internal ALB 打压测端点（真实 addOrder+addHistory），三种测法**一致收敛到 ~67-68 TPS**：

| 测法 | TPS |
|---|---|
| 单机 bench (batch2, 3商品) | 68 |
| 通过 ALB 压 3 台并发 (c50~c400) | 68（并发加大延迟暴涨，TPS 不升） |
| 本机多进程（隔离 ALB/网络） | 67 |

压测时观测：**后端 CPU 空闲 98%**，Aurora max_connections=2000 只用 600 且**全 `Sleep`**。
→ **瓶颈是单个下单请求内部的串行 DB 往返延迟**（每单 10+ 次串行 SQL × ~1ms 往返 + 每请求建连接/PHP 启动开销），
加机器/加并发都不会突破这个「单请求延迟」决定的上限。这与本项目组过往「cart.add 卡 700」是同一规律：
**CPU/DB/Redis 都不忙但 TPS 卡住 = 往返次数×延迟瓶颈，不是算力。**

> ⚠️ 说明：压测端点为裸 PHP（每请求新建连接、CLI 无 OPcache/连接池），
> 该 67 TPS 含明显的「连接建立 + 进程启动」开销，**不代表真实 php-fpm 环境的下单上限**（真实会更高）。
> 它准确说明的是：**在本测试脚手架下，瓶颈已从"写提交次数"转移到"串行往返/连接开销"，而非本次 5 项优化未生效**。

---

## 三、逻辑一致性 & 数据一致性审查（对比官方 4.1.0.4）

逐行核对结论：

1. **事务包裹（#1/#2）**：`addOrder`/`addHistory` 去掉事务语句后与原版**逐行一致**，内部 SQL 一字未改。
2. **批量 INSERT 字段核对**：order_product(10列)/order_option(7列)/order_total(6列) 的每一列类型转换
   （`(int)/(float)/escape`）与原版 `SET` 写法**逐列一致**。
3. **option 关联正确性**：Aurora `innodb_autoinc_lock_mode=2`，实测「单条多值 INSERT 内部自增 id 连续」
   （95015~95019），并用「有/无 option 交错」的混合订单验证 `firstId+idx` 关联全部正确。
   - MySQL 官方保证：mode 2 下行数已知的 "simple insert" 会一次性分配连续 id 块。并发下不同 INSERT 间交错，
     但**同一条 INSERT 内部连续**——本方案只依赖后者，安全。
   - 前提：order_product 表无触发器（已确认）。
4. **subscription 保留逐条**：有 subscription 才调 addSubscription，用推算的 order_product_id，与原版等价。
5. **事务嵌套安全**：全 catalog 代码库**无任何 `START TRANSACTION`/`COMMIT`/`autocommit`**——
   addHistory 内部调用的 total confirm / reward / coupon / subscription 等**都不自开事务**，
   不会隐式提交我的外层事务。把它们纳入订单事务反而**增强一致性**（要么全成功，要么全回滚）。

### ⚠️ 已知特性（与原版一致，非本次引入的缺陷）

- **缓存失效依赖 TTL**：admin 改 country/zone 时调 `cache->delete('country')`，但 Redis 引擎的 delete 是
  **精确删除单 key**，删不掉 `country.{md5}` / 我新增的 `country.info.*`。
  → OpenCart 原生 `getCountries` 缓存也是同样行为，**都靠 TTL（默认 3600s）自然过期**。
  本次改动**未引入比原生更差的一致性**。国家/地区极少变更，下单场景可接受。
- **空结果不缓存**：用 `empty($data)` 判断未命中，查询不存在的 id 会每次回源（缓存穿透）。
  与原版 `if (!$country_data)` 行为一致；下单的 id 必然存在，无实际影响。

---

## 四、文件清单

```
patched-files/     改造后的 3 个文件（order.php / country.php / zone.php）
original-files/    官方 4.1.0.4 原版（对比基线）
diffs/             unified diff（原版 → 改造版）
bench/             benchmark 脚本
  bench_writepath.php    仅 addOrder 写路径（auto vs txn）
  bench_fullorder.php    addOrder+addHistory（auto vs txn）
  bench_fullorder2.php   三模式（auto/txn/batch）
  bench_fullorder3.php   三模式（txn/batch/batch2）
  loadorder.php          压测端点（真实引擎调 addOrder+addHistory）
  loadorder2.php         压测端点 v2（持久连接实验）
patch-scripts/     用于把改动应用到原版的 Python 脚本
  patch_country_cache.py / patch_zone_cache.py / patch_product_batch.py
```

## 五、回滚

生产机上每次改动均留时间戳备份：`order.php.pretxn.*` / `.prehist.*` / `.prebatch.*` / `.preprodbatch.*`，
`country.php.precache.*` / `zone.php.precache.*`。`cp` 回即恢复。
