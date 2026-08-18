# OpenCart 购物车迁移到 Redis：减少 Aurora 压力

> 环境：AWS us-east-2 · OpenCart 4.1.0.4 · PHP 8.5 · Aurora MySQL 8.0 · ElastiCache Redis · 3×EC2 t3.small
> 时间：2026-08-18

## ⚠️ 重要：这是定制开发，不是 OpenCart 官方特性

OpenCart 官方**只对 Session 和 Cache 提供了可切换 Redis 的引擎抽象**（改配置即可，无需改代码）：

| 组件 | 官方配置项 | 官方自带 Redis 支持 | 迁 Redis 是否需改代码 |
|---|---|---|---|
| Session | `session_engine` | ✅ 有（`session/redis.php`） | 否，改配置即可 |
| Cache | `CACHE_ENGINE` | ✅ 有 | 否，改配置即可 |
| **购物车 Cart** | ❌ 无 | ❌ 无（硬编码 `oc_cart` 表） | **是，必须改 `cart.php` 源码** |

本改造新增的 `CART_ENGINE` 常量是**自定义开关**，只有在部署了本目录改造版 `cart.php`（含内联 `CartStorage`）后才生效。换回官方原版 `cart.php`，该常量无效。**升级 OpenCart 时官方会覆盖 `cart.php`，需重新合并本改动**（保留了 `cart.php.original` 供对比）。

## 背景与动机

OpenCart 默认把购物车条目存在 **`oc_cart` 表**（MySQL）。每次页面加载都会 `SELECT oc_cart`，构造函数还会 `DELETE` 过期匿名购物车，加购/改数量/删除都是 DB 写操作。

**购物车（尤其匿名用户的）是非关键交易数据**——即使偶发丢失，用户重新加购即可，不影响已下单的订单。因此把它从 Aurora 迁到 **Redis** 可以：
- 减少 Aurora 的读写压力（每次页面加载省掉 `SELECT oc_cart`，加购省掉 SELECT+INSERT）
- 购物车走内存，读写更快
- 借助 Redis TTL 自动过期，替代原来的"DELETE 过期车"定期清理

> ⚠️ **重要设计取舍**：购物车条目本身（product_id/quantity/option）搬到 Redis；但"根据 product_id 查商品详情/价格/库存"的查询**保持在 DB 不动**（那是商品主数据，本就该在 DB）。所以本改造减少的是"购物车条目的存取"这部分 DB 压力，不是全部。

## 改造原理

### OpenCart 购物车机制

`system/library/cart/cart.php` 的 `Cart` 类管理购物车，对 `oc_cart` 表有 6 处存取：

| 方法 | 原 DB 操作 |
|---|---|
| `__construct()` | DELETE 过期匿名车 + 登录时 2 条 UPDATE 迁移 session |
| `getProducts()` | SELECT 购物车条目 |
| `add()` | SELECT COUNT + INSERT / UPDATE |
| `update()` | UPDATE quantity |
| `remove()` | DELETE 单条 |
| `clear()` | DELETE 全部 |

购物车条目结构：`{cart_id, product_id, quantity, option, subscription_plan_id, override}`，按 `store_id + customer_id + session_id` 归属。

### Redis 数据结构

用 **Redis Hash** 存储：

```
key   = {CACHE_PREFIX}.cart.{store_id}.{customer_id}.{session_id}   (Hash, 带 TTL)
field = cart_id
value = json({product_id, quantity, option, subscription_plan_id, override, date_added})

自增 cart_id 计数器 = {CACHE_PREFIX}.cart_seq   (String, INCR)
```

- 复用 OpenCart 已有的 `CACHE_HOSTNAME` / `CACHE_PORT` / `CACHE_PREFIX`（即 ElastiCache，和 session/cache 同一个 Redis）
- key 带 TTL（= `config_session_expire`），到期自动删，无需定期清理
- `cart_id` 原本是 DB 自增主键，Redis 里用 `INCR` 计数器代替

## 实现

### 1. 新增 `CartStorage` 存储后端类

封装 Redis 的 list/find/add/update/remove/clear/mergeOnLogin，并带 **DB 降级**（引擎设为 db，或 Redis 连不上时，自动回退原生 SQL，绝不影响下单）。

引擎由常量 `CART_ENGINE` 控制：
```php
define('CART_ENGINE', 'redis');   // config.php + admin/config.php；未定义则默认 db
```

> ⚠️ **踩坑**：OpenCart 的 library autoloader 不会自动加载任意新文件。独立放 `cartstorage.php` 会报 `Class "...CartStorage" not found`。**解法：把 CartStorage 类直接内联到 `cart.php` 文件末尾**（同 namespace、同文件，PHP 一起加载，不依赖 autoload）。本目录 `cartstorage.php.standalone` 是独立版源码，实际部署时它被追加进 `cart.php`。

### 2. 改造 `cart.php` 的 6 处

每处都是 `if ($this->storage->usingRedis()) { ...Redis... return; } ...原DB逻辑...` 的模式，保留 DB 路径作为降级。

> ⚠️ **踩坑**：`getProducts()` 里除了主 SELECT，后面还有一处 `foreach ($cart_query->rows as $cart_2)`（算同商品不同选项的总量）。改用统一变量 `$cart_rows` 后，这处也必须同步改，否则 Redis 分支下 `$cart_query` 未定义会报 `Undefined variable` warning。

## 部署步骤

```bash
# 1. 把改造后的 cart.php（含内联 CartStorage）部署到所有 EC2
sudo cp cart.php /var/www/html/system/library/cart/cart.php
php -l /var/www/html/system/library/cart/cart.php   # 语法检查

# 2. config.php + admin/config.php 加引擎开关
echo "define('CART_ENGINE', 'redis');" >> /var/www/html/config.php
echo "define('CART_ENGINE', 'redis');" >> /var/www/html/admin/config.php

# 3. 重启
sudo systemctl restart php-fpm httpd
```

（前提：Redis 的 `CACHE_HOSTNAME/PORT/PREFIX` 已配好，phpredis 扩展已装——这些在 session 迁移时已完成）

## 验证结果

加购 product_id=43 后：

```
oc_cart 表增量 = 0                              ← 数据库零写入 ✅
Redis 出现 key: oc_.cart.0.0.<session>  TTL=86399
  cart_id=1 => {"product_id":43,"quantity":1,"option":"[]",...}
购物车页正常读出商品 ✅
```

多实例一致性（通过 ALB 反复请求，被分发到不同 EC2）：购物车内容一致，无报错，`oc_cart` 增量始终为 0。

## 收益与边界

**收益**：购物车相关的 DB 读写归零，Aurora 压力下降；多实例天然共享同一 Redis 购物车（负载均衡切实例购物车不丢）。

**边界/注意**：
- 购物车在 Redis，**Redis 若整体故障且未持久化，未下单的购物车会丢**——但这是可接受的（非关键数据），且代码有 DB 降级
- `oc_cart` 表保留（降级路径 + 历史数据），不删
- 已提交的**订单**（`oc_order`）仍在 Aurora，不受影响——只有"未结账的购物车"在 Redis
- 回滚：把 `CART_ENGINE` 改为 `db`（或删除该 define），重启即恢复原生 DB 购物车；每台有 `cart.php.predredis.<ts>` 备份

## 文件说明

- `cart.php` — 改造后的完整文件（含内联 CartStorage 类），可直接部署
- `cart.php.original` — 官方原版（对比用）
- `cartstorage.php.standalone` — CartStorage 类独立源码（阅读用；实际内联进 cart.php）
