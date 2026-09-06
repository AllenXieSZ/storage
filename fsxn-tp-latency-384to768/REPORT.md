# FSxN 升吞吐 384→768 对 IO 延迟影响实测报告

**实验日期**: 2026-09-06 (UTC)
**执行者**: storage-bench subagent（独立实验，与 1536→3072 实验完全隔离）
**结论一句话**: 单 HA pair 内 384→768 升吞吐是 **online（不中断）** 操作，耗时约 **26 分钟**；升级过程中有 **一次明显的瞬时延迟尖峰**（read p99 冲到 ~20ms、write mean 冲到 ~8.9ms，发生在开始后约 3~4 分钟），其余时间只是**中度抬升**；升级完成后 **write 延迟稳态高于 baseline（300us→450us），read 基本回落**。

---

## 1. 环境与规格

| 项 | 值 |
|---|---|
| Region / 账号 | us-east-2 / 386094880462 |
| FSxN | Gen2 **SINGLE_AZ_2**，**单 HA pair (HAPairs=1)** |
| 文件系统 | `fs-049b7a5387930eeed`（实验后已删除） |
| 存储容量 | 1024 GiB SSD |
| 起始吞吐 | **384 MBps/HA pair**（该部署类型最低档） |
| 目标吞吐 | **768 MBps/HA pair** |
| SVM / Volume | svm1 / vol1（FlexVol 512GiB，junction `/vol1`，UNIX，SE 关闭） |
| 挂载 | NFSv3，`nfsvers=3`，rsize/wsize=64K（ONTAP 钳制） |
| 挂载/压测机 | MySQL-Master EC2 `i-0dffb881b2a90daa2`（AZ us-east-2c，共用，未删） |
| 专用 SG | `sg-08af4a5ca5cce5afa`（独立，实验后已删除） |

**档位合法性（已查证）**: FSx ONTAP Gen2 SINGLE_AZ_2 单 HA pair 合法吞吐档 = **384/768/1536/3072/6144 MBps**（Terraform AWS provider 官方文档："Valid values for deployment type MULTI_AZ_2 and SINGLE_AZ_2 are 384, 768, 1536, 3072, 6144 where ha_pairs is 1"）。**384→768 都在单 HA pair 内，不涉及扩 HA pair。**

## 2. fio 测试方法

- 参数（严格照旧）：`bs=16k ioengine=sync direct=1 numjobs=1 iodepth=1 runtime=8 -time_based`
- 每轮：先 randread 8s，再 randwrite 8s，各取 **clat mean + clat p99**（单位 us；fio 2.14 clat 直接以 us 报告）
- 采样节奏：约每 ~18s 一轮（两次 8s fio + 解析）
- 三阶段：**baseline**（升前 5 轮）→ **upgrade**（发起升吞吐后持续采样至 COMPLETED，86 read+85 write 样本）→ **post**（完成后收尾 5 轮）
- 结果写在跳板机本地 `/root/tp384_results.csv`（非 NFS，避免自扰）

## 3. 升吞吐耗时

- T0（发起 `update-file-system ThroughputCapacityPerHAPair=768`）: **2026-09-06 06:34:13 UTC**
- AdministrativeAction `FILE_SYSTEM_UPDATE` → COMPLETED、TP 显示 768: **07:00:22 UTC**
- **升吞吐总耗时 ≈ 1569 秒 ≈ 26.1 分钟**（全程 online，NFS 挂载未断，fio 持续有 IO）

## 4. 延迟统计（单位 us）

| op | 阶段 | 样本 | mean 均值 | mean 峰值 | p99 均值 | p99 峰值 |
|----|------|-----|----------|----------|---------|---------|
| read | baseline | 5 | **181.8** | 186.1 | **359.6** | 414.0 |
| read | upgrade | 86 | 262.7 | **1473.0** | 737.6 | **20352.0** |
| read | post | 5 | 255.9 | 261.0 | 395.6 | 430.0 |
| write | baseline | 5 | **300.1** | 303.3 | **559.6** | 604.0 |
| write | upgrade | 85 | 481.7 | **8855.9** | 636.3 | **3248.0** |
| write | post | 5 | 453.0 | 456.3 | 581.6 | 620.0 |

## 5. 有没有大尖峰？—— 有，但是瞬时单点

升吞吐过程中确实出现 **一次明显的瞬时延迟尖峰**，集中在 T0 后约 **3~4 分钟**（对应 ONTAP 后台节点重配/failover 时刻）：

- **write clat mean 尖峰 8856 us（≈8.9 ms）@ t=178s** —— 相对 baseline 300us **约 30×**
- **read clat p99 尖峰 20352 us（≈20.4 ms）@ t=250s** —— 相对 baseline p99 360us **约 57×**
- **read clat mean 尖峰 1473 us @ t=250s**；write p99 另有一处 3248us @ t=613s

这些都是**单个采样点的瞬时毛刺**（下一轮即回落），不是持续高延迟。此外全程未见 IO error、未断连、fio 未中断——**操作是 online 无中断的**。

## 6. 稳态影响：write 抬升，read 基本回落

- **read**：尖峰过后逐步回落，稳态 ~250–260us（略高于 baseline 182us，post 阶段 255.9us）。
- **write**：升级后稳态 ~390–460us，**明显高于 baseline 300us**（post 阶段 453us）。write p99 也从 baseline ~560us 升到 ~580–640us。
- 说明升吞吐完成后写路径延迟有一个**持续性抬升**（约 +50%），推测与 768 档下的资源/队列/后台重平衡有关（此为观察，非官方定论）。

## 7. 结论

1. **单 HA pair 内 384→768 升吞吐是 online 操作**，NFS 不中断，本次耗时 **~26 分钟**。
2. 升级过程有 **一次明显瞬时延迟尖峰**（read p99 ~20ms、write mean ~8.9ms），发生在开始后 3~4 分钟，属单点毛刺（很可能对应节点重配/failover 窗口），**持续时间极短**。
3. 稳态影响：**read 基本回落到接近 baseline，write 稳态延迟持续高于 baseline（+~50%）**。
4. 对延迟敏感的在线业务：升吞吐建议避开业务高峰，因存在秒级的 10~20ms 级瞬时尖峰；总体不中断，但会有一次可感知的抖动。

## 8. 资源清理

**资源已全部清理，无残留计费。**
- 删除 volume `fsvol-091cfb4e19b2fa550` → SVM `svm-0b7126dba6e881839` → FSxN `fs-049b7a5387930eeed`
- 删除专用 SG `sg-08af4a5ca5cce5afa`（确认无 ENI 依赖后）
- 跳板机 `i-0dffb881b2a90daa2` 共用未删；仅清理本实验 NFS 挂载 `umount -f -l /mnt/fsx384` 及测试文件

---

*方法遵循 SOUL 铁律：档位查 Terraform/AWS 官方文档核实；延迟以 fio 实测为准；私网挂载/取数据走 SSM + S3 中转。本实验与 1536→3072 实验使用独立 FS + 独立 SG，完全隔离。*
