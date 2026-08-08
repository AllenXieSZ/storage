# FSx for Lustre — DRA 元数据 Import 两条通道对比与实测速率

Amazon FSx for Lustre 通过 **DRA (Data Repository Association)** 把 S3 对象的元数据同步进 Lustre 文件系统时，有**两条完全不同的通道**，速率天差地别。本文用实测数据澄清一个常见混淆，并给出容量规划公式。

- **区域**: us-east-2 (Ohio)
- **文件系统**: FSx Lustre `PERSISTENT_2` (SSD)
- **测试数据集**: `s3://<bucket>/metaXXX/`，小对象（1KB~10KB），多目录分散
- **测试日期**: 2026-06 ~ 2026-08

---

## 一、两条通道（核心结论，别混为一谈）

| 通道 | 触发方式 | 速率 | `AgeOfOldestQueuedMessage` |
|---|---|---|---|
| **DRA batch import task** | 首次建 DRA / 手动 `create-data-repository-task`(IMPORT_METADATA_FROM_REPOSITORY) | **~2000 obj/s（实测稳态，恒定）** | 基本不进队列，指标 ≈ 0 |
| **AutoImport 增量同步** | 建 DRA 后，S3 侧再发生变更，走 S3 event notification 逐条触发 | 慢得多（见官方上限） | 积压时飙升，靠它监控 |

**官方对 AutoImport 的能力描述**（AWS 文档 `autoimport-data-repo-dra`）：
> 对接单分片(single shard) S3 桶、持续满速推变更时，**AutoImport 在 14 天内只能处理约 7 小时的 S3 变更积压**。单次 S3 批量操作产生的变更量，可能远超 AutoImport 14 天能消化的量。

即 AutoImport 消费速率 ≈ S3 满速生产速率的约 1/48，**不适合一次性大批量变更**。

---

## 二、DRA batch import task 实测速率表

metadata import = 建目录树 + stub（released 占位），**不含数据 restore**（数据要等首次读/warmup 才从 S3 拉）。

| 数据集 | 对象数 | import 耗时 | 速率 |
|---|---|---|---|
| meta200k | 200,200 | 1.7 min | 1,947 obj/s |
| meta2m | 2,000,020 | 14.9 min | 2,236 obj/s |
| **meta20m** | **20,002,000** | **2.81 h (120.7 min)** | **1,976 – 2,762 obj/s** |

- **稳态速率 ~2000 obj/s，累计进度曲线是完美直线**（受服务端元数据能力恒定限制）。
- **粗估公式**：`import 秒数 ≈ 对象数 ÷ 2000`
  - 100 万 → ~8 min
  - 1000 万 → ~1.4 h
  - 2000 万 → ~2.8 h（全部实测吻合）
- 2000万文件 import 时叠加 metadata 压测，24000 metadata IOPS 未打满，import 也没被拖慢 → import 速率不吃客户端侧 IOPS，卡在服务端元数据处理。

---

## 三、如何观察 batch import 进度（重要：不走 CloudWatch）

**DRA batch import 进度通过 FSx API `describe-data-repository-tasks` 轮询，而不是看 CloudWatch 指标。**

```bash
aws fsx describe-data-repository-tasks \
  --region us-east-2 \
  --task-ids <task-id> \
  --query 'DataRepositoryTasks[0].[Lifecycle,Status.TotalCount,Status.SucceededCount,Status.FailedCount]' \
  --output text
```

- `Lifecycle`：`PENDING` → `EXECUTING` → `SUCCEEDED`（或 `FAILED`）
- `Status.TotalCount`：本次任务要处理的对象总数
- `Status.SucceededCount`：已成功处理数（**进度就看这个**，每 30~60s 轮询算增量即得速率）
- `Status.FailedCount`：失败数

**速率算法**：连续两次采样 `(SucceededCount₂ − SucceededCount₁) / Δt`。实测该值在量大时稳定 ~2000 obj/s，累计曲线呈完美直线。

> ⚠️ **关键区别**：batch import 走独立 import task 通道，进度只在 `describe-data-repository-tasks` 里可见；它**基本不进 AutoImport 事件队列**，所以 CloudWatch 的 `AgeOfOldestQueuedMessage` 全程 ≈0。想监控 import 进度**别去看 CloudWatch**，要轮询 task API。反之，AutoImport 增量同步没有 task，只能靠下面的 CloudWatch 指标。

## 四、`AgeOfOldestQueuedMessage` 指标要点

- **发布位置**：CloudWatch 命名空间 `AWS/FSx`，属于 "S3 repository metrics" 里的 AutoImport/AutoExport 指标。
- **维度**：`FileSystemId` + `Publisher`（`AutoImport` 或 `AutoExport`）。
- **单位**：秒。含义 = 队列中"最老的一条待处理变更消息"已等待多久。
- **只在 AutoImport/AutoExport 队列活跃时才有数据点。**

**实测（100万×1KB，建 DRA→batch import 全程每 30s 采样）**：
- 整个 batch import 全程该指标**几乎全是 None 或 0**，只在 import 尾声冒出一个孤立尖峰（~393s）随即回 0。
- **坐实**：首次 DRA batch import **不会**让该指标持续走高——它走独立 import task 通道，基本不进 AutoImport 队列。
- **该指标真正反映的是「建好 DRA 后，S3 后续变更触发的 AutoImport 增量同步积压」**，不是初始导入。

---

## 五、实践建议

1. **首次灌大量数据 / 一次性大批量变更** → 用 **手动 import data repository task**（并行、~2000 obj/s），**不要**依赖 AutoImport 事件队列（会严重积压，甚至可能因超出保留窗口丢事件）。
2. **AutoImport 适合**：S3 侧持续、涓涓细流式的增量变更（队列能实时追平，指标稳定接近 0）。
3. **监控**：对 `AgeOfOldestQueuedMessage`（`Publisher=AutoImport`）设 CloudWatch 告警 + 开启 DRA event logs 到 CloudWatch Logs，积压/失败时能定位具体文件。
4. **容量规划**：用 `对象数 ÷ 2000` 估 batch import 耗时；AutoImport 稳态吞吐远低于此，按官方 "14天/7小时" 关系保守估算。

---

## 常见误区（记录一次踩过的坑）

❌ 把两条通道混为一谈，用 AutoImport 的慢速率去估 batch import 耗时（例如误算"100万对象要13天"）。
✅ 实测：**batch import ~2000 obj/s，100万只需 ~8 分钟**。官方"14天/7小时"仅针对 AutoImport 增量事件队列。

## 数据来源

- AWS 官方文档：`docs.aws.amazon.com/fsx/latest/LustreGuide/fs-metrics.html`（S3 repository metrics，维度 FileSystemId+Publisher）
- AWS 官方文档：`docs.aws.amazon.com/fsx/latest/LustreGuide/autoimport-data-repo-dra.html`（AutoImport 能力上限 "14天/7小时"）
- 实测数据：2026-06 ~ 2026-08，FSx Lustre PERSISTENT_2，us-east-2
