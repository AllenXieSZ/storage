# AWS Local Zone gp3 性能实测（亚特兰大 Atlanta）

在 AWS Local Zone **亚特兰大（us-east-1-atl-2a，父区 us-east-1f）** 实测增强版 gp3 卷，验证 IOPS 与吞吐能否达到设置值。

## 测试环境

| 项目 | 配置 |
|---|---|
| Local Zone | us-east-1-atl-2a（Atlanta，父 AZ us-east-1f） |
| 实例 | c6i.16xlarge（64 vCPU，EBS 带宽 20 Gbps ≈ 2.5 GB/s） |
| gp3 卷 | 6553 GiB，**设置 80,000 IOPS / 2,000 MiB/s**（增强版 gp3 上限） |
| OS | Amazon Linux 2023 |
| 工具 | fio 3.32，direct=1，裸设备 /dev/nvme1n1 |
| 说明 | 测前顺序写 200G 预热，消除 gp3 首次访问惩罚 |

## 实测结果

| 测试项 | 设置目标 | 实测 | 达标率 |
|---|---|---|---|
| 随机读 IOPS（4k, iodepth=64×16job） | 80,000 | **80,200** | ✅ 100% |
| 随机写 IOPS（4k, iodepth=64×16job） | 80,000 | **80,200** | ✅ 100% |
| 顺序读吞吐（1M, iodepth=32×8job） | 2,000 MiB/s | **2,068 MiB/s** | ✅ 103% |
| 顺序写吞吐（1M, iodepth=32×8job） | 2,000 MiB/s | **2,068 MiB/s** | ✅ 103% |

## 结论

1. **亚特兰大 Local Zone 的 gp3 完全达到设置值**，IOPS 和吞吐全部跑满，甚至略超（吞吐 +3%）。
2. **增强版 gp3（80,000 IOPS / 2,000 MiB/s）在 Local Zone 真实可用且性能达标**（不只是 API 接受配置，是实测能跑满）。
3. **Local Zone 的 EBS 后端性能与母 Region 无差异**，无隐性折扣。
4. 打满 80k IOPS 时用了高队列深度（iodepth=64×16job=1024），随机读平均延迟约 12.5 ms——这是高并发换高 IOPS 的正常代价（IOPS = 并发 / 延迟）。追求低延迟时用低队列深度，IOPS 会相应降低。

## 前置知识：并非所有 Local Zone 都支持 gp3

据 AWS Local Zones Features 官方页：
- **支持 gp3**（列为 gp3, gp2, io1, st1, sc1）：Atlanta、Chicago、Dallas、Houston、Los Angeles、Miami、New York、Phoenix 等（较新的 C6i/M6i 一代机型的 Local Zone）
- **仅支持 gp2**：Boston、Denver、Honolulu、Kansas City、Las Vegas、Minneapolis、Philadelphia、Portland、Seattle、Querétaro 等（老一代 C5d/R5d/G4dn 机型的 Local Zone）

参考：
- https://aws.amazon.com/about-aws/global-infrastructure/localzones/features/
- https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volume-types.html

---
测试日期：2026-08-20
