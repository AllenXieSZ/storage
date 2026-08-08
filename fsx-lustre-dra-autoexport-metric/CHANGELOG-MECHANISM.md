# FSx for Lustre — Changelog（MDT 变更日志）实测解读

DRA AutoExport 的底层驱动机制。**Changelog 是 Lustre MDT 维护的一份有序变更日志**（不是普通文件，而是 MDT 上的记录流），按时间顺序记录文件系统上发生的所有元数据操作（创建/删除/改名/权限变更/文件关闭等），每条带递增序号。

- **区域**: us-east-2 (Ohio)，FSx Lustre PERSISTENT_2
- **客户端**: i7i.4xlarge，lustre-client 2.15.6，AL2023
- **MDT**: `<mountname>-MDT0000`
- **测试日期**: 2026-08-08

## 实测：制造变更后 Changelog 的内容

在 Lustre 挂载点做：建目录 → 建 f1.txt、f2.txt → 删 f1.txt，`lfs changelog <MDT名>` 立刻记录 4 条：

```
8610134 02MKDIR  11:09:33.572743305 2026.08.08 0x0 t=[0x200000417:0x1:0x0] ef=0xf u=0:0 nid=<CLIENT_IP>@tcp p=[0x200000007:0x1:0x0] cltest
8610135 01CREAT  11:09:33.575750391 2026.08.08 0x0 t=[0x200000417:0x2:0x0] ef=0xf u=0:0 nid=<CLIENT_IP>@tcp p=[0x200000417:0x1:0x0] f1.txt
8610136 01CREAT  11:09:33.579881120 2026.08.08 0x0 t=[0x200000417:0x3:0x0] ef=0xf u=0:0 nid=<CLIENT_IP>@tcp p=[0x200000417:0x1:0x0] f2.txt
8610137 06UNLNK  11:09:33.586660971 2026.08.08 0x1 t=[0x200000417:0x2:0x0] ef=0xf u=0:0 nid=<CLIENT_IP>@tcp p=[0x200000417:0x1:0x0] /cltest/f1.txt
```

## 字段逐个解读

| 字段 | 含义 |
|---|---|
| `8610134` | **递增记录序号**（consumer 靠它记录"处理到哪条"）|
| `02MKDIR` / `01CREAT` / `06UNLNK` | **操作类型码 + 名称**：MKDIR=建目录、CREAT=建文件、UNLNK=删除 |
| `11:09:33.572...` | 变更发生的**时间戳**（纳秒精度）|
| `t=[0x200000417:0x2:0x0]` | **target FID**（Lustre 文件唯一标识 File ID）|
| `p=[...]` | **parent FID**（父目录 FID）|
| `u=0:0` | 操作者 uid:gid |
| `nid=<CLIENT_IP>@tcp` | **发起变更的客户端网络 ID** |
| 末尾 `cltest`/`f1.txt` | 文件/目录名 |

## 关键观察（实证机制）

1. **序号已到 861 万+（8610134）**：说明该文件系统历史上处理过大量变更（此前的 100 万 import/export 测试留下），序号一直累积。

2. **首次查询返回 0 条，制造变更后立刻出现 4 条**：因为 **FSx 的 AutoExport consumer 持续消费并 purge（清除）已处理的旧记录**。查询那一刻旧记录已被清掉，只有新制造、尚未被 consumer 处理完的才显示。→ **直接实证「AutoExport = Changelog consumer」的机制**：处理完就 purge。

3. **这就是 AutoExport 感知"哪些文件要导出"的数据源**：CREAT → 触发 New 导出；UNLNK → 触发 Deleted 导出；文件关闭/元数据变更 → 触发 Changed 导出。与官方 New/Changed/Deleted 策略完全对应。

## 命令与权限边界（FSx 托管环境实测）

- ✅ **客户端可读 Changelog 记录**：`lfs changelog <MDT名>`（如 `lfs changelog abcd1234-MDT0000`）。
- ⚠️ `lctl changelog` 需交互式或带 `--device`，不能直接当查询用。
- ❌ **服务端参数 `mdd.*.changelog_users`（查看注册了哪些 consumer / 各自游标）在 FSx 托管环境下客户端访问不到**（报 `No such file or directory`）——那是 MDS 侧参数，AWS 不开放 MDS shell。
- Changelog 清除（purge）由 FSx 托管的 consumer 自动完成，用户无需（也无法）手动 `lctl changelog_clear`。

## 机制小结

- **Changelog = MDT 上的有序元数据变更记录流**，每条含：序号、操作类型、纳秒时间戳、target/parent FID、操作者、客户端 NID、文件名。
- 通用用途：`lustre_rsync` 增量备份、HSM、审计等都靠注册 changelog user（consumer）+ 游标做增量同步。
- **在 FSx 场景，DRA AutoExport 就是那个托管 consumer**——它读 Changelog 感知变更、导出到 S3、处理完 purge。AutoExport 积压时（见本目录 `AgeOfOldestQueuedMessage` 实测飙到 85 分钟），本质就是变更堆在 Changelog 里等消费。

## 数据来源

- Lustre 官方 / Lustre Wiki（Changelog、lustre_rsync、changelog_register 机制）
- AWS FSx for Lustre 文档（autoexport-data-repo-dra，New/Changed/Deleted 语义与"文件关闭才导出""atime/mtime 不触发"吻合 Changelog 语义）
- 实测：2026-08-08，us-east-2，`lfs changelog`

> ⚠️ 说明：「FSx AutoExport 内部注册为 changelog consumer」这一层，AWS 官方文档未逐字公开实现细节，但本次实测（旧记录被持续 purge、新变更才可见 + 操作类型与导出策略一一对应）强力支持该推断，标为**实测支持的机制推断**。
