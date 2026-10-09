# FSx for Lustre 文件变更审计：Changelog 方法（含与 S3 EventBridge 对比、导出 S3 + Athena 查询）

目标：记录 FSx for Lustre 上**谁、什么时间、对哪个文件**做了创建 / 删除 / 重命名等操作，并能事后查询。

> ⚠️ Changelog 是 Lustre 自带的能力，**FSx for Lustre 官方文档没有介绍**。本文全部内容为实测结果，行为可能随服务更新变化。

---

## 1. 测试环境

| 项目 | 配置 |
|---|---|
| 区域 | us-east-2 |
| 文件系统 | FSx for Lustre PERSISTENT_2，1200 GiB，Lustre 2.15，已配置 S3 关联（DRA）并开启自动导出 |
| 客户端 | Amazon Linux 2023，lustre-client 2.15.6，root |
| 查询 | S3 + Athena |

---

## 2. 什么是 Changelog

Lustre 的元数据服务器（MDT）会把每一次元数据变更按顺序记成一条日志，在客户端用 `lfs changelog` 读取。

**前提：文件系统必须配置了 S3 关联（DRA）并开启自动导出。** 实测：

| 文件系统 | 有无 Changelog |
|---|---|
| DRA 双向（自动导入 + 自动导出） | ✅ 有 |
| DRA 仅自动导出 | ✅ 有 |
| DRA 仅自动导入 | ❌ 无 |
| 没有 DRA | ❌ 无 |

有 Changelog 时，记录的是**整个文件系统**的变更，不只是 DRA 路径。

---

## 3. 快速使用

```bash
# 1. 查 MDT 名称
lfs mdts /mnt/lustre
# 0: divrbb4v-MDT0000_UUID ACTIVE   → MDT 名称 divrbb4v-MDT0000

# 2. 持续读取（root）
lfs changelog --follow divrbb4v-MDT0000
```

- 必须用 **root**；普通用户报 `Permission denied`。
- 必须 **`--follow` 持续读取**：记录在几秒内就会被清除，事后再执行 `lfs changelog` 基本是空的。

---

## 4. 能获取哪些内容

### 4.1 实测样例（一组操作逐条对应）

| 操作 | 记录 |
|---|---|
| `mkdir cl8` | `12955 02MKDIR 05:55:15.024429670 2026.10.09 0x0 t=[0x200000403:0x1928:0x0] ef=0xf u=0:0 nid=172.31.39.207@tcp p=[0x200000007:0x1:0x0] cl8` |
| `echo a > a.txt` | `12957 01CREAT 05:55:18.028357979 2026.10.09 0x0 t=[0x200000403:0x1929:0x0] ef=0xf u=0:0 nid=172.31.39.207@tcp p=[0x200000403:0x1928:0x0] a.txt` |
| `echo more >> a.txt` | `12958 12LYOUT ...` |
| `truncate -s 1 a.txt` | `12959 13TRUNC ...` |
| `chmod` / `chown` / `touch` | `12960 14SATTR ...`、`12961 14SATTR ...` |
| `ln -s a.txt lnk` | `12962 04SLINK ... lnk` |
| `ln a.txt hard` | `12963 03HLINK ... hard` |
| `mv a.txt b.txt` | `12964 08RENME ... b.txt s=[0x200000403:0x1929:0x0] sp=[...] /cl8/a.txt` |
| `cat b.txt` | **无记录** |
| `rm b.txt` | `12967 06UNLNK 05:55:21.970213014 2026.10.09 0x1 t=[0x200000403:0x1929:0x0] ef=0xf u=0:0 nid=172.31.39.207@tcp p=[...] /cl8/b.txt` |
| `rmdir cl8` | `12968 07RMDIR ... /cl8` |
| 普通用户（uid 1000）删除 | `4148 06UNLNK 05:51:36.321249230 2026.10.09 0x1 ... u=1000:1000 nid=172.31.39.207@tcp ... /cl5/user_slow.txt` |

### 4.2 字段

| 字段 | 示例 | 含义 |
|---|---|---|
| 序号 | `12967` | 递增编号，可用来检查是否有缺失 |
| 类型 | `06UNLNK` | 操作类型（见 4.3） |
| 时间 | `05:55:21.970213014 2026.10.09` | UTC，纳秒精度 |
| 标志 | `0x1` | 删除记录中 `0x1` = 文件真正被删除；`0x0` = 只删了一个硬链接 |
| `u=` | `1000:1000` | **操作者 uid:gid** |
| `nid=` | `172.31.39.207@tcp` | **发起操作的客户端 IP** |
| `t=` | `[0x200000403:0x1929:0x0]` | 文件 ID（FID） |
| `p=` | `[0x200000403:0x1928:0x0]` | 父目录 FID |
| 名称 / 路径 | `a.txt` / `/cl8/b.txt` | 创建类只有文件名；**删除、删目录、重命名带完整路径** |
| `s=` `sp=` | — | 重命名的源文件 FID、源父目录 FID |

文件名可通过 FID 解析成路径（文件未删除时）：
```bash
lfs fid2path /mnt/lustre '[0x200000403:0x1c:0x0]'
```

### 4.3 记录的操作类型

| 类型 | 操作 | 类型 | 操作 |
|---|---|---|---|
| `01CREAT` | 创建文件 | `07RMDIR` | 删除目录 |
| `02MKDIR` | 创建目录 | `08RENME` | 重命名 / 移动 |
| `03HLINK` | 创建硬链接 | `12LYOUT` | 首次写入数据 |
| `04SLINK` | 创建软链接 | `13TRUNC` | 截断 |
| `06UNLNK` | 删除文件 / 链接 | `14SATTR` | 改权限 / 属主 / 时间 |

**不记录**：读文件、追加写 / 覆盖写内容（只有首次写入的 `LYOUT`）。

### 4.4 完整性测试

| 测试 | 结果 |
|---|---|
| 200 个文件慢速 / 快速创建 + 删除 | 0 丢失 |
| 1000 个文件创建 → `rm -rf` | 0 丢失 |
| 3000 个文件创建 → `rm -rf` | 0 丢失 |
| 导出 S3 实测 72 条 | 0 丢失，序号连续 |
| 2000 个文件创建 → `rm -rf`（第一次测试） | **有丢失**（记到 949 创建 / 1149 删除），原因未确认 |

---

## 5. 与 S3 EventBridge 对比

另一种方法是在 DRA 关联的 S3 bucket 上开 EventBridge，Lustre 文件变化同步到 S3 后产生事件（见 [fsx-lustre-dra-eventbridge](../fsx-lustre-dra-eventbridge/README.md)）。

### 5.1 同一个删除操作，两种方法拿到的内容

**Changelog：**
```
12967 06UNLNK 05:55:21.970213014 2026.10.09 0x1 t=[0x200000403:0x1929:0x0] ef=0xf u=0:0 nid=172.31.39.207@tcp p=[0x200000403:0x1928:0x0] /cl8/b.txt
```

**S3 EventBridge：**
```json
{
  "detail-type": "Object Deleted",
  "time": "2026-10-09T04:17:22Z",
  "detail": {
    "bucket": { "name": "my-lustre-bucket" },
    "object": { "key": "bidir/evt/evtfile.txt", "version-id": "JdSL83A6TIt1KHpdkYl_wBaEGm7EuSFG" },
    "requester": "111122223333",
    "source-ip-address": "18.224.234.254",
    "reason": "DeleteObject",
    "deletion-type": "Delete Marker Created"
  }
}
```
（EventBridge 中的 `requester` / `source-ip-address` 是 FSx 服务，不是 Lustre 上操作的用户和客户端）

### 5.2 对比表

| 对比项 | Changelog | S3 EventBridge |
|---|---|---|
| 覆盖范围 | 整个文件系统 | 仅 DRA 关联路径 |
| **操作者 uid / gid** | ✅ 有 | ❌ 无 |
| **客户端 IP** | ✅ 有 | ❌ 无 |
| 时间精度 | 纳秒（操作发生时间） | 秒（同步到 S3 的时间） |
| 延迟 | 毫秒级 | 约 5–10 秒 |
| 新建文件 | ✅ | ✅ |
| 删除文件 | ✅（带完整路径） | ✅ |
| 删除目录 | ✅ | ❌（目录在 S3 中只是一个 `xxx/` 对象，实测 rm -rf 只看到文件删除） |
| 重命名 | ✅ 一条记录，带旧路径 + 新名字 | ⚠️ 表现为"删除旧对象 + 创建新对象"两条事件 |
| 改权限 / 属主 / 时间 | ✅ | ⚠️ 取决于是否同步到 S3 |
| 读文件 | ❌ | ❌ |
| 文件大小 | ❌ | ✅（创建事件中） |
| 部署 | 客户端常驻进程（root） | 无需客户端，纯 AWS 配置 |
| 可靠性 | 采集进程停止期间丢失，无法补回；实测出现过一次丢失 | S3 至少投递一次 |
| 官方支持 | ❌ 文档未提及 | ✅ |
| 前提 | DRA + 自动导出 | DRA + 自动导出 |

> 注：表中"删除目录""重命名"在 EventBridge 一侧的行为为推测（根据 S3 对象模型），本次未逐一实测。

### 5.3 如何选

| 需求 | 建议 |
|---|---|
| 要知道**谁**删的 / 从哪台机器删的 | Changelog |
| 要官方支持、可靠投递，只关心"哪些文件变了" | S3 EventBridge |
| 合规审计 | 两者同时用：EventBridge 兜底，Changelog 补充操作者 |

---

## 6. 集成：导出到 S3 + Athena 查询

### 6.1 架构

```
Lustre 客户端（root，只需一台）
 ├─ lustre-changelog@<MDT>.service   常驻：lfs changelog --follow → 解析成 JSON → 每 N 秒切一个 .jsonl.gz
 └─ lustre-changelog-upload.timer    每 1 分钟：上传 S3，成功后删除本地文件
                 │
                 ▼
s3://<BUCKET>/lustre-changelog/mdt=<MDT>/dt=YYYY-MM-DD/*.jsonl.gz
                 │
                 ▼
Athena 表 lustre_audit.changelog（SQL 查询）
```

- 采集必须**常驻**；"定时"的是上传。
- 先落本地再上传：S3 / 网络短暂故障不丢数据。

### 6.2 部署

前提：客户端已挂载 Lustre；实例角色有 `s3:PutObject` 到目标 bucket。

```bash
# 1. 安装脚本
install -m755 scripts/lustre-changelog-collector.py /usr/local/bin/
install -m755 scripts/lustre-changelog-upload.sh    /usr/local/bin/

# 2. 按 scripts/systemd-units.txt 创建 3 个 systemd 文件（把 <BUCKET> 换成自己的 bucket）

# 3. 启动（MDT 名称用 lfs mdts 查）
systemctl daemon-reload
systemctl enable --now lustre-changelog@divrbb4v-MDT0000.service lustre-changelog-upload.timer
```

| 文件 | 说明 |
|---|---|
| [scripts/lustre-changelog-collector.py](scripts/lustre-changelog-collector.py) | 采集 + 解析成 JSON + 按时间切片 |
| [scripts/lustre-changelog-upload.sh](scripts/lustre-changelog-upload.sh) | 按 `mdt=/dt=` 分区上传 S3 |
| [scripts/systemd-units.txt](scripts/systemd-units.txt) | 采集服务、上传服务、上传定时器 |
| [scripts/athena_ddl.sql](scripts/athena_ddl.sql) | Athena 建表 |
| [scripts/athena_queries.sql](scripts/athena_queries.sql) | 常用查询 |

`ROTATE_SEC`：多少秒切一个文件（默认 300，实测用 60）。没有记录的时间段不生成文件。

### 6.3 S3 中的数据（每行一条 JSON，实测）

```json
{"mdt":"divrbb4v-MDT0000","seq":13134,"type":"UNLNK","type_code":"06UNLNK","time":"2026-10-09T06:18:30.919731382Z","flags":"0x1","collector":"ip-172-31-39-207.us-east-2.compute.internal","target_fid":"[0x200000403:0x1995:0x0]","ef":"0xf","uid":1000,"gid":1000,"client_nid":"172.31.39.207@tcp","client_ip":"172.31.39.207","parent_fid":"[0x200000403:0x1962:0x0]","path":"/clarch/user2.txt"}
{"mdt":"divrbb4v-MDT0000","seq":13133,"type":"RENME","type_code":"08RENME","time":"2026-10-09T06:18:30.918221737Z","flags":"0x0","collector":"ip-172-31-39-207.us-east-2.compute.internal","target_fid":"[0:0x0:0x0]","ef":"0xf","uid":1000,"gid":1000,"client_nid":"172.31.39.207@tcp","client_ip":"172.31.39.207","parent_fid":"[0x200000403:0x1962:0x0]","name":"user2.txt","source_fid":"[0x200000403:0x1995:0x0]","source_parent_fid":"[0x200000403:0x1962:0x0]","old_path":"/clarch/user.txt"}
```

| 字段 | 含义 |
|---|---|
| `seq` | 序号 |
| `type` | CREAT / MKDIR / UNLNK / RMDIR / RENME / SATTR / TRUNC / LYOUT / HLINK / SLINK |
| `time` | 操作时间（UTC，纳秒） |
| `uid` `gid` | 操作者 |
| `client_ip` | 客户端 IP |
| `path` | 删除 / 删目录的完整路径 |
| `name` | 创建的文件名；重命名后的新名字 |
| `old_path` | 重命名前的完整路径 |
| `flags` | 删除记录中 `0x1` = 文件真正被删除 |

### 6.4 Athena 建表

```sql
CREATE DATABASE IF NOT EXISTS lustre_audit;

CREATE EXTERNAL TABLE IF NOT EXISTS lustre_audit.changelog (
  seq bigint, type string, type_code string, `time` string, flags string, collector string,
  target_fid string, parent_fid string, source_fid string, source_parent_fid string,
  uid int, gid int, client_nid string, client_ip string,
  name string, path string, old_path string )
PARTITIONED BY (mdt string, dt string)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://<BUCKET>/lustre-changelog/'
TBLPROPERTIES (
  'projection.enabled'='true',
  'projection.mdt.type'='injected',
  'projection.dt.type'='date', 'projection.dt.format'='yyyy-MM-dd', 'projection.dt.range'='2026-01-01,NOW',
  'storage.location.template'='s3://<BUCKET>/lustre-changelog/mdt=${mdt}/dt=${dt}/');
```
- 用分区投影：新文件上传后**直接可查**，无需 `MSCK REPAIR` / Glue Crawler。
- 查询时 WHERE 中必须指定 `mdt`。

### 6.5 查询样例（实测结果）

测试操作：建 50 个文件 → 普通用户（uid 1000）建 / 改名 / 删除 `user.txt` → root 改名 `f1.txt`、删 `f2` `f3` → `rm -rf` 整个目录。

**谁删了哪些文件**
```sql
SELECT "time", uid, client_ip, type, path FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09' AND type IN ('UNLNK','RMDIR') AND flags='0x1'
ORDER BY seq;
```
| time | uid | client_ip | type | path |
|---|---|---|---|---|
| 2026-10-09T06:18:30.919731382Z | 1000 | 172.31.39.207 | UNLNK | /clarch/user2.txt |
| 2026-10-09T06:18:30.924751823Z | 0 | 172.31.39.207 | UNLNK | /clarch/f2.txt |
| 2026-10-09T06:18:30.925292080Z | 0 | 172.31.39.207 | UNLNK | /clarch/f3.txt |
| … | | | | |

**某个文件的完整历史**
```sql
SELECT "time", type, uid, client_ip, coalesce(path, old_path, name) AS f FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
  AND (path LIKE '%user%' OR old_path LIKE '%user%' OR name LIKE 'user%')
ORDER BY seq;
```
| time | type | uid | client_ip | f |
|---|---|---|---|---|
| 06:18:30.914924380Z | CREAT | 1000 | 172.31.39.207 | user.txt |
| 06:18:30.918221737Z | RENME | 1000 | 172.31.39.207 | /clarch/user.txt（→ user2.txt） |
| 06:18:30.919731382Z | UNLNK | 1000 | 172.31.39.207 | /clarch/user2.txt |

**重命名记录**
| time | uid | old_path | name |
|---|---|---|---|
| 06:18:30.918221737Z | 1000 | /clarch/user.txt | user2.txt |
| 06:18:30.923168924Z | 0 | /clarch/f1.txt | f1_renamed.txt |

**按用户统计**
| uid | type | n |
|---|---|---|
| 0 | CREAT | 50 |
| 0 | UNLNK | 16 |
| 0 | RENME / MKDIR / SATTR | 1 / 1 / 1 |
| 1000 | CREAT / RENME / UNLNK | 1 / 1 / 1 |

**检查是否漏记录**：见 [scripts/athena_queries.sql](scripts/athena_queries.sql) 第 5 条（按 `seq` 找缺口）。

### 6.6 集成实测结果

| 项目 | 结果 |
|---|---|
| Changelog 记录 | 72 条（序号 13080–13151） |
| S3 中记录 | 72 条，**序号连续，0 缺失** |
| 操作 → Athena 可查 | 约 1–2 分钟（切片 60 秒 + 上传周期 1 分钟） |
| Athena 单次查询 | 约 0.6 秒 |
| 数据量 | 压缩后约 23 字节 / 条（估算 1000 万次操作 / 天 ≈ 230 MB / 天） |

---

## 7. 限制

1. **非官方功能**：FSx for Lustre 文档未提及 Changelog，行为可能变化。
2. **只有配置了 DRA 自动导出的文件系统才有 Changelog。**
3. **记录只保留几秒**：必须常驻采集；采集停止期间的变更**丢失且无法补回**。
4. **可能丢记录**：批量操作测试中出现过一次丢失。用序号缺口查询监控。
5. **采集客户端是单点**：只在一台客户端上运行（多台会重复，可按 `seq` 去重）；这台宕机期间的变更丢失。
6. **需要 root 权限。**
7. **不能自行配置**：无法注册自己的 Changelog 用户，也不能选择记录哪些类型。
8. **不记录读取和内容修改**：只记首次写入（LYOUT）和截断（TRUNC）。
9. **创建类记录只有文件名**，没有完整路径（可用父目录 FID 解析，或关联同目录其他记录）。
10. **多 MDT 文件系统**：每个 MDT 需要一个采集实例。
11. 建议给 S3 前缀配置生命周期规则控制成本。
