# FSx for Lustre 客户端网络延迟耐受性测试（AWS FIS 故障注入）

**测试日期**：2026-08-02
**文件系统**：FSx for Lustre PERSISTENT_2，4.8 TiB，us-east-2b（脱敏 FS-ID）
**客户端**：i7i.4xlarge（16 vCPU），Amazon Linux 2023，lustre-client 2.15.6，网卡 `enp39s0`
**方法**：AWS Fault Injection Service（FIS），`AWSFIS-Run-Network-Latency` SSM 文档，对客户端网卡递增注入网络延迟。全程有 24h fio 高压压测 + PCC 缓存同时运行。

---

## 结论速览（TL;DR）

- **Lustre 对网络延迟极其宽容**：200–500ms 延迟下**吞吐完全无损、零断连**。
- **延迟拐点 ≈ 1000ms**：从 1000ms 开始触发 OST 数据 RPC（o3）`slow reply timed out` + OST `Connection lost`，但**都在约 1 秒内自动 restored**。
- **即使 2000ms 也没崩溃**：全程 **0 eviction**，每次断连秒级自愈，压测/PCC 全程存活，故障结束后 OST 立即全部 FULL。
- **根因**：Lustre 用异步 RPC 流水线（max_rpcs_in_flight 并发）吸收单次延迟；RPC 超时用 **adaptive timeout**（实测 deadline 约 26–70 秒），远大于注入延迟，所以延迟只让个别 RPC 触线、不会大面积失败。
- **生产启示**：跨 AZ（通常 <2ms）乃至网络轻度劣化（几百 ms）对 Lustre 训练吞吐几乎无威胁。真正危险的是**丢包/断链**（直接断 TCP），而非延迟。

---

## 实验梯度与结果

| 延迟 | 时长 | OST 断连 | 数据RPC超时(o3) | Eviction | Lustre 反应 |
|---|---|---|---|---|---|
| 200ms | 60/90/120s | 无 | 无 | 无 | 完全无感，吞吐不掉（seq 2030/2009 MB/s @250档） |
| 500ms | 120s | 无 | 无 | 无 | 仍稳，无新超时 |
| **1000ms** | 120s | **首现**(OSTx) | **首现 o3 超时** | 无 | **拐点**：超时+断连，~1s 内 restored |
| 2000ms | 120s | 更频繁(反复) | 持续 | 无 | 断连-重连循环，全部自愈 |

> 注：FIS `AWSFIS-Run-Network-Latency` 的 `DurationSeconds` 最小为 60 秒（60–43200），无法做 <60s 的短注入。首轮做了 60/90/120s @200ms，第二轮做 120s @500/1000/2000ms 找拐点。

---

## 关键证据（dmesg，脱敏）

### 200–500ms：无任何 Lustre 错误
OST 全程 FULL；fio 吞吐不变；dmesg 无新增超时。

### 1000ms：拐点，首次数据 RPC 超时 + OST 断连
```
02:52:01  Lustre: ptlrpc_expire_one_request() @@@ Request sent has timed out for slow reply:
          req@... o3->zmuqnb4v-OSTxxxx-osc-...@<OST-IP>@tcp:6/4 ... dl <deadline> ... rc 0/-1
02:52:01  Lustre: zmuqnb4v-OSTxxxx-osc-...: Connection to zmuqnb4v-OSTxxxx (at <OST-IP>@tcp) was lost;
          in progress operations using this service will wait for recovery to complete
02:52:02  Lustre: zmuqnb4v-OSTxxxx-osc-...: Connection restored to <OST-IP>@tcp
```
- `o3` = OST 数据读写 RPC（区别于 `o400` 心跳 RPC）。
- 断连到恢复约 1 秒。

### 2000ms：断连-重连更频繁，但仍无 eviction
```
02:53:38  slow reply timed out (o3, OSTxxxx)
02:53:38  Connection to OSTxxxx was lost → 02:53:38 Connection restored
02:53:39  Connection to OSTyyyy was lost → 02:53:39 Connection restored
```
- 反复断连-秒级重连，`evict` 计数全程 **0**。

---

## 为什么 Lustre 抗延迟（机制）

1. **异步 RPC 流水线**：客户端可并发多个在途 RPC（`osc.*.max_rpcs_in_flight`），单次 RPC 多几百 ms 延迟被并发窗口吸收，大块顺序吞吐几乎不受影响。
2. **Adaptive Timeout**：实测 slow-reply 的 deadline 约 26–70 秒，Lustre 会根据网络状况动态放宽超时。注入的 200–2000ms 远小于该阈值，只让少数 RPC 触线。
3. **Recovery 机制**：`Connection lost` 后在途操作被**挂起等待 recovery**（而非报错），重连成功即 replay，对应用透明。

---

## 复现方法

前置：客户端 SSM Agent Online + EC2 instance profile 有 SSM 权限 + FIS role（信任 fis.amazonaws.com + ssm:SendCommand 权限）。

关键坑：
- **网卡名**：本机是 `enp39s0` 不是 `eth0`，FIS 文档 `Interface` 参数必须显式指定，否则注入到不存在网卡等于无效。
- **最小时长 60s**：`AWSFIS-Run-Network-Latency` 的 DurationSeconds ≥ 60。

FIS 实验模板核心（脱敏）：
```json
{
  "actions": {"netLatency": {
    "actionId": "aws:ssm:send-command",
    "parameters": {
      "documentArn": "arn:aws:ssm:us-east-2::document/AWSFIS-Run-Network-Latency",
      "documentParameters": "{\"Interface\":\"enp39s0\",\"DelayMilliseconds\":\"1000\",\"DurationSeconds\":\"120\",\"InstallDependencies\":\"True\"}",
      "duration": "PT2M"
    },
    "targets": {"Instances": "fioClient"}
  }},
  "targets": {"fioClient": {"resourceType":"aws:ec2:instance","resourceArns":["arn:aws:ec2:us-east-2:<ACCOUNT>:instance/<INSTANCE-ID>"],"selectionMode":"ALL"}}
}
```

监控（客户端侧，权威判据）：
```bash
lctl get_param -n osc.*.ost_server_uuid    # FULL/IDLE=通, DISCONN=断
dmesg -T | grep -iE 'slow reply|Connection.*(lost|restored)|evict|o3->'
tc qdisc show dev enp39s0 | grep netem     # 确认 FIS 注入的 netem 生效
```

---

---

## 第二/三轮：丢包 + 端口黑洞，直至打出 eviction（2026-08-02）

在延迟测试基础上继续加码：丢包（`AWSFIS-Run-Network-Packet-Loss`）与 TCP 988 端口黑洞（`AWSFIS-Run-Network-Blackhole-Port`，Lustre LNet 默认端口）。

### 完整故障耐受性全谱

| 故障 | 强度 | OST断连 | MGS/MDT断连 | /fsx卡住 | Eviction | 应用影响 |
|---|---|---|---|---|---|---|
| 延迟 | 200-500ms | 无 | 无 | 无 | 无 | 无感，吞吐不掉 |
| 延迟 | 1000ms | 秒级 | 无 | 无 | 无 | 拐点：o3数据RPC超时，秒级自愈 |
| 延迟 | 2000ms | 反复秒级 | 无 | 无 | 无 | 自愈 |
| 丢包 | 10-30% | 无 | 无 | 无 | 无 | TCP重传吸收，吞吐略降 |
| 丢包 | 50% | o4写RPC超时+断连 | 无 | 无 | 无 | 秒级自愈 |
| 黑洞988 | 90s | 多OST CONNECTING | ✅MGS断 | ✅ | 无 | IO挂起，恢复后自愈 |
| **黑洞988** | **360s(6min)** | 全断 | ✅MGS+MDT全断 | ✅ | ✅ **evict** | **在途IO失败，需重连** |

### 关键拐点

1. **延迟拐点 ~1000ms**：<1000ms 完全无感；1000ms 起触发 o3 数据 RPC `slow reply timed out`。
2. **丢包拐点 ~50%**：10-30% 靠 TCP 重传吸收；50% 起触发 o4 写 RPC 超时 + OST 秒级断连重连。
3. **eviction 临界值：介于 90s 与 360s 失联之间**（结合 `obd_timeout=100s` + recovery 窗口，实际约 100-300s）。

### eviction 证据（6 分钟黑洞，脱敏）

```
03:27:47  LustreError 167-0: MDT0001-mdc: This client was evicted by MDT0001; in progress operations will fail
03:27:57  LustreError 167-0: OST0002-osc: This client was evicted by OST0002
03:28:12  Evicted from MGS after server handle changed 0x...db6a -> 0x...4b19
03:28:12  LustreError 167-0: MDT0000-mdc: This client was evicted by MDT0000
```
- 6 分钟失联后，服务端（MDT0000/MDT0001/OST0002/MGS）全部驱逐该客户端；`server handle changed` = 服务端已清客户端状态。
- 黑洞结束后客户端立即重连、全部 `Connection restored`、`/fsx` 恢复、压测/PCC 存活。

### 关键区别：eviction vs 挂起

- **短时故障（延迟/丢包/短黑洞）**：`in progress operations will WAIT for recovery` —— IO **挂起**，网络恢复即续跑，对应用透明。
- **eviction（长黑洞）**：`in progress operations will FAIL` —— 被驱逐时**在途 IO 真的失败**，未提交脏数据可能丢失，客户端需重新建立连接。

### 关键参数（客户端观测）

- `at_max=600`（adaptive timeout 上限 600s），`obd_timeout=100`（基础 100s）。
- 这解释了为何 Lustre 对延迟/丢包极宽容：自适应超时可拉到 600s，短故障远够不着。

## 生产启示（6PB AI 训练）

- **Lustre 能扛住短时（<~2min）网络分区**：靠 recovery 挂起 IO，恢复即续跑，对应用透明。
- **网络分区 >~5min 会触发 eviction**：被驱逐时在途 IO 失败，训练可能报错——**这是 AI 训练必须做 checkpoint 的直接原因**（长网络分区后靠 checkpoint 恢复，不丢进度）。
- **可调**：网络不稳环境可调大服务端 recovery timeout / obd_timeout 放宽 eviction 阈值。
- **延迟/丢包威胁小，长时链路中断（分区）才是真风险**。

## 复现 —— 丢包/黑洞

```
# 丢包
documentArn: arn:aws:ssm:us-east-2::document/AWSFIS-Run-Network-Packet-Loss
documentParameters: {"Interface":"enp39s0","LossPercent":"50","DurationSeconds":"120","InstallDependencies":"True"}

# 端口黑洞(切断 Lustre 数据面)
documentArn: arn:aws:ssm:us-east-2::document/AWSFIS-Run-Network-Blackhole-Port
documentParameters: {"Protocol":"tcp","Port":"988","TrafficType":"egress","DurationSeconds":"360","InstallDependencies":"True"}
```
监控 eviction：`dmesg -T | grep -iE 'evicted|167-0|server handle changed'`；`lctl get_param -n osc.*.ost_server_uuid mdc.*.mds_server_uuid mgc.*.mgs_server_uuid`。

*配合 24h Lustre 压测（lustre_stress_24h.sh）+ PCC 缓存 + 吞吐变配实验一并进行。相关：`fsx-lustre-throughput-change/`、`fsx-lustre-efa-diag/`。*
