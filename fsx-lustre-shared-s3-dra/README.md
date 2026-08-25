# 一个 S3 Bucket 双向 DRA 关联多个 FSx for Lustre —— 完整实测

> 实测日期：2026-08-25 | Region：us-east-2 | 作者：AllenXieSZ
> 目标：验证「同一个 S3 bucket 能否被多个 FSx for Lustre 文件系统同时通过 DRA（Data Repository Association）双向关联」，并实测增/改/删/并发/直写 S3 各场景的同步行为。

## TL;DR

- ✅ **可行且不报错**：一个 S3 bucket 可以同时被多个 FSx Lustre 文件系统各自建 DRA 关联。约束都在「每 FS ≤ 8 个 DRA / root `/` 独占 1 个」这一侧，**bucket 侧无限制**。
- ✅ **S3 作为中枢实现多 Lustre 间接双向同步**：`A ⇄ S3 ⇄ B`。开启双向 auto-import + auto-export（含 DELETED 事件）后，两个 Lustre 通过 S3 达成准实时互通，本次实测各场景延迟均在**秒级**。
- ⚠️ **写冲突 = last-writer-wins**：并发/顺序覆盖同一文件时后写覆盖，三方（A/S3/B）最终一致，**不损坏、不脑裂、不报错**，代价是**丢更新**（无版本合并、无冲突副本）。

---

## 测试环境

| 项 | 值 |
|---|---|
| Region / AZ | us-east-2 / us-east-2c |
| FSx Lustre A | PERSISTENT_2, 1.2 TiB, 125 MB/s/TiB |
| FSx Lustre B | PERSISTENT_2, 1.2 TiB, 125 MB/s/TiB |
| S3 bucket | 单一 bucket，root `/` 关联 |
| DRA 配置（A、B 相同） | `FileSystemPath=/`，`DataRepositoryPath=s3://bucket/`，`--batch-import-meta-data-on-create`，`AutoImportPolicy={NEW,CHANGED,DELETED}`，`AutoExportPolicy={NEW,CHANGED,DELETED}` |
| 挂载客户端 | Amazon Linux 2，lustre-client 2.12.8（同 VPC/AZ EC2，走 SSM 操作） |

---

## ⭐ 实测结果矩阵（全部实测坐实）

| # | 验证项 | 结果 | 延迟 |
|---|---|---|---|
| 1 | 第二个 FS 关联**同一 bucket** 是否报错 | ✅ **不报错**，DRA 正常创建 | — |
| 2 | A 写 10 文件 → auto-export 到 S3 | ✅ 成功 | 秒级 |
| 3 | B 建 DRA 时 batch-import → 看到 A 的 10 文件 | ✅ 挂载后直接可见 | — |
| 4 | B 写 5 文件 → S3 → auto-import 同步到 A | ✅ 成功 | 秒级 |
| 5 | 直接 `aws s3 cp` 写 20 文件 → A/B **同时**可见 | ✅ 各 20 个 | 秒级 |
| 6 | 顺序覆盖（A 写→同步→B 覆盖同一文件） | ✅ 三方干净收敛到 B 版本 | 秒级 |
| 7 | 并发覆盖（A、B 相差 0.4ms 各写不同内容） | ✅ **last-writer-wins**，三方一致，无损坏 | 秒级 |
| 8 | A 删除 5 文件 → S3 删除 → B 同步删除 | ✅ **秒级双向传播** | 秒级 |

---

## 详细过程与关键发现

### 场景 1-4：基础双向同步（增 / 改）
1. A 写 10 个文件 → auto-export 秒级出现在 S3。
2. B 用 `--batch-import-meta-data-on-create` 建 DRA，挂载后直接看到 A 写的全部 10 个文件（经 S3 中转）。
3. B 写 5 个文件 → auto-export 到 S3 → **A 通过 auto-import 秒级同步到 B 的 5 个文件**。
4. A 读取 B 写的文件内容正确；HSM 状态为 `released exists archived`（元数据先导入为 released 占位，**首次读时惰性 restore** 拉回真实数据）。

### 场景 5：直接写 S3 → 双 FS 同时可见
- `aws s3 cp` 直接写 20 个对象到 bucket（真正的外部 S3 事件）。
- A 和 B **同时**通过 auto-import 秒级各看到 20 个。这是最标准的 auto-import 触发路径。

### 场景 6-7：写覆盖冲突（重点，纠正了「会乱」的推测）
- **顺序覆盖**：A 写 `VERSION-FROM-A` → S3 → B 读到后覆盖为 `VERSION-FROM-B` → S3 变 B 版本 → **A 也被 auto-import 更新为 B 版本**。三方最终一致。
- **并发覆盖**：A、B 在相差 0.4ms 内各写不同内容 → 最终 S3/A/B **全部收敛到 B 版本**（晚写的赢），连续观察 5 分钟稳定不变。
- **结论**：写冲突以 **last-writer-wins** 收敛，**不损坏、不报错、不脑裂**；代价是**丢更新**（DRA 是文件级整文件覆盖，无块级 diff、无版本合并、无冲突副本）。风险在业务层丢数据，而非存储层损坏。

### 场景 8：删除同步
- A 删 5 文件 → auto-export DELETED → S3 对应对象秒级删除 → auto-import DELETED → B 秒级删除对应文件。
- ⚠️ **前提：DRA 策略必须显式包含 `DELETED` 事件**。若只配 `NEW,CHANGED`，删除不会传播，S3 会留孤儿文件。

---

## 机制小结

- **同步媒介**：所有同步都经 S3 中转（`FS ⇄ S3`），FS 之间不直接通信。多个 FS 关联同一 bucket 即可通过 S3 间接互通。
- **auto-import 触发**：靠 S3 事件通知。无论是外部直接写 S3，还是另一个 FS 的 auto-export 写入 S3，都会触发本 FS 的 auto-import。
- **惰性加载（HSM）**：import 只导入元数据（`released` 占位），首次读触发 restore 从 S3 拉真实数据。适合「数据集 >> 集群容量」省钱场景。
- **一致性模型**：最终一致（eventual consistency）+ last-writer-wins。

## 生产注意事项

1. **多 FS 写同一文件会丢更新**：无冲突协调，靠应用层避免多写方写同一文件（或用不同 prefix 隔离写域）。
2. **DELETED 事件按需开启**：需要删除传播就必须在 import/export policy 里带 `DELETED`。
3. **root `/` DRA 独占**：用 `/` 做 file system path 时该 FS 只能有 1 个 DRA；要子目录多 DRA 需先删 root DRA。
4. **DRA 创建耗时**：root + batch-import 的 DRA 创建约 8-14 分钟（本次实测）。

## 复现命令要点

```bash
# 建 DRA（双向 + 删除传播 + 建时批量导入元数据）
aws fsx create-data-repository-association --region us-east-2 \
  --file-system-id <fs-id> \
  --file-system-path / \
  --data-repository-path s3://<bucket>/ \
  --batch-import-meta-data-on-create \
  --s3 'AutoImportPolicy={Events=[NEW,CHANGED,DELETED]},AutoExportPolicy={Events=[NEW,CHANGED,DELETED]}'

# 挂载
sudo mount -t lustre -o relatime,flock <fs-dns>@tcp:/<mount-name> /mnt/lustre
```
