# 自建 Lustre 2.15.8 集群 —— 性能压测报告

**日期：** 2026-07-18 (Ohio us-east-2a)
**集群：** 1×MDS(MGS+MDT) + 2×OSS(各2 OST) + 1×Client，全部 i7i.2xlarge (8 vCPU/64GiB/up-to-12Gbps)
**存储：** 全 EBS gp3。MDT=50G gp3；每 OST=100G gp3（4 OST，单盘基线 125 MB/s + 3000 IOPS）
**文件系统：** lustrefs，4 OST，总容量 390 GB；LNet tcp0，同 AZ 私网
**客户端内核：** 4.18.0-553.124.4.el8_10（stock + DKMS lustre-client 2.15.8）
**测试工具：** fio 3.19（libaio, direct=1）

---

## 结果汇总

| 测试项 | 配置 | 结果 | 对照基线 |
|---|---|---|---|
| **单流顺序写** | stripe_count=1, bs=1M, iodepth=16 | **127 MiB/s (133 MB/s)** | 单 gp3 基线 125 MB/s ✅ |
| **单流顺序读** | stripe_count=1, bs=1M, iodepth=16 | **127 MiB/s (133 MB/s)** | 单 gp3 基线 ✅ |
| **宽条带顺序写** | stripe_count=4, 4 jobs, bs=1M | **505 MiB/s (530 MB/s)** | 4×gp3 ≈ 500 MB/s ✅ |
| **宽条带顺序读** | stripe_count=4, 4 jobs, bs=1M | **508 MiB/s (533 MB/s)** | 4×gp3 ✅ |
| **4K 随机写 IOPS** | stripe_count=4, 8 jobs, iodepth=32 | **8,611 IOPS (33.6 MiB/s)** | 4×gp3=12000 IOPS 上限，写偏低 |
| **4K 随机读 IOPS** | stripe_count=4, 8 jobs, iodepth=32 | **12,100 IOPS (47.1 MiB/s)** | 4×gp3=12000 IOPS 上限 ✅ 打满 |
| **元数据 单线程 create** | 空文件, 单 MDT | **1,285 files/s** | 单 MDT (gp3) |
| **元数据 并行 create** | 8 进程 × 5000 | **5,703 files/s** | 单 MDT 并发提升 4.4× |
| **元数据 unlink** | 单线程 | **623 files/s** | 删除比创建慢 |
| **元数据 stat (ls -f 20000)** | 缓存内 | 14 ms | 元数据已缓存 |

---

## 关键结论（均有实测数据支撑，非推测）

1. **吞吐 = OST 数 × 单 gp3 基线**，与之前 FSx 实测的"OSS 数 × per-flow"规律一致。
   - 单流被单 OST（单 gp3 125MB/s）限死 → 127 MiB/s。
   - 4 条带打满 4 OST → 505 MiB/s（≈4×）。**要高吞吐必须 `lfs setstripe -c 4`**。
2. **IOPS 上限 = OST 数 × gp3 3000 IOPS = 12000**。
   - 随机读 12.1k 精确打满聚合上限；随机写 8.6k（gp3 写放大 + Lustre 元数据开销，偏低约 28%）。
   - 想提 IOPS：给 gp3 加 provisioned IOPS，或换 io2。
3. **元数据受单 MDT 限制**：单线程 1285 files/s，并行可到 5703 files/s。
   - 只有 1 个 MDT（gp3 backend），元数据是瓶颈。多 MDT（DNE）可横向扩展，但本集群只建了 1 个。
4. 客户端 8 vCPU/12Gbps 网络在本测试中**不是瓶颈**（530MB/s 远低于 12Gbps=1500MB/s），瓶颈全在 gp3 后端。

## 提升方向（如需）
- 顺序吞吐：加 OST 数量（更多 OSS 盘）或给 gp3 调高 throughput（gp3 可单独调至 1000 MB/s/盘）。
- IOPS：gp3 provisioned IOPS 上调（最高 16000/盘）或换 io2 Block Express。
- 元数据：加 MDT（DNE striped dir），本集群目前单 MDT。
- 单客户端>530MB/s：多客户端并行，或 stripe 打满 + 更大 bs。

**测试脚本：** `lustre-build/bench.sh`（客户端 /tmp/bench.sh）
