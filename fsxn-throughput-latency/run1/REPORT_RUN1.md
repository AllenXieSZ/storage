# FSxN 升吞吐过程对 IO Latency 影响实测报告

**日期**: 2026-09-06 | **区域**: AWS us-east-2 (Ohio) | **账号**: 386094880462

## 1. 实验目的

测量 **FSx for NetApp ONTAP（FSxN）在线升吞吐操作本身对单请求 IO 延迟的冲击**：
从发起 `update-file-system`（提升 ThroughputCapacityPerHAPair）起，每隔约 10 秒采一个
延迟样本（read + write 各一轮 fio），直到升吞吐完成，绘制延迟随时间变化曲线，找出峰值。

## 2. 环境与规格

| 项目 | 值 |
|---|---|
| 文件系统 | FSxN **Gen2 / `SINGLE_AZ_2`**，1 HA pair |
| FileSystemId | `fs-0d7924d394930c95f` |
| 存储容量 | 1024 GiB SSD（AUTOMATIC IOPS = 3072） |
| SVM | `svm-05b23cf0627829b64`（svm1），NFS IP `172.31.44.241` |
| Volume | `fsvol-0f81981b69e53e9b6`（vol1，512 GiB，junction `/vol1`，UNIX，SE 关闭） |
| 子网 / AZ | `subnet-0c551a33e366d52d4` / us-east-2c |
| VPC | `vpc-0c28d2a9082ef222e` |
| 专用 SG | `sg-02326ca1dc0af5246`（放行来自跳板机 SG `sg-0d67509101b407583` 的 NFS 2049/111/635/4045-4046 + SSH 22） |
| 挂载/压测机 | MySQL-Master EC2 `i-0dffb881b2a90daa2`（Amazon Linux，SSM 驱动） |
| 挂载参数 | `nfsvers=3`（rsize/wsize=65536，服务端钳制 64K） |
| fio 版本 | fio-2.14 |

> **⚠️ 规格纠正（查 AWS 官方 `create-file-system` help 核实）**：
> HANDOFF 里假设最小吞吐档可能是 384，但官方文档明确
> **`SINGLE_AZ_2` 合法吞吐档只有 1536 / 3072 / 6144 MBps**（384/768 仅 `MULTI_AZ_2` 有）。
> 因此本次以最小档 **1536** 创建，升吞吐路径 **1536 → 3072 MBps**（本次不扩 HA，不触发扩 HA 的死锁约束）。

## 3. fio 参数（严格按要求）

```
bs=16k  ioengine=sync  direct=1  numjobs=1  iodepth=1
rw=randread（一轮） + randwrite（一轮）
runtime=8 -time_based   # 每轮短跑，采单点延迟
```
关注指标：**clat 均值 + p99**（sync/direct/iodepth=1 下即真实单请求延迟）。
> 实际采样节奏：read(8s) + write(8s) + 开销 ≈ **每 ~17 秒一个 read/write 样本对**（runtime 严格保留 8s，故节奏略大于名义 10s，已如实标注）。

## 4. 时间线

| 事件 | 时刻 (UTC) | loop 相对 T0 |
|---|---|---|
| baseline 采样（5 轮） | 03:29:27 – 03:31:0x | — |
| **发起升吞吐 1536→3072** | **03:31:35** | ≈ 0 s |
| 监测 loop 启动 | 03:31:39 | 0 s |
| **升吞吐 COMPLETED** | **≈ 03:52:13** | **≈ 1234 s** |
| 收尾采样结束 | 03:53:55 | 1336 s |

**升吞吐总耗时 ≈ 20.5 分钟**（AdministrativeAction `FILE_SYSTEM_UPDATE` 从 IN_PROGRESS 到 COMPLETED）。

## 5. 结果

### 5.1 基线（升级前）
| op | mean (µs) | p99 (µs) |
|---|---|---|
| read | ~224 | ~316 |
| write | ~733 | ~18300（16k sync 写受 NFS 提交/落盘抖动，p99 本就高） |

### 5.2 升级过程中（核心结论）

| op | 峰值 mean | 出现时刻 | 峰值 p99 | 出现时刻 |
|---|---|---|---|---|
| **write** | **12,336 µs（12.3 ms）** | **+167 s** | 22,656 µs | +0 s |
| **read** | **904 µs** | **+784 s** | 1,400 µs | +768 s |

- **最显著冲击 = 写延迟在 +167 s 飙到 12.3 ms**（≈ 基线写均值的 17 倍、读均值的 55 倍），
  推测对应升吞吐过程中的**存储/文件服务器重配置或 failover 瞬间**（Gen2 在线改吞吐会切换底层文件服务器规格）。
- **次级冲击在 +768~818 s**：读均值短暂升到 ~900 µs、p99 ~1.4 ms；写 p99 再次抬到 ~13 ms 量级。
- 除这两个窗口外，绝大多数样本延迟**接近基线**——升吞吐**不是全程劣化，而是少数几个瞬时抖动点**。

### 5.3 升级完成后
- **read mean 降到 ~184 µs**（比基线 224 µs 更低），p99 ~330–360 µs 且稳定。
- **write mean 降到 ~390–410 µs**（比基线 733 µs **降约 45%**），p99 从基线 ~18 ms 降到 **~500–570 µs**。
- 说明升到 3072 MBps 后，单请求写延迟与尾延迟均**明显改善并更稳定**。

### 5.4 曲线图
见 `latency_curve.png`：上图 clat 均值（log 轴，read/write，含 baseline 虚线），
下图 clat p99；黄色区间 = 升吞吐窗口（T0→COMPLETED），绿/红虚线标起止，标注写延迟 12.3ms 峰值点。

## 6. 结论

1. **FSxN Gen2 在线升吞吐（1536→3072）总体是"在线、低影响"操作**：全程 ~20.5 min，IO 未中断，
   绝大多数时刻延迟接近基线。
2. **但存在瞬时延迟尖峰**：写延迟峰值 **12.3 ms @ +167 s**（约基线 17×），另在 +770s 附近有次级读/写抖动。
   对**延迟敏感**的同步小 IO 负载，升吞吐期间会感知到偶发的秒级以下~十几毫秒尖刺。
3. **升级完成后收益明确**：写延迟均值降 ~45%、写 p99 从 ~18 ms 降到 sub-ms，读延迟也更低更稳。
4. 建议：对延迟极敏感的生产负载，把升吞吐安排在低峰窗口；升级完成后延迟改善值得。

## 7. 资源（默认保留，伟伟习惯）

```
FileSystem : fs-0d7924d394930c95f   (SINGLE_AZ_2, 现 3072 MBps, 1024 GiB)
SVM        : svm-05b23cf0627829b64
Volume     : fsvol-0f81981b69e53e9b6
SG         : sg-02326ca1dc0af5246
挂载机     : i-0dffb881b2a90daa2 (共用跳板机，未新建)
```

### 清理命令（需要时执行）
```bash
R=us-east-2
aws fsx delete-volume --volume-id fsvol-0f81981b69e53e9b6 --region $R
# 等 volume 删除完成后：
aws fsx delete-storage-virtual-machine --storage-virtual-machine-id svm-05b23cf0627829b64 --region $R
# 等 SVM 删除完成后：
aws fsx delete-file-system --file-system-id fs-0d7924d394930c95f --region $R
# 文件系统删完后删 SG：
aws ec2 delete-security-group --group-id sg-02326ca1dc0af5246 --region $R
```

## 8. 产物
- `results.csv` — 全部采样（baseline + 升级过程），列：elapsed_sec, op, lat_mean_us, lat_p99_us, timestamp_utc, phase
- `latency_curve.png` — 延迟曲线图
- `latency_loop.sh` / `plot.py` — 采样与画图脚本
