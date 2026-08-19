# Lustre 客户端 retry/timeout 参数对变配断连的影响（3 组对照实测）

**测试日期**：2026-08-19
**背景**：补上 `fsx-lustre-throughput-change`（2026-08-01）缺的一环——那次只测了**服务端变配对 IO 的影响**（OST 断连 90-110s，IO 挂起等 recovery），**没测客户端 retry/timeout 参数**。本次用 3 套独立系统对照测试不同客户端 Adaptive Timeout 参数。

> ⚠️ 所有敏感值（账号、资源 ID、IP）已脱敏/占位。

---

## Lustre 客户端 timeout/retry 机制（先厘清概念）

Lustre 客户端**不用** NFS 的 `timeo`/`retrans`/`hard`/`soft` 那套。它用 **Adaptive Timeouts (AT)**（PTLRPC 层），关键客户端可调参数（`lctl get/set_param`）：

| 参数 | 作用 | 默认 |
|---|---|---|
| `at_min` | RPC 超时**下限**秒数；客户端至少等这么久才判超时重发（避免服务器忙时激进重发）| 0 |
| `at_max` | RPC 超时**上限**；**设 0 = 关闭自适应超时，改用固定 `timeout`** | 600 |
| `timeout`(obd_timeout) | 关 AT 时的固定 RPC 超时基值 | 100 |

**重要**：这些控制的是**单个 RPC 多久判超时后重发**，**不是"多久彻底放弃报错"**。Lustre 客户端在 OST 断连时的默认行为是**无限期挂起等 recovery**（不像 NFS soft 会 retrans 若干次后返回 EIO）——这解释了为何应用是"IO 挂起"而非"报错退出"。

---

## 测试设计

- **3 套完全独立系统**（避开"6 小时变配间隔"限制，3 套同时各变配一次）：
  - 每套 = 1 个最小 FSx Lustre（PERSISTENT_2, 1.2TiB, 125 MBps/TiB, 同 AZ）+ 1 台 c7i.2xlarge（lustre-client 2.15.6 + fio）
- **3 组客户端参数**（挂载后 `lctl set_param`，变配前设好）：

| 组 | at_min | at_max | timeout | 含义 |
|---|---|---|---|---|
| **g1** | 0 | 600 | 100 | 默认基线 |
| **g2** | 5 | 30 | 100 | 激进短超时（缩小 AT 范围）|
| **g3** | 0 | **0** | 50 | 关闭 AT + 固定短超时 50 |

- 每台后台跑 fio（randrw 70/30, bs64k, numjobs4, iodepth32, direct, time_based）覆盖变配断连窗口。
- **同时**对 3 套 Lustre 变配 `PerUnitStorageThroughput` 125→250，触发 OST 断连，对比 3 组行为。

---

## 实测结果（dmesg 精确时间戳）

变配发起：约 09:03:54 UTC（三套同时）

| 组 | 参数 | 断连开始 | 恢复 | 断连时长 | 首报错操作 | fio 存活 | IO error |
|---|---|---|---|---|---|---|---|
| **g1** 默认 | 0/600/100 | 09:04:12 | 09:05:07 | **~55s** | ldlm_enqueue | ✅ | 0 |
| **g2** 激进短 | 5/30/100 | 09:04:11 | 09:05:18 | **~67s** | ldlm_enqueue | ✅ | 0 |
| **g3** 关AT固定 | 0/0/50 | 09:04:32 | 09:05:38 | **~66s** | ost_read | ✅ | 0 |

OST 状态轮询（`lctl get_param osc.*.ost_server_uuid`）也印证：
- +26s：g1/g2 已 CONNECTING（在重连），**g3 仍 FULL**（还没检测到断连）
- +86s：g1/g2 已恢复 FULL，**g3 才 DISCONN**

---

## 分析结论

### 1. 客户端参数不改变"IO 挂起等 recovery + 自愈"的本质行为
**三组参数下，应用（fio）表现一致**：OST 断连期间 IO 挂起（进程不掉、不报错），OST 重连后自动 replay 继续，**全程 fio 存活、零 IO error**。
→ **无论怎么调 at_min/at_max/timeout，都不会让应用在这种短暂断连（~1 分钟）中失败**。Lustre 默认就是"死等 recovery"，客户端参数只影响"多久判 RPC 超时重发"，不影响"放弃与否"。

### 2. 关闭自适应超时（g3, at_max=0）会让客户端**更晚检测到断连**
- g3 断连开始比 g1/g2 **晚约 20 秒**（09:04:32 vs 09:04:11-12），OST 状态也明显滞后（+86s 才 DISCONN，而 g1/g2 +86s 已恢复）。
- 原因（推测，待进一步验证）：关 AT 后用固定 timeout，客户端要等固定超时值到期才判 RPC 失败、才进入重连流程；而 AT 机制能根据网络/服务时间更快感知异常。**关 AT 反而让故障检测变迟钝。**

### 3. 激进短超时（g2, at_max=30）没带来更快恢复，反而略慢
- g2 断连时长 67s，比默认 g1 的 55s 还长一点。
- 说明**缩小 AT 上限不能加速 FSx 后台换服务器的 recovery**——恢复速度由服务端 rebalance 决定，客户端超时调小只是更频繁重发 RPC，对总恢复时间无益（甚至因频繁重发有轻微负面）。

### 总体建议
- **对"变配/故障导致的 OST 短暂断连"，保持客户端默认 AT 参数（at_min=0, at_max=600）即可**——默认行为最稳，检测快、自愈可靠、应用无感（仅 IO 挂起 ~1 分钟）。
- **不建议关闭 AT（at_max=0）**：会让断连检测变慢（本次晚 20s），无收益。
- **不建议盲目调小 at_max**：不加速恢复（恢复由服务端决定），反增重发。
- 若应用**不能容忍 IO 挂起 1 分钟**，真正的解法不是调客户端超时（改不了"死等"本质），而是：①变配安排在业务低峰；②应用层加超时/重试/降级逻辑；③关键路径考虑多副本/多路径。

---

## 复现命令

```bash
# 挂载
mount -t lustre -o relatime,flock <DNS>@tcp:/<mountname> /fsx
# 设客户端 AT 参数
lctl set_param at_min=<v> at_max=<v> timeout=<v>
lctl get_param at_min at_max timeout   # 确认生效
# 变配触发断连
aws fsx update-file-system --file-system-id <FSID> \
  --lustre-configuration '{"PerUnitStorageThroughput":250}'
# 观察(权威判据)
lctl get_param -n osc.*.ost_server_uuid       # FULL/IDLE=正常, DISCONN/CONNECTING=断连
dmesg -T | grep -iE "Connection to|restored|rc = -19|recovery"
```

> 断连窗口仅约 1 分钟，实时抽查易错过，**以 dmesg 时间戳为准**（历史留痕可靠）。
