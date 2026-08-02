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

## 后续可做

- **丢包注入**：`AWSFIS-Run-Network-Packet-Loss`（如 10%/30%）—— 比延迟更能打断 TCP，可能真正触发 eviction。
- **端口黑洞**：`AWSFIS-Run-Network-Blackhole-Port`（Lustre 端口 988/1024）—— 模拟 OST 彻底失联。

*配合 24h Lustre 压测（lustre_stress_24h.sh）+ PCC 缓存 + 吞吐变配实验一并进行。相关：`fsx-lustre-throughput-change/`、`fsx-lustre-efa-diag/`。*
