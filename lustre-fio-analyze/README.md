# FSx for Lustre 读写压测 + analyze.sh 系统诊断 —— 完整日志解读

> 环境：FSx Lustre 2.15 / PERSISTENT_2 / 4.8TB / 250MB·s·TiB / **2 MDT + 4 OST** / Metadata IOPS 24000
> 客户端：c5.4xlarge（16 vCPU / 31GB）、lustre-client 2.15.6
> 负载：fio 8 jobs × iodepth 16、bs=1M、direct=1、rw 混合（70% 读 / 30% 写）、20 分钟
> 诊断：analyze.sh 在压测前/中/后各采一次，本文重点解读「压测中（--live）」这份。

---

## fio 结果（20 分钟稳态）

| 指标 | 读 | 写 | 合计 |
|---|---|---|---|
| 带宽 | **1183 MiB/s (1241 MB/s)** | **507 MiB/s (532 MB/s)** | **~1690 MiB/s (1.77 GB/s)** |
| IOPS | 1183 | 507 | 1690 |
| 传输量 | 1387 GiB | 595 GiB | ~1982 GiB |
| 平均延迟 | 88.9 ms | 44.8 ms | — |
| P99 延迟 | 321 ms | 264 ms | — |

---

## 第 1 段：EC2 元数据

```
> curl ... /latest/meta-data/instance-type
c5.4xlarge
> curl ... /latest/meta-data/instance-id
i-0b591b9798e624dde
```

**解读**：
- analyze.sh 开头用 **IMDSv2**（先 PUT 拿 token，再带 `X-aws-ec2-metadata-token` 头查）从 `169.254.169.254`（EC2 元数据服务的固定链路本地地址）读实例信息。
- 为什么记这个：诊断日志先标明「哪台机器、什么机型」——机型决定 **网络带宽 / CPU / 内存上限**，是后续分析瓶颈的基准。c5.4xlarge = 16 vCPU / 31GB / ~10Gbps 网络。

---

## 第 2 段：CPU — top（压测中）

```
top - 01:36:35 up 30 min, load average: 2.42, 1.41, 0.78
Tasks: 280 total, 3 running, 277 sleeping
%Cpu(s): 0.0 us, 4.5 sy, 0.0 ni, 93.9 id, 0.0 wa, 0.0 hi, 1.6 si, 0.0 st
MiB Mem : 31384.6 total, 29452.9 free, 1044.5 used, 887.2 buff/cache

    PID USER  ... %CPU  COMMAND
  27727 root ... 13.3  socknal+
  27728 root ... 13.3  socknal+
  27732 root ... 13.3  socknal+
```

**逐字段解读（怎么看 top）**：
- **load average 2.42/1.41/0.78** = 过去 1/5/15 分钟平均运行队列长度。2.42 相对 16 核 → 负载很轻（满载应接近 16）。
- **%Cpu 行（最关键）**：
  - `us`（用户态）**0.0%** — 应用自己几乎不吃 CPU
  - `sy`（内核态）**4.5%** — 少量内核活动（网络 / Lustre 驱动）
  - `id`（空闲）**93.9%** — CPU 九成多在闲着
  - `wa`（iowait，等 IO）**0.0%** — 没有卡在等磁盘 / 网络返回
  - `si`（softirq 软中断）**1.6%** — 网络包处理
  - `st`（steal）0.0% — 无邻居争抢
- 内存：31GB 只用 1GB，30GB 空闲 → 内存不是瓶颈。
- **最忙进程是 `socknal`（各 13.3%）** = Lustre LNet 的 socket 网络线程（socklnd，Lustre over TCP 的网络驱动）。压测时最忙的是网络线程，不是 fio 本身 → 佐证瓶颈在网络传输层，不在计算。

**要点**：看性能先看 top 的 %Cpu 行——`id` 高 + `wa` 低 + 应用 CPU 低 = 瓶颈不在本机 CPU，往下游（网络 / 存储后端）找；`socknal` 最忙直接指向「网络传输」。

---

## 第 3 段：内存 — free

```
              total     used      free    shared  buff/cache  available
Mem:       32137812   1068388  30160948    2808     908476    30606380   (KB)
Swap:             0        0         0
```

**解读**：
- total 32GB，used 仅 **1GB**，free / available **30GB**。
- `buff/cache` 才 **887MB** —— 关键：fio 用 **`direct=1`（direct I/O，绕过 page cache）**，数据不进内存缓存，所以 buff/cache 很小。这是故意的：测真实存储性能就要绕过缓存，否则测到的是内存速度。
- `Swap: 0` — 无换页压力。
- 结论：内存完全空闲，不是瓶颈。

---

## 第 4 段：sar（系统活动报告）

```
Linux 6.18.44-99.149.amzn2023.x86_64 (16 CPU)
01:06:08  LINUX RESTART (16 CPU)
```

**解读**：
- `sar`（sysstat 包）能看一段时间的 CPU / 磁盘 / 网络趋势。
- 这里只有 `LINUX RESTART` —— 因为机器刚开机 30 分钟，sar 还没累积足够历史采样（默认每 10 分钟由 cron 采一次）。新机器上 sar 数据少是正常的，短测更依赖 top / perf 实时数据。

---

## 第 5 段：网络连接 — ss -tanoip

```
State   Recv-Q Send-Q  Local Address:Port  Peer Address:Port  Process
LISTEN  0      128      0.0.0.0:22          0.0.0.0:*          sshd
```

**解读**：
- `ss` 看 socket 连接。`-t`=TCP `-a`=所有 `-n`=不解析域名 `-o`=计时器 `-i`=内部信息 `-p`=进程。
- 只截到 sshd 的监听 —— 注意：**Lustre 的网络流量走内核态 LNet（socknal 线程），不走普通用户态 socket**，所以 `ss` 里看不到客户端到 OST 的连接（内核 LND 管理）。Lustre 特点：网络层在内核，普通网络工具看不全。

---

## 第 6 段：LNet NID + 挂载选项（Lustre 核心）

```
> lctl list_nids
172.31.41.55@tcp            ← 客户端自己的 LNet 网络标识

172.31.45.171@tcp:/foebrb4v on /mnt/lustre type lustre
  (rw,relatime,seclabel,checksum,flock,nouser_xattr,lruresize,
   lazystatfs,nouser_fid2path,verbose,encrypt)
```

**逐项解读**：
- **NID（Network Identifier）`172.31.41.55@tcp`** = Lustre 给客户端的网络地址标识，格式 `IP@网络类型`。`@tcp`=走 TCP（socknal）；高性能场景可能是 `@o2ib`（InfiniBand）。
- **挂载源 `172.31.45.171@tcp:/foebrb4v`** = 服务端 NID + 文件系统名（MountName）。
- 挂载选项：
  - `checksum` — 开启数据传输校验和（防网络错误损坏，略有 CPU 开销）
  - `flock` — 支持文件锁
  - `nouser_xattr` — 不支持用户扩展属性
  - `lruresize` — LRU 缓存动态调整
  - `lazystatfs` — df 时不等所有 OST 响应（个别 OST 慢也不卡 df）
  - `encrypt` — 支持加密（FSx 默认开）
- 要点：`lctl list_nids` + `mount -t lustre -l` 是排查 Lustre 第一步——确认客户端 NID、连的哪个服务端、开了哪些特性（checksum / encrypt 都吃一点性能）。

---

## 第 7 段：OSC 读写统计（客户端↔OST 的真实 I/O 计数）

```
write_bytes  218784 samples [bytes]  min=2048     max=1048576  sum=124758851584
read_bytes    80144 samples [bytes]  min=1048576  max=1048576  sum=84037074944
ost_read      80144 samples [usec]   min=2808     max=54767    ← 读请求耗时
ost_write     89016 samples [usec]   min=183      max=53660    ← 写请求耗时
```

**逐字段解读（Lustre 性能核心证据，来自 `lctl get_param osc.*.stats`）**：
- OSC = Object Storage Client（客户端对接 OST 的模块）。每行：`名称 样本数 单位 最小值 最大值 累计和 平方和`。
- **`read_bytes`**：min=max=**1048576（1MB）** → 每个读请求都是整齐的 1MB（正是 fio 的 bs=1M，读对齐大块）。sum=84GB（采集时刻累计读量）。
- **`write_bytes`**：min=**2048（2KB）**, max=1MB → 写请求大小不齐！2KB 来自那 10 万个小文件的写入 / 元数据，1MB 来自 fio，混合了。
- **`ost_read` / `ost_write`（单位 usec 微秒）** = 每个 OST 请求的往返延迟：
  - 读：2.8ms ~ **54ms**
  - 写：0.18ms ~ **53ms**
  - 这解释了 fio 的高延迟——单个 OST 请求最慢 50+ms，高并发排队累积成 fio P99 300ms。
- 要点：`osc.*.stats` 是看真实 I/O 大小分布和 OST 延迟的权威数据。

---

## 第 8 段：OST/MDT 健康状态（lctl dl）

```
0: foebrb4v-MDT0000_UUID ACTIVE
1: foebrb4v-MDT0001_UUID ACTIVE      ← 2 个 MDT 都在线
0: foebrb4v-OST0000_UUID ACTIVE
1: foebrb4v-OST0001_UUID ACTIVE
2: foebrb4v-OST0002_UUID ACTIVE
3: foebrb4v-OST0003_UUID ACTIVE      ← 4 个 OST 都在线
foebrb4v-MDT0000_UUID  FULL
```

**解读**：
- 列出所有 target（MDT + OST）及状态。`ACTIVE` = 正常连接可用。
- **2 MDT + 4 OST 全 ACTIVE** —— 证实 24000 IOPS 配置 = 2 MDT；容量 4.8TB = 4 OST（每 OST 约 1.2TB）。
- `FULL` = 客户端和该 target 的连接状态完整（正常）。
- 要点：`lctl dl` 快速确认所有 MDT/OST 是否 ACTIVE——排查「某 OST 掉线 / DISCONN 导致性能下降」的第一步。吞吐 = 多 OST 并行叠加，4 OST 都 ACTIVE 才能跑满带宽。

---

## 第 9 段：perf 内核热点（--live 独有，最能定性瓶颈）

```
# Overhead  Command   Shared Object       Symbol
   87.93%   swapper   [kernel.kallsyms]   [k] pv_native_safe_halt
```

**解读（最关键一段）**：
- `perf record -a` 采样 5 秒内整个系统 CPU 花在哪些函数上，按占比排序（`--percent-limit=5` 只显示 >5%）。
- **唯一超过 5% 的是 `swapper` 的 `pv_native_safe_halt`，占 87.93%**。
- `swapper` = 内核空闲进程（idle task）；`pv_native_safe_halt` = CPU 进入 halt（停机等待）指令。
- 含义：**87.93% 的 CPU 时间在空转 / halt** —— CPU 大部分时间无事可做，在等外部（网络 / OST）返回数据。
- 没有任何 Lustre / fio 计算函数进前列（都 <5%）→ 铁证：瓶颈不在 CPU 计算，CPU 在闲等 I/O。
- 要点：perf 是定性瓶颈的杀手锏——热点是 `pv_native_safe_halt`（halt/idle）占大头 = 系统在等 I/O，瓶颈在存储 / 网络后端，加 CPU 没用；若热点是某具体计算函数（加密 / 压缩 / 锁），才是 CPU / 软件瓶颈。

---

## 综合结论

| 日志证据 | 说明什么 |
|---|---|
| top: `id 93.9%` `wa 0%` | CPU 九成空闲，没等 IO 卡住 |
| top: 最忙是 `socknal`(13%) | 最忙的是 Lustre 网络线程，活动在网络传输 |
| free: 30GB 空闲、cache 小 | 内存不是瓶颈；direct I/O 绕过缓存（测真实性能） |
| osc stats: `ost_read` max 54ms | 单个 OST 请求延迟高，高并发排队 → fio P99 300ms |
| lctl dl: 2 MDT + 4 OST 全 ACTIVE | 后端拓扑健康，4 OST 并行供给吞吐 |
| **perf: 87.93% halt** | **CPU 在闲等 I/O，瓶颈在后端吞吐 / 网络，不在客户端** |

**最终结论**：fio 读 1241 + 写 532 = **1.77 GB/s** 的上限，来自 FSx 后端吞吐档（250MB/s·TiB）+ 客户端网卡带宽（c5.4xlarge ~10Gbps），**不是客户端 CPU / 内存**（全空闲，perf 证明在 halt）。

**想更高吞吐**：① 升 PerUnitStorageThroughput 档（250→500/1000 MB/s·TiB，抬高后端供给）；② 上更大网络的客户端（c5n 等）或多客户端并行（单 c5.4xlarge 网卡 ~10Gbps 已接近读带宽上限）。

**排查套路**：top（CPU 忙不忙 / 是否 iowait）→ free（内存）→ perf（定性：halt=等IO / 计算函数=CPU瓶颈）→ lctl dl + osc.*.stats（Lustre 专有：OST/MDT 健康 + 真实 I/O 大小与延迟）。
