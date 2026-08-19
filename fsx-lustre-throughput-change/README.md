# FSx for Lustre 在线变配吞吐（PerUnitStorageThroughput）对运行中 IO 的影响

**测试日期**：2026-08-01
**文件系统**：FSx for Lustre PERSISTENT_2，4.8 TiB，us-east-2b（脱敏 FS-ID）
**客户端**：i7i.4xlarge（16 vCPU），Amazon Linux 2023，lustre-client 2.15.6
**场景**：在 24 小时 fio 高压压测运行过程中，在线修改 `PerUnitStorageThroughput` 125 → 250 MBps/TiB，实测对运行中 IO 的影响。

---

## 结论速览（TL;DR）

- **在线变配吞吐会导致 OST 短暂断连约 90–110 秒**（后台替换文件服务器）。
- **报错信息**：dmesg 出现 `LustreError 11-0: ... operation ost_read ... failed: rc = -19`（ENODEV）+ `Connection to OSTxxxx was lost`。
- **应用层表现**：**不是直接 IO 失败退出，而是"IO 挂起等待恢复"**。Lustre recovery 机制把在途操作挂起，OST 重连后自动 replay/继续。fio 进程数从 17 短暂掉到 0–1（线程阻塞），恢复后回到 17，**压测主进程全程存活，无需人工干预**。
- **官方限制（已查 User Guide 证实）**：
  - 变配期间文件系统「最长 1 小时不可用」（实测本次仅约 100 秒 OST 抖动，远小于上限）。
  - 两次吞吐变配之间必须间隔 **6 小时**（`whichever is longer`：6h 或优化完成）。
  - PERSISTENT_2 合法档位：125 / 250 / 500 / 1000 MBps/TiB。
- **生产启示**：在线变配应安排在业务低峰；应用需能容忍约 1–2 分钟的 IO 停顿（挂起而非报错）。不能假设变配对在线业务零影响。

---

## 双向验证：升档 125→250 与降档 250→125 行为一致（2026-08-01 两次实测）

同一 FS 做了两次变配，**升档和降档都会触发 OST 断连 + rc=-19 报错，断连约 1.5–2 分钟，Lustre recovery 自愈**：

| 项 | 升档 125→250 | 降档 250→125 |
|---|---|---|
| 发起时刻 (UTC) | 10:19:38 | 16:20:17 |
| 断连开始 | 10:20:41（发起后 ~63s） | 16:21:31（发起后 ~74s） |
| 恢复完成 | ~10:22:37 | 16:23:39–40 |
| 断连时长 | 约 90–110s | 约 2 分钟 |
| 报错 | `rc = -19` + `Connection lost` | 同 |
| 应用影响 | 在途 IO 挂起等 recovery（透明） | 同 |
| OST 迁移 | — | **实测 OST0000 从 IP .210 → .7**（换文件服务器印证） |

降档 250→125 的 dmesg 原文（含 `Connection restored` 恢复记录）：
```
16:21:31  LustreError 11-0: zmuqnb4v-OST0000-osc-xxxx: operation ost_read to node <OST-IP-A>@tcp failed: rc = -19
16:21:31  Connection to zmuqnb4v-OST0000 (at <OST-IP-A>@tcp) was lost; in progress operations will wait for recovery to complete
16:23:15  Connection restored to <OST-IP-B>@tcp (OST0003)
16:23:30  Connection restored to <OST-IP-A>@tcp (OST0001)
16:23:39  Connection restored ... (OST0002)
16:23:40  OST0003 lost again → 立即 restored
```

**教训**：变配 IO 影响要**事后回查 dmesg**（历史留痕可靠），不能只靠实时 `ost_server_uuid` 抽查——断连窗口仅约 2 分钟，实时抽查极易错过，但 dmesg 一定有记录。

---

## 报错信息（dmesg 原文）

```
[Sat Aug  1 10:20:41 2026] LustreError: 11-0: zmuqnb4v-OST0002-osc-xxxx: operation ost_read to node <OST-IP>@tcp failed: rc = -19
[Sat Aug  1 10:20:41 2026] Lustre: zmuqnb4v-OST0002-osc-xxxx: Connection to zmuqnb4v-OST0002 (at <OST-IP>@tcp) was lost; in progress operations using this service will wait for recovery to complete
```

**关键解读**：
- `rc = -19` = `-ENODEV`：OST 对应的文件服务器正在被 FSx 后台替换，设备暂时不存在。
- `in progress operations ... will wait for recovery to complete`：**这是 Lustre 的保护机制**——在途 IO 不会立刻失败，而是挂起等待重连恢复。这解释了为什么应用没崩溃。

---

## 时间线（OST 连接状态，客户端 `lctl get_param osc.*.ost_server_uuid`）

变配发起：`2026-08-01T10:19:38Z`（125 → 250）

| 时刻 (UTC) | 4×OST 状态 | fio 进程 | 说明 |
|---|---|---|---|
| 10:20:16 | 全 FULL | 17 | 变配刚发起，尚正常 |
| 10:20:41 | (dmesg) OST0002 Connection lost, rc=-19 | — | **断连开始** |
| 10:20:56 | 全 CONNECTING | 17 | 4 OST 全部进入重连 |
| 10:21:56 | 2×DISCONN + 2×CONNECTING | 17 | 断连最严重点 |
| 10:22:37 | 2×CONNECTING + 2×FULL | 17 | 开始恢复 |
| 10:22:57 | **全 FULL（恢复）** | **1** | OST 全恢复；fio 线程因刚才阻塞掉到 1 |
| 10:23:57 | 全 FULL | 17 | fio 恢复到满并发 |
| 10:28:57 / 10:29:17 | 全 FULL | 0 | fio 在场景切换间隙（正常） |
| 10:29:37+ | 全 FULL | 17 | 稳定 |

**OST 断连持续时间**：约 10:20:41 → 10:22:37，**约 90–110 秒**。

> 注：AWS 侧 `AdministrativeActions` 在 OST 恢复后仍显示 `State=UPDATING / IN_PROGRESS`——即"OST 恢复"只是变配第一阶段，完整换服务器 + 新吞吐生效还需更长时间。

---

## 应用（fio）表现

- 压测脚本：16 并发 fio，覆盖 seq/rand/mixed/metadata 多场景轮转。
- 变配期间 fio 进程数：17 → （断连期仍 17，线程阻塞在 IO 等待）→ 恢复瞬间掉到 1 → 1 分钟内回到 17。
- **压测主进程（`lustre_stress_24h.sh`）全程存活**，未崩溃、未退出。
- 手动验证：断连恢复后 `echo > /fsx/.../test && cat && rm` 读写正常，`lfs df` 4 OST + 2 MDT 全部在线。

---

## 吞吐前后对照（burst 耗尽 + 变配）

同一 4.8 TiB FS，24h 压测各轮顺序读写（fio 1M，16 并发，direct=1）：

| 轮次 | 顺序写 | 顺序读 | 状态 |
|---|---|---|---|
| Round 1–2（刚启动） | 1671 / 1655 MB/s | 2003 MB/s | **burst 额度充足** |
| Round 3+（持续高压后） | ~648–656 MB/s | ~596–601 MB/s | **burst 耗尽，回落磁盘基线** |

**磁盘基线验证**：PERSISTENT-125 磁盘吞吐 baseline = 125 MBps/TiB × 4.8 TiB = **600 MBps** ≈ 实测 648/599 MB/s。
（官方：写 & 非缓存读性能 = min(网络吞吐, 磁盘吞吐)；burst 走 network I/O credit 机制，额度耗尽回落基线。）

变配到 250 MBps/TiB 后，磁盘基线预期升到 1200 MBps（待变配完成后验证，另附）。

---

## 官方文档依据（FSx for Lustre User Guide）

1. **变配不可用窗口**："Your file system will be unavailable for up to an hour during throughput capacity scaling."（后台 switches out the file servers）
2. **6 小时最小间隔**："You can't make further throughput capacity changes until 6 hours after the last request, or until the throughput optimization process has completed, whichever is longer."
3. **合法档位**：Persistent 2 = 125/250/500/1000 MBps/TiB。
4. **burst 机制**："FSx for Lustre file systems provide burst read throughput using a network I/O credit mechanism..."

---

## 监控方法（供复现）

- OST 连接状态（权威判据）：`lctl get_param -n osc.*.ost_server_uuid`（FULL/IDLE=正常，DISCONN/CONNECTING=断连中）。
- 报错：`dmesg -T | grep -iE 'LustreError|Connection|rc = -|recovery'`。
- 变配进度（AWS 侧）：`aws fsx describe-file-systems ... --query 'FileSystems[0].AdministrativeActions'`。

### ⚠️ 监控脚本已知缺陷（诚实记录）

本次用的 `throughput_change_watch.sh` 里，用「在压测 workdir 写探测文件 + 10s 超时」来判断 IO 是否可用，结果**全程误报 `RW_FAIL`**（即便 OST 全 FULL、IO 实际正常时也报）。原因：探测文件与满负荷 fio 争抢同一目录 + 10s 超时在高压下不够。
**教训**：IO 健康探测应写到独立轻负载路径、超时给足（30s+），或直接以 `ost_server_uuid` 连接状态 + dmesg 为准，不要用"在高压目录里争抢写"来判断可用性。`RW_FAIL` 本次应忽略，以 dmesg + 手动测试 + lfs df 为准。

---

## 补充：客户端 retry/timeout 参数对变配断连的影响（2026-08-19，3 组对照实测）

上面的测试测的是**服务端变配对 IO 的影响**，没测**客户端 retry/timeout 参数**。本节补上——用 3 套独立系统对照不同客户端 Adaptive Timeout 参数。

### Lustre 客户端 timeout/retry 机制
Lustre 客户端**不用** NFS 的 `timeo`/`retrans`/`hard`/`soft`，用 **Adaptive Timeouts (AT)**（PTLRPC 层）。关键参数（`lctl get/set_param`）：

| 参数 | 作用 | 默认 |
|---|---|---|
| `at_min` | RPC 超时**下限**秒数（至少等这么久才判超时重发）| 0 |
| `at_max` | 超时**上限**；**设 0 = 关闭 AT，改用固定 `timeout`** | 600 |
| `timeout`(obd_timeout) | 关 AT 时的固定 RPC 超时基值 | 100 |

**重要**：这些只控制"单个 RPC 多久判超时后重发"，**不控制"多久彻底放弃报错"**。Lustre 客户端断连时默认**无限期挂起等 recovery**（不像 NFS soft 会 retrans 若干次后返回 EIO），这就是应用"IO 挂起"而非"报错退出"的原因。

### 测试设计
3 套完全独立系统（避开 6 小时变配间隔，同时各变配一次）：每套 = 最小 FSx Lustre（PERSISTENT_2, 1.2TiB, 125 MBps/TiB, 同 AZ）+ 1 台 c7i.2xlarge（lustre-client 2.15.6 + fio randrw 70/30）。变配前各设一组参数：

| 组 | at_min/at_max/timeout | 含义 |
|---|---|---|
| g1 | 0/600/100 | 默认基线 |
| g2 | 5/30/100 | 激进短超时 |
| g3 | 0/**0**/50 | 关闭 AT + 固定短超时 |

同时变配 125→250 触发 OST 断连。

### 结果（dmesg 精确时间戳）

| 组 | 参数 | 断连开始 | 恢复 | 断连时长 | fio 存活 | IO error |
|---|---|---|---|---|---|---|
| g1 默认 | 0/600/100 | 09:04:12 | 09:05:07 | **~55s** | ✅ | 0 |
| g2 激进短 | 5/30/100 | 09:04:11 | 09:05:18 | **~67s** | ✅ | 0 |
| g3 关AT固定 | 0/0/50 | 09:04:32 | 09:05:38 | **~66s** | ✅ | 0 |

OST 状态轮询印证：+26s 时 g1/g2 已 CONNECTING，**g3 仍 FULL**；+86s 时 g1/g2 已恢复，**g3 才 DISCONN**。

### 分析结论
1. **客户端参数不改变"IO 挂起等 recovery + 自愈"本质**——三组 fio 全存活、零 error。无论怎么调 AT，都不会让应用在这种 ~1 分钟短暂断连中失败（Lustre 默认死等 recovery）。
2. **关闭 AT（g3, at_max=0）反而让断连检测更晚**——晚约 20s（09:04:32 vs 09:04:11）。AT 能更快感知异常，关了变迟钝。
3. **激进短超时（g2）不加速恢复**——67s 比默认 55s 还慢。恢复速度由**服务端 rebalance 决定**，客户端调小超时只增重发、无益。
4. **建议保持默认 AT 参数最稳**。不能容忍 IO 挂起 1 分钟的解法不是调客户端超时（改不了"死等"本质），而是变配避峰 + 应用层重试/降级。

---

*生成：2026-08-01（服务端变配影响）+ 2026-08-19（客户端参数 3 组对照）。*
