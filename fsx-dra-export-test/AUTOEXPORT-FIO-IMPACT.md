# FSx for Lustre — DRA AutoExport 进行中 vs 完成后 对前端 FIO 性能影响

本测试回答一个具体问题：**当 DRA AutoExport 正在把大批量数据导出到 S3 时，前端应用（fio）的读写性能会不会下降？下降多少？导出完成后是否恢复？**

> 注：本文与同目录 `README.md`/`REPORT.md`（测 export 吞吐本身）是**不同角度**——那份测「导出多快」，本文测「导出过程中前端 IO 受多大影响」。

- **区域**: us-east-2 (Ohio)
- **文件系统**: FSx Lustre `REDACTED`，`PERSISTENT_2`，1.2 TiB，250 MB/s/TiB（单 OST）
- **客户端**: 1 × `i7i.4xlarge`（16 vCPU / 128 GiB RAM / 本地 NVMe），Amazon Linux 2023，lustre-client 2.15.6，与 FSx 同 AZ（us-east-2a）
- **测试日期**: 2026-08-07

## 测试方法

```
1. 往 /fsx/exptest 写 100GB = 100,000 个 1MB 小文件（fio 16 并行，492 MiB/s，221s）
2. 对该目录创建 DRA，关联到新 S3 bucket，开 AutoExport（New/Changed/Deleted）
3. append 触发全部 10 万文件的 CHANGED → 制造大批量 export 积压（触发耗时 158s）
4. 【export 进行中】在独立目录 /fsx/fiozone 跑 fio（不含被 export 的文件，纯看资源争抢）
5. 等 S3 对象数导满 100,000（export 追平）后，再跑一次相同 fio 对比
```

FIO 参数：
- 顺序读/写：`bs=1M, numjobs=8, iodepth=32, direct=1, runtime=60, time_based`
- 随机读：`bs=4k, numjobs=16, iodepth=64, direct=1, runtime=60, time_based`

## 结果对比

| 负载 | export 进行中 | export 完成后 | 下降幅度 |
|------|--------------|--------------|---------|
| 顺序写 1M | 390 MiB/s | 514 MiB/s | **−24%** |
| 顺序读 1M | 441 MiB/s | 508 MiB/s | **−13%** |
| 随机读 4K | 1,561 IOPS | 2,087 IOPS | **−25%** |

**证据链**：S3 bucket 对象数从 99,997 → 100,000 的时间线，证明 export 确实在第一轮 fio 期间进行、在第二轮前追平。export 完成后的数字与无 DRA 基线（504/503 MiB/s、2,131 IOPS）一致，说明性能完全恢复。

## 核心结论

1. **AutoExport 大批量积压（10 万文件）进行中，会明显拖累前端 fio 性能**：
   - 顺序写 **−24%**、随机读 **−25%**（受影响最大）
   - 顺序读 **−13%**（相对轻）
2. **export 追平后，性能完全恢复正常**。
3. **原因**：AutoExport 是后台异步任务，需要读文件系统数据 + 处理元数据推送到 S3，与前端 fio I/O **争抢文件系统后端带宽和元数据资源**。写和随机小 IO 对元数据/IOPS 敏感，掉得多；顺序读主要吃带宽，受影响相对小。

## 实践建议

- 大批量 export（如批量 checkpoint 落 S3）最好**避开前端高负载时段**，或接受期间约 −25% 的性能折损。
- 稳态增量 export（少量新文件）影响很小；本次 −24% 是 10 万文件一次性积压的**极端情况**。
- 监控积压可用 CloudWatch `AgeOfOldestQueuedMessage`；但实测本账号 DRA 维度指标查不到数据，**用 S3 对象计数判断 export 进度更可靠**。

## 备注：CloudWatch 指标坑

- `AgeOfOldestQueuedMessage` 指标名在文件系统级 `list-metrics` 里存在，但按 `FileSystemId + DataRepositoryAssociationId` 维度 `get-metric-statistics` 查询返回空数据点。
- 排查 export 进度时，直接 `aws s3 ls s3://<bucket>/ --recursive | wc -l` 对比目标文件数最直接可靠。
