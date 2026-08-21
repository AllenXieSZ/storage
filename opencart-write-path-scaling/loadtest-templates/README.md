# OpenCart 压测脚本模板 (Load Test Templates)

这些是给 OpenCart 三层架构(ALB → EC2 app → Aurora)做压测时用的脚本模板，
覆盖三类工具/角色：**ab（冒烟）**、**wrk（主力高并发）**、**Python 脚本（混合场景/阶梯爬坡）**。

> ⚠️ 所有脚本已把 host/密码改为**环境变量**，用前先 `export`。切勿把真实凭据提交回仓库。

---

## 三类工具/角色对比

| 维度 | ab (ApacheBench) | wrk | loadgen (压测机 + 脚本) |
|---|---|---|---|
| 本质 | 具体工具 | 具体工具 | 角色/机器(其上跑 wrk 或 py 脚本) |
| 并发模型 | 单线程阻塞 | 多线程 + epoll 事件驱动 | 取决于所跑工具 |
| 发压能力 | 弱(高并发时自成瓶颈) | 强(单机数十万 QPS) | 取决于工具 + 机型 + 台数 |
| 多接口/复杂场景 | ❌ 单 URL | ✅ Lua 脚本 | ✅ 脚本任意编排 |
| POST/自定义请求 | 勉强(-p file) | ✅ Lua 灵活 | ✅ |
| 上手难度 | 极低 | 中(Lua) | 中 |
| 适用场景 | 单 URL 快速冒烟 | 高并发真实压测 | 大规模/多机分布式压测 |

**一句话**：ab 冒烟、wrk 主力、loadgen 是承载 wrk/脚本的机器阵列。

> 教训(踩过的坑)：**Python threading + requests 做压测不可信**——GIL 下单机发压能力弱，
> 测出的"拐点"往往是压测客户端自己的上限，不是后端。真正冲高 TPS 用 **wrk**（C，多路复用）。
> Python 脚本适合做**混合业务场景比率 / 逐级爬坡找拐点**这类"编排型"压测，不追求极限发压。

---

## 文件清单

| 文件 | 工具 | 用途 |
|---|---|---|
| `ab_smoke.sh`         | ab   | 单 URL 快速冒烟(直连 localhost 排除网络，测单机后端极限) |
| `wrk_browse.lua`      | wrk  | 读路径压测(首页/分类/商品页随机 GET) |
| `wrk_cart_add.lua`    | wrk  | 写路径压测(cart.add POST，冲 5000 TPS 主力) |
| `wrk_fastorder.lua`   | wrk  | 一键下单接口(fastorder POST，端到端下单 TPS) |
| `run_wrk.sh`          | wrk  | wrk 启动封装(参数化 线程/连接/时长) |
| `loadtest_ramp.py`    | py   | 阶梯并发爬坡，自动找拐点(成功率<95% 或 P95>8s 停) |
| `loadtest_mixed.py`   | py   | 混合负载(browse 85% / order 10% / admin 5%) 按比率打 |
| `loadtest_seed_products.py` | py | 灌测试商品数据到 Aurora(压测前准备数据) |

---

## 快速开始

```bash
# 0. 公共环境变量
export TARGET="http://your-alb-dns.us-east-2.elb.amazonaws.com"   # 或 CloudFront 域名
export BASE="$TARGET"

# 1. ab 冒烟(单 URL)
./ab_smoke.sh "$TARGET/" 10000 100        # 1万请求, 并发100

# 2. wrk 读路径(高并发)
./run_wrk.sh 8 400 60s wrk_browse.lua       # 8线程 400连接 压60秒

# 3. wrk 写路径(cart.add, 冲 TPS)
./run_wrk.sh 12 600 300s wrk_cart_add.lua    # 12线程 600连接 压5分钟

# 4. Python 阶梯爬坡(找拐点)
python3 loadtest_ramp.py 15 20,50,100,200,400

# 5. Python 混合负载
python3 loadtest_mixed.py 100 20            # 100并发 x 每线程20迭代
```

## 大规模分布式发压(冲 5000+ TPS)

单台压测机发压能力有限（走公网/CloudFront 更甚）。冲 5000 TPS 时用**多台压测机同时打**：

```bash
# 每台压测机(如 6 台 c7i.2xlarge)各跑:
./run_wrk.sh 12 600 300s wrk_cart_add.lua   # 单台 c600, 6台 = c3600 总并发
# 汇总各台 Requests/sec 得到总 TPS
```

> 实测经验(见上层 README)：3 台后端被 2400 并发瞬间打爆会触发**冷启动死锁**
> (延迟飙升→吞吐下降→基于吞吐的扩容触发不了)。解法：**先手动预扩 ASG**，或**逐步加压**。
