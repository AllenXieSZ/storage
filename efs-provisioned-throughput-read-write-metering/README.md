# Amazon EFS Provisioned Throughput 读写吞吐与计费指标实测

实测 Amazon EFS（Regional，General Purpose，**Provisioned 500 MiB/s**）的读/写真实吞吐上限，以及计费/配额到底按哪个指标计量。全部结论均有 fio + CloudWatch 实测证据。

## 结论摘要（全部实测验证，非推理）

| 场景 | 真实吞吐（fio 实测） | 计费指标 MeteredIOBytes（CloudWatch 实测） |
|---|---|---|
| **纯写打满** | **500 MiB/s**（单客户端即可撞顶） | **500 MiB/s**（1:1 计量） |
| **纯读打满** | **1,520 MiB/s**（需 4 客户端并发） | **506 MiB/s**（≈1/3 计量，撞顶） |

**核心结论：**
1. **计费/配额限制的是 `MeteredIOBytes`，不是真实吞吐**。你 provision 的 500 MiB/s 限制的就是这个指标。
2. **读操作按 1/3 费率计量**：真实读 1520 MiB/s → 计费仅 506 MiB/s（实测比值 3.0）。写按 1:1 计量。
3. **因此 Provisioned 500 MiB/s 的真实吞吐上限：写 = 500 MiB/s，读 = 1,500 MiB/s（3 倍）**。
4. **单客户端（单挂载）per-client 上限 = 500 MiB/s**：所以读要冲到 1500 必须多客户端并发；单台 EC2 无论怎么压读都只能到 500。

## 官方文档依据

来源：
- https://docs.aws.amazon.com/efs/latest/ug/performance.html
- https://docs.aws.amazon.com/efs/latest/ug/efs-metrics.html

关键原文：
- "Read throughput is discounted to allow you to drive higher read throughput than write throughput."
- "Amazon EFS **meters read operations up to one-third the rate of write operations**."
- CloudWatch 指标定义：
  - `ReadIOBytes` / `WriteIOBytes` / `TotalIOBytes` = **实际（真实）吞吐**
  - `MeteredIOBytes` = 计量吞吐，"**read operations discounted according to the throughput limit**"（读打折后的计量值）—— 这才是判断是否撞 provisioned 上限、以及计费的指标
- 性能规格表：Regional 文件系统 **per-client 读/写上限 = 500 MiBps**。

## 关键实测证据（CloudWatch 分钟曲线）

**① 纯写窗口（单客户端满载写）：**

| 分钟 | WriteIOBytes（真实写） | MeteredIOBytes（计费） | 比值 |
|---|---|---|---|
| T+1 | 500 MiB/s | 500 MiB/s | 1:1 |
| T+2 | 500 MiB/s | 500 MiB/s | 1:1 |

→ 写：真实 = 计费，直接撞 500 上限。

**② 纯读窗口（单客户端满载读）：**

| 分钟 | ReadIOBytes（真实读） | MeteredIOBytes（计费） | 比值 |
|---|---|---|---|
| T+1 | 508 MiB/s | 169 MiB/s | ≈3.0 |
| T+2 | 499 MiB/s | 166 MiB/s | ≈3.0 |

→ 单客户端读被 per-client 500 卡住，真实读只到 500，计费仅 167（还远没撞 500 顶，说明读还有额度）。

**③ 4 客户端并发读窗口（突破 per-client 限制）：**

| 指标 | 值 |
|---|---|
| ReadIOBytes（真实读，4 台合计） | **1,520 MiB/s** |
| MeteredIOBytes（计费） | **506 MiB/s** |
| PermittedThroughput | 500 MiB/s |
| 比值（真实/计费） | **3.0** |

→ 真实读 1520，计费按 1/3 只算 506，恰好撞到 provisioned 500 上限。**读真实吞吐达到 1500 得到实测证实。**

4 台客户端各自读吞吐：约 390 MiB/s × 4 = 1,567 MiB/s（fio 端），CloudWatch 服务端计 1,520 MiB/s。

## 与 FSx ONTAP 的对比

| | FSx ONTAP Gen2 | EFS Provisioned |
|---|---|---|
| 预置数字含义 | throughput capacity（network 带宽预算） | 计量吞吐（MeteredIOBytes）上限 |
| 读写关系 | 读满额、写≈1/3（**写吃 2× 带宽**） | **读按 1/3 计量**（读真实吞吐 = 写的 3 倍） |
| 谁的真实吞吐更高 | 读 > 写（读约写的 3-6 倍） | 读 > 写（读 = 写的 3 倍） |
| 机制本质 | 写更贵（复制到 secondary） | 读打折（计量层面鼓励读） |
| 单客户端限制 | 受 EC2 网络/nconnect | per-client 500 MiBps |

## 测试环境与方法

- EFS：Regional，General Purpose，Provisioned 500 MiB/s，加密，us-east-2
- 客户端：最多 4 台 EC2（c5n 系列，高网络带宽），Amazon Linux 2023
- 挂载：`mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,noresvport`
- fio：direct=1，bs=1M，iodepth=16，numjobs=8~16
- 方法：
  1. 预铺数据文件（dd urandom）。
  2. 读/写测试**分时段错开**（各 180s，中间停 60s），使 CloudWatch 分钟粒度能清晰区分读窗口与写窗口。
  3. 每次读前 `echo 3 > drop_caches` 清客户端缓存。
  4. 读要突破单客户端 500 上限时，用 4 台客户端**同时并发读**同一 EFS。
  5. 对照三个 CloudWatch 指标：`DataReadIOBytes` / `DataWriteIOBytes`（真实）vs `MeteredIOBytes`（计费）vs `PermittedThroughput`（上限）。

## 实用建议

- **读密集型 workload**：EFS 的 1/3 读计量非常划算——provision 500 就能支撑 1500 真实读吞吐。
- **写密集型 workload**：写按 1:1 计量，真实写上限 = provisioned 值，无折扣。
- **单机跑不满读**：单客户端 per-client 500 MiBps 是硬限制，需要横向扩展多客户端才能吃满文件系统级的高读吞吐。

---
测试日期：2026-08-21 (UTC) | 环境：EFS Regional Provisioned 500 MiB/s，us-east-2 | 方法：fio + CloudWatch（真实吞吐 vs MeteredIOBytes 对照）
