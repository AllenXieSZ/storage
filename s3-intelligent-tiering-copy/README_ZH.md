# S3 Intelligent-Tiering Bucket 复制：能否保留分层状态？

## 结论

**不能。** S3 Intelligent-Tiering 的 access tier（Frequent / Infrequent / Archive Instant / Archive / Deep Archive）是 S3 内部状态，不是独立的 Storage Class。对象无论通过 CopyObject、`aws s3 sync`、还是 S3 Replication 复制到目标 bucket，**都从 Frequent Access tier 重新开始**，由 S3 根据访问模式自动重新分层。

> 官方文档原文（[How S3 Intelligent-Tiering works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html)）：
> - "Objects that are uploaded or transitioned to S3 Intelligent-Tiering are automatically stored in the **Frequent Access tier**."
> - "When objects move between access tiers, **the storage class remains the same** (S3 Intelligent-Tiering)."

## 三种方案对比

### 方案 1：aws s3 sync + INTELLIGENT_TIERING

```bash
aws s3 sync s3://source-bucket s3://dest-bucket --storage-class INTELLIGENT_TIERING
```

- ✅ 简单直接，一条命令
- ✅ 目标 bucket 对象自动进入 Intelligent-Tiering 分层管理
- ❌ 所有对象从 Frequent Access 重新开始，需要 30/90/180 天重新沉降
- ❌ 过渡期存储费用高于源 bucket（全在 Frequent Access 价格）
- ❌ 大规模数据需要长时间运行，无断点续传保障

### 方案 2：按源 tier 映射到不同独立 Storage Class（不推荐）

用 S3 Inventory 查出每个对象的 access tier，按映射关系 copy 到对应的独立 Storage Class（IA→Standard-IA, Archive Instant→Glacier IR 等）。

**三个致命问题：**

1. **很多 Storage Class 不能 lifecycle 回 Intelligent-Tiering**：Glacier IR / Glacier FR / Deep Archive / One Zone-IA 都不支持通过 lifecycle transition 到 Intelligent-Tiering（S3 lifecycle 是单向瀑布流）
2. **独立 Storage Class 有 retrieval 费，Intelligent-Tiering 没有**：IT 的 IA / Archive Instant Access tier 读取零 retrieval 费，但 Standard-IA / Glacier IR 每次读都收 per-GB retrieval 费，等于凭空增加持续性开支
3. **既然已经在独立 Storage Class 了，再搬回 IT 没有意义**：操作复杂、费用高、很多路径还走不通

### 方案 3：S3 Replication（推荐）✅

配置 S3 Replication（SRR 同区域 或 CRR 跨区域），目标 Storage Class 设为 INTELLIGENT_TIERING。

```json
{
  "Rules": [{
    "ID": "replicate-to-new-bucket",
    "Status": "Enabled",
    "Filter": { "Prefix": "" },
    "Destination": {
      "Bucket": "arn:aws:s3:::dest-bucket",
      "StorageClass": "INTELLIGENT_TIERING"
    },
    "DeleteMarkerReplication": { "Status": "Disabled" }
  }]
}
```

**存量数据**：用 S3 Batch Replication 一次性复制已有对象。

**优点：**
- ✅ 存量 + 增量一套方案搞定（Batch Replication 处理存量，Live Replication 处理增量）
- ✅ AWS 托管，自动重试、进度跟踪、完成报告
- ✅ 支持跨账号、跨 Region
- ✅ 目标自动进入 Intelligent-Tiering，从 Frequent Access 开始自动分层
- ✅ 可配合 S3 RTC（Replication Time Control）保障 99.99% 对象 15 分钟内完成复制

**缺点：**
- ❌ 同样无法保留源 tier，从 Frequent Access 重新开始
- ❌ 源 bucket 需要开启 Versioning
- ❌ Archive Access / Deep Archive Access tier 的对象**不能直接复制**，需要先 RestoreObject

**注意事项：**
- 源 bucket 必须开启 Versioning（Replication 前提）
- 如果源 bucket 有对象在 Archive Access 或 Deep Archive Access tier，需要先 restore 再复制，或者排除这些对象后单独处理
- 目标 bucket 配置与源相同的 Intelligent-Tiering Configuration（Archive Access / Deep Archive Access 的激活天数），确保分层策略一致

## 过渡期成本评估

无论哪种方案，对象到目标 bucket 后都从 Frequent Access 开始。可用 S3 Inventory 导出源 bucket 的 `IntelligentTieringAccessTier` 字段，统计各 tier 数据量，预估过渡期成本差异：

| 源 Tier | 重新沉降所需天数 | 过渡期价格差（us-east-1） |
|---|---|---|
| Infrequent Access | 30 天 | Frequent $0.023 vs IA $0.0125/GB-月 |
| Archive Instant Access | 90 天 | Frequent $0.023 vs AIA $0.004/GB-月 |
| Archive Access | 90~730 天（按配置） | Frequent $0.023 vs AA $0.0036/GB-月 |
| Deep Archive Access | 180~730 天（按配置） | Frequent $0.023 vs DA $0.00099/GB-月 |

大部分数据（IA + Archive Instant）会在 30~90 天内恢复到对应 tier，过渡期成本可控。

## 参考文档

- [How S3 Intelligent-Tiering works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html)
- [What does Amazon S3 replicate?](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication-what-is-isnot-replicated.html)
- [Replication configuration - Specify storage class](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication-add-config.html#storage-class-configuration)
- [Supported lifecycle transitions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-transition-general-considerations.html)
- [Copying objects](https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html)
