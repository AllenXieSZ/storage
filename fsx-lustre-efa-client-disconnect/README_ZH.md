# FSx for Lustre EFA 客户端高并发写入断连：根因与规避

测试日期：2026-10-16（us-east-2）

## 1. 结论

| 项目 | 结论（已实测） |
|---|---|
| **现象** | 大规格 EFA FS（72 TiB / 15 OSS）上，单个大机型 EFA 客户端高并发写入，几秒到 2 分钟内 IO 停止，15 个 OST 全部 `CONNECTING`，fio 进入 D 状态，只能重启客户端 |
| **触发条件** | 单客户端同时在途的 RPC 总数过高 = `osc.max_rpcs_in_flight` × 写入的 OST 数。约 256–512 时开始断连 |
| **规避方法** | 挂载后执行 `lctl set_param osc.*.max_rpcs_in_flight=8` |
| **规避效果** | c8gn.48xlarge 写入从"断连"变为稳定 **46–64 GB/s**（180 s 持续 52.7 GB/s）；c8gn.24xlarge 写入稳定约 31 GB/s，读取从 14.4 提升到 **37.1 GB/s**（接近 300 Gbps 网卡线速） |
| **不是原因** | FS 服务端总量 / OSS 过载、某台 OSS 故障、双 EFA 网卡、第二张网卡带 IP / 路由、NUMA、单纯带宽高 |

推测（未实测）：阈值与 LNet EFA 网络接口的 `credits=256` 相当。超过后请求在客户端本地排队，同时 EFA 重传增加，kefalnd（1.2.2）没有平滑限流，而是超时并取消发送，最终 OST 断连。AWS 文档未给出 EFA 客户端的 `max_rpcs_in_flight` 建议值。

## 2. 错误信息

断连时客户端 `dmesg`（48xl，默认 `max_rpcs_in_flight=64`，IP 已脱敏，完整内容见 [`logs/`](./logs/)）：

```
Lustre: ... ptlrpc_expire_one_request()) @@@ Request sent has timed out for sent delay: [sent 1792134072/real 0]  req@... o4->...-OST0007-osc-...@10.0.0.72@tcp:6/4 ...
Lustre: ...-OST0002-osc-...: Connection to ...-OST0002 (at 10.0.0.188@tcp) was lost; in progress operations using this service will wait for recovery to complete
Lustre: ... Request sent has timed out for sent delay: [sent 1792134092/real 0]  req@... o400->...-OST0001-osc-...@10.0.0.165@tcp:28/4 ...
LNet: ...(efalnd.c:949:kefalnd_force_cancel_tx()) Device[efa_1] canceling TX type[IMMEDIATE] to peer NI[<OSS_EFA_NID>@efa]
Lustre: ... Request sent has timed out for slow reply: [sent 1792134276/real 1792134276]  req@... o4->...-OST0000-osc-...
```

之后 fio 进程卡死（串口控制台，24xl）：

```
INFO: task fio:9491 blocked for more than 122 seconds.
task:fio             state:D stack:0     pid:9491 ...
 wait_for_completion+0x28/0x40
 exit_aio+0x130/0x388
```

**解读**
- `o4` = OST_WRITE，`o400` = OBD_PING。`sent delay ... real 0` 表示请求一直排在客户端本地，没有真正发出。
- 断连前 EFA `tx_bytes` 停止增长，`retrans_pkts` / `retrans_timeout_events` 上升；`lnetctl peer show -v` 中 EFA peer 的 `min_tx_credits` 降到 −21 ~ −56。
- 顺序：EFA 发送停滞 + 重传 → ptlrpc 超时 → `Connection ... was lost` → `kefalnd_force_cancel_tx` → 15 个 OST `CONNECTING` → fio D 状态。
- 稳定配置下 dmesg 也会偶尔出现 `kefalnd_finv_complete() ... completion with err[4] vendor[5]`，不会导致断连。

## 3. 测试环境

| 项目 | 配置 |
|---|---|
| FS | PERSISTENT_2，SSD，1000 MB/s/TiB，EFA，元数据 AUTOMATIC。**72,000 GiB（15 OSS，基线 72 GB/s）**；对照 19,200 GiB（4 OSS）、9,600 GiB（2 OSS） |
| 客户端 | c8gn.48xlarge（2 × EFA，600 Gbps）、c8gn.24xlarge（1 × EFA，300 Gbps）、c8gn.16xlarge（1 × EFA，200 Gbps） |
| 软件 | AL2023 kernel 6.12.111，lustre-client 2.15.6，efa 驱动 3.3.1，kefalnd 1.2.2 |
| 客户端配置 | 官方 `install-fsx-lustre-client.sh --install-lustre --install-efa` + `configure-efa-fsx-lustre-client/setup.sh`，未做其他修改 |
| 默认参数 | `osc.max_rpcs_in_flight`：48xl = 64，24xl / 16xl = 32；`max_pages_per_rpc=256`（1 MiB RPC）；`max_dirty_mb=64`；LNet EFA NI `credits=256`、`peer_credits=32` |
| SG | 自引用全放行出入站（EFA 要求） |

## 4. 测试方法

每组测试前重启或重新挂载客户端，确认 15 个 OST 为 `FULL`。fio 运行期间每 5 秒采集 OST 连接状态、EFA 硬件计数器（`tx_bytes`、`retrans_pkts`、`retrans_timeout_events`）和 dmesg 错误数，结束后采集 `dmesg`、`osc.*.import`、`rpc_stats`、`lnetctl stats/net show -v 4/peer show -v`、FSx CloudWatch 指标。

**判定断连**：dmesg 出现 `lost` / `timed out` / `network error` / `force_cancel`，或 OST 状态不是 `FULL` / `IDLE`，或 EFA 发送/接收字节连续 25 秒不增长。

**fio 命令**（写；读把 `--rw=write` 改为 `--rw=read`，读前 `echo 3 > /proc/sys/vm/drop_caches`）：

```bash
mkdir -p /fsx/t && lfs setstripe -c -1 /fsx/t      # 全条带；只写前 N 个 OST 用 -c N -i 0
fio --name=t --directory=/fsx/t --rw=write --bs=16M --size=8G --numjobs=<NJ> \
    --ioengine=libaio --iodepth=8 --direct=1 --time_based --runtime=60 \
    --group_reporting --output-format=json
```

**测试维度（每次只改一个变量）**

| 维度 | 做法 |
|---|---|
| 单客户端 vs 服务端总量 | 4 台 16xl 同时写 vs 1 台 48xl 单独写 |
| 并发阈值 | 改 numjobs、条带数（`-c 1/2/4/8/15`）、`fio --rate` 限速 |
| 单卡 vs 双卡 / NUMA | 24xl（单 EFA）对照 48xl；48xl 两组 fio 分别绑定 NUMA0/1 |
| 某台 OSS 故障 | 绕开多次最先报错的 OST 写其余 14 个；单独写该 OST |
| 客户端参数 | `osc.max_rpcs_in_flight` = 8 / 16 / 32 / 默认；`peer_credits` = 8 |
| FS 规模 | 2 / 4 / 15 OSS |

脚本见 [`scripts/`](./scripts/)：`brc_run.sh`（单组测试 + 采集）、`brc_numa.sh`（NUMA 分组）、`brc_ud.sh`（客户端安装）、`brc_mount.sh`、`brc_cw.py`（FSx CloudWatch 导出）。全部结果见 [`logs/summary_all_runs.txt`](./logs/summary_all_runs.txt)。

## 5. 测试结果

记号："断" = OST lost / CONNECTING，或 IO 停滞 ≥ 25 s。未注明的都是 72 TiB / 15 OSS FS、全条带、60 s 写入。

### 5.1 `max_rpcs_in_flight`（关键变量）

| 客户端 | 负载 | max_rpcs_in_flight | 结果 |
|---|---|---|---|
| 48xl | 写 nj=96 | 默认 64 | **断**（多次复现） |
| 48xl | 写 nj=96 | 32 | **断** |
| 48xl | 写 nj=96 | 16 | 断 1 次 / 62.10 GB/s 1 次 |
| 48xl | 写 nj=96 | **8** | **46.29 / 36.20 / 63.61 GB/s，180 s 持续 52.67 GB/s，4/4 稳定** |
| 48xl | 写 nj=96 | 默认，只降 `peer_credits` 32→8 | **断** |
| 24xl | 写 nj=8 | 默认 32 | 断 / 吞吐塌陷到 2.88、4.91 GB/s |
| 24xl | 写 nj=8 | 16 | 29.92 / 29.89 GB/s，2/2 稳定 |
| 24xl | 写 nj=8 / 32 | **8** | **31.74 / 25.36 / 30.94 / 34.00 GB/s，4/4 稳定** |
| 24xl | 读 nj=8 | 默认 32 | 14.41 GB/s |
| 24xl | 读 nj=8 | **8** | **37.12 GB/s** |

### 5.2 单客户端 vs 服务端总量

| 客户端 | 负载 | 结果 |
|---|---|---|
| 1 × 16xl | 写 nj=64，180 s | 25.26 GB/s 稳定 |
| **4 × 16xl 同时** | 每台写 nj=64，180 s / 120 s | 合计 **70.3 GB/s**（两次），FS 写满（盘吞吐利用率 101%），0 错误 |
| 1 × 48xl 单独 | 写 nj=96 | **断** |

48xl 断连期间 FSx 服务端 CPU 最高 3%、网络吞吐利用率最高 19%，服务端没有过载。

### 5.3 写入的 OST 数（默认参数）

| 客户端 | 写入 OST 数 | 结果 |
|---|---|---|
| 24xl（rif=32） | 4 / 8 | 19.83 / 37.52 GB/s 稳定 |
| 24xl（rif=32） | 14 / 15 | **断** |
| 48xl（rif=64） | 1 / 2 / 4 | 5.06 / 10.08 / 19.90 GB/s 稳定 |
| 48xl（rif=64） | 8（nj=32） | 38.15 GB/s 稳定 |
| 48xl（rif=64） | 15 | **断** |

### 5.4 带宽不是决定因素

| 客户端 | 负载 | 结果 |
|---|---|---|
| 48xl | nj=1 / 2 / 4，全条带 | 10.70 / 20.39 / 29.85 GB/s 稳定 |
| 48xl | nj=32 `--rate` 限速到 ~30 GB/s | 30.06 GB/s 稳定 |
| 48xl | nj=6–8 不限速 | **断** |
| 48xl | 两组 fio 绑 NUMA0/1，各 16 job 限速 | 35.64 GB/s 稳定（两卡各 17.8） |
| 24xl / 48xl | rif=8，不限速 | 25–64 GB/s 稳定 |

### 5.5 某台 OSS 故障？

| 测试 | 结果 |
|---|---|
| 历次最先报错的 OST | 0007、000d、0008、0006、0000、0002、0009、000e，每次不同 |
| 24xl 绕开 OST000d 写其余 14 个 OST | **断**，这次最先报错的是 OST0008 |
| 24xl 单独写 OST000d（nj=32） | 4.99 GB/s 稳定 |

### 5.6 FS 规模（默认参数）

| FS | 客户端 | 结果 |
|---|---|---|
| 9.6 TiB / 2 OSS | 48xl 写/读 nj=32/64/96 | 稳定，约 10 GB/s（FS 上限） |
| 19.2 TiB / 4 OSS | 24xl 写 nj=8 × 2、nj=32 × 2 | 20.15 / 19.96 / 20.02 / 20.07 GB/s 稳定（FS 上限） |
| 72 TiB / 15 OSS | 24xl / 48xl 写 nj ≥ 8 | **断** |

OSS 少的 FS 上，OST 数 × `max_rpcs_in_flight` 低于阈值，所以不会触发。

## 6. 规避与建议

1. **大规格 EFA FS（OSS 多）+ 大机型 EFA 客户端**，挂载后设置：
   ```bash
   lctl set_param osc.*.max_rpcs_in_flight=8
   ```
2. `lctl set_param` 重启后不保留，需要在每次挂载后自动执行（例如 systemd 单元 `After=` 挂载点，或 `@reboot` cron 等待挂载完成后执行）。
3. 不建议用 16：48xl 上 2 次中断过 1 次。
4. 建议向 AWS 提交 case，最小复现步骤：
   - 建 72,000 GiB PERSISTENT_2 SSD 1000 MB/s/TiB EFA FS，SG 自引用全放行。
   - c8gn.24xlarge（1 × EFA，AL2023 6.12），运行官方安装脚本和 `setup.sh`。
   - `mount -t lustre -o relatime,flock <FS_DNS>@tcp:/<MOUNT_NAME> /fsx`，`lfs setstripe -c -1 /fsx/t`。
   - 运行第 4 节 fio 命令（nj=8）→ 数秒到 2 分钟内 OST lost / CONNECTING，或吞吐塌陷到 < 5 GB/s。
   - `lctl set_param osc.*.max_rpcs_in_flight=8` 后重跑 → 稳定约 31 GB/s。

## 7. 限制

- 内部机制（为什么在 256–512 个并发 RPC 时断连）为推测，未实测验证。
- 48xl 在 `max_rpcs_in_flight=8` 下的读测试未拿到有效结果（fio 超时），读路径只有 24xl 的数据。
- 未测：kefalnd `credits` / `nqps`、LNet `transaction_timeout` / `retry_count` / `health_sensitivity`、`max_pages_per_rpc`、`max_dirty_mb`；其他 AMI / 更新版本 kefalnd；8 OSS 中间规格。
- 每组测试 1–4 次。

## 参考文档

- 配置 EFA 客户端：https://docs.aws.amazon.com/fsx/latest/LustreGuide/configure-efa-clients.html
- EFA-enabled 文件系统：https://docs.aws.amazon.com/fsx/latest/LustreGuide/efa-file-systems.html
- 性能：https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance.html
- 性能优化建议（`lctl set_param` 重启不保留）：https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance-tips.html
