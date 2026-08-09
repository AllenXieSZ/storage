# FSx for Lustre — 2.12 升级到 2.15 后能否配置 Metadata IOPS（实测）

验证一个常见误区：**FSx Lustre 2.12 文件系统原地升级到 2.15 后，是否就能配置/更新 Metadata IOPS（enhanced metadata / DNE）**。

- **区域**: us-east-2 (Ohio)
- **测试对象**: 全新创建的 Lustre **2.12**, Persistent_2, 1.2 TiB, 250 MB/s/TiB（创建时未指定 metadata configuration —— 2.12 本就不支持指定）
- **测试日期**: 2026-08-08

## 结论（一句话）

❌ **不行。** 能否配置 Metadata IOPS 的**唯一判据是「文件系统创建时是否指定了 metadata configuration」，与当前 Lustre 版本号无关**。2.12 创建的文件系统即使原地升级到 2.15，`MetadataConfiguration` 永远是 `null`，**升级时不能指定、升级后也不能添加/更新**。

## 实测步骤与结果

### 测试点 1：升级到 2.15 时**同时**指定 Metadata IOPS → ❌ 失败
```bash
aws fsx update-file-system --file-system-id <FS_ID> \
  --file-system-type-version 2.15 \
  --lustre-configuration '{"MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":6000}}' \
  --region us-east-2
```
报错：
```
BadRequest: Updating metadata configuration is not supported on file systems
created without specifying a metadata configuration.
```

### 版本升级本身：✅ 成功
纯版本升级（不带 metadata 参数）成功：
```bash
aws fsx update-file-system --file-system-id <FS_ID> \
  --file-system-type-version 2.15 --region us-east-2
```
- 2.12 → **2.15**，Lifecycle: AVAILABLE → UPDATING → AVAILABLE，`AdministrativeAction=FILE_SYSTEM_UPDATE` Status COMPLETED。
- **耗时约 12 分钟**（官方称通常 <30 分钟）。升级期间 FS 短暂不可用，client 请求透明重试。
- 升级后 `MetadataConfiguration` 仍为 **`null`**。

### 测试点 2：升级到 2.15 **完成后**再配置 Metadata IOPS → ❌ 失败（两种模式都不行）
```bash
# 2a. USER_PROVISIONED 指定 IOPS
aws fsx update-file-system --file-system-id <FS_ID> \
  --lustre-configuration '{"MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":6000}}' --region us-east-2
# 2b. AUTOMATIC 模式
aws fsx update-file-system --file-system-id <FS_ID> \
  --lustre-configuration '{"MetadataConfiguration":{"Mode":"AUTOMATIC"}}' --region us-east-2
```
两条命令均报同样的错：
```
BadRequest: Updating metadata configuration is not supported on file systems
created without specifying a metadata configuration.
```

## 汇总表

| 场景 | 结果 |
|---|---|
| 2.12 创建时指定 metadata IOPS | ❌ 2.12 无此特性 |
| 升级到 2.15 **时**同时指定 IOPS | ❌ BadRequest |
| 升级到 2.15 **后** USER_PROVISIONED 配置 | ❌ BadRequest |
| 升级到 2.15 **后** AUTOMATIC 配置 | ❌ BadRequest |
| 纯版本升级 2.12 → 2.15 | ✅ 成功（~12 min） |

## 官方文档佐证（原文）

> "**Enhanced metadata is available only for 2.15 file systems.** You can increase metadata performance only on FSx for Lustre file systems created with the Persistent 2 deployment type and a metadata configuration specified. **You cannot add or update the metadata configuration for an FSx for Lustre file system if the metadata configuration is not specified at the time of file system creation.** This also applies to file systems restored from backups of 2.12 file systems which did not support enhanced metadata performance..."

来源：`docs.aws.amazon.com/fsx/latest/LustreGuide/managing-metadata-performance.html`

## 唯一可行办法

想要可配置 Metadata IOPS，**必须全新创建**满足三条件的文件系统：
1. Lustre **2.15**
2. **Persistent_2** 部署类型
3. **创建时显式指定 `MetadataConfiguration`**（`AUTOMATIC` 或 `USER_PROVISIONED`）

已有 2.12 数据可通过 DRA/S3 或 `lfs`/rsync 迁移到新文件系统。升级路径无法补救。

## 元数据配置模式（创建时可选）

- **AUTOMATIC**：FSx 按存储容量自动 provision/scale Metadata IOPS（仅 SSD；Intelligent-Tiering 不支持）。
- **USER_PROVISIONED**：自行指定 Metadata IOPS 数值。
- 扩 metadata IOPS 两次请求间隔需 ≥6 小时；扩容时 FS 短暂不可用、client 透明重试。

## 数据来源

- 实测：2026-08-08，us-east-2，`aws fsx create-file-system` / `update-file-system` / `describe-file-systems`
- AWS 官方文档：`managing-metadata-performance.html`、`managing-lustre-version.html`
