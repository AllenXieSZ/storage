# FSx ONTAP Gen2 Single-AZ 3072 MBps 读写吞吐实测

实测 Amazon FSx for NetApp ONTAP **第二代（Gen2）Single-AZ、throughput capacity = 3072 MBps** 档位的实际读/写吞吐，并与官方文档规则对照。

## 结论摘要

| 指标 | 官方文档规则/预期 | 实测（持续稳定值） |
|---|---|---|
| **顺序读吞吐** | "reads = full provisioned throughput capacity"（≈3072） | **~5,920 MiB/s ≈ 6,207 MB/s** |
| **顺序写吞吐** | "writes ≈ 1/3 of provisioned capacity"（≈1024） | **~1,530 MiB/s ≈ 1,606 MB/s** |
| 读稳定性 | — | 持续 8 分钟无衰减（非短暂 burst） |

**核心发现（实测纠正直觉）：**
1. **"throughput capacity=3072" 不是读吞吐的硬上限**。实测读打到 **~6,207 MB/s，几乎正好等于 Gen2 Single-AZ 的 SSD 读吞吐上限 6,144 MBps/HA pair**，且**持续 8 分钟稳定不降**（CloudWatch 分钟曲线全程 5884–5958 MiB/s）。
2. 官方"读=满额 throughput capacity"是**保守下限描述**；大块顺序读 + nconnect=16 + 命中 SSD 层时，实际读吞吐可超过标称的 3072，冲到 SSD 存储层的物理上限。
3. **写吞吐 1,606 MB/s**，比官方保守的"1/3≈1024"高约 1.5×，但**约为读的 1/4** —— 印证写受 2× 复制成本（写要复制到 secondary）+ 写上限约束，明显低于读。

## 官方文档依据

来源：https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html

- Gen2 规则："second-generation file systems can deliver the full provisioned throughput capacity for reads and up to a third of the provisioned throughput capacity for writes"（6144 档除外）。
- Gen2 Single-AZ 最大 SSD 吞吐 **per HA pair**：读 **6,144 MBps** / 写 **1,024 MBps**。
- throughput capacity 合法档位：Gen2 Single-AZ = 1536 / 3072 / 6144 MBps；Gen1 = 128/256/512/1024/2048/4096 MBps。
- 写占 2× network 带宽（复制到 secondary 文件服务器）。
- 可达吞吐 = min(network I/O 层, disk I/O 层)；disk 层默认 768 MBps/TiB + 3072 IOPS/TiB。

## 测试环境

| 项目 | 配置 |
|---|---|
| 文件系统 | FSx ONTAP，**SINGLE_AZ_2**（Gen2），ThroughputCapacityPerHAPair=**3072**，1 HA pair，2048 GiB SSD |
| Region/AZ | us-east-2c |
| 客户端 | **c5n.18xlarge（100 Gbps 网络）** — 远超 3072 MBps(≈24 Gbps) 需求，确保网络不成瓶颈 |
| 挂载 | NFSv3，**nconnect=16**，rsize/wsize 请求 1M（服务端钳制为 64K） |
| fio | direct=1，bs=1M，iodepth=32，numjobs=16 |
| 数据集 | 16 × 8 GiB = 128 GiB（远超文件服务器 cache，确保打穿到 SSD 层） |

## 测试方法

1. 预铺 128 GiB 数据（16 个 8G 文件，dd urandom）——注意用 dd 预铺，避免 fio layout 在小吞吐档卡死。
2. **读测试**：`echo 3 > drop_caches` 清客户端缓存后，fio 顺序读全部 16 文件，先测 120s，再测 **480s（8 分钟）** 确认非 burst。
3. **写测试**：fio 顺序覆写 16 文件 120s。
4. **CloudWatch 验证**：拉 `DataReadBytes` / `DataWriteBytes` 分钟曲线（Sum ÷ 60 ÷ 1048576 = MiB/s），确认吞吐稳定性与真实性（客户端 fio 数与服务端 CloudWatch 数一致）。

## 测试输出日志

**fio 读吞吐（120s）：**
```
read: IOPS=5918, BW=5923MiB/s (6211MB/s)(695GiB/120073msec)
```

**fio 写吞吐（120s）：**
```
write: IOPS=1527, BW=1531MiB/s (1606MB/s)(180GiB/120260msec)
```

**fio 读吞吐（480s / 8 分钟，验证非 burst）：**
```
read: IOPS=5919, BW=5920MiB/s (6207MB/s)(2775GiB/480059msec)
```

**CloudWatch DataReadBytes 分钟曲线（8 分钟持续读，全程稳定无衰减）：**
```
01:16  3910 MiB/s   (ramp up)
01:17  5884 MiB/s
01:18  5957 MiB/s
01:19  5893 MiB/s
01:20  5948 MiB/s
01:21  5888 MiB/s
01:22  5958 MiB/s
01:23  5885 MiB/s
```

**CloudWatch DataWriteBytes 分钟曲线（写测试）：**
```
01:13  1465 MiB/s
01:14  1595 MiB/s
```

## 备注

- 读吞吐 6207 MB/s ≈ SSD 读上限 6144 MBps，且 8 分钟不衰减，说明此档位下读的瓶颈在 SSD 存储层而非 throughput capacity 标称值，"3072"在读方向不是硬顶。
- 写吞吐受复制成本与写上限约束，实测约为读的 1/4，符合"写更受限"的文档描述。
- rsize/wsize 被 ONTAP 服务端钳制为 64K 是 ONTAP 已知行为，不影响大块顺序吞吐达成。

---
测试日期：2026-08-21 (UTC) | 环境：Gen2 Single-AZ，us-east-2 | 方法：fio + CloudWatch
