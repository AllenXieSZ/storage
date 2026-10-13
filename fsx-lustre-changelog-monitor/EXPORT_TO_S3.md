# Lustre Changelog 定时导出到 S3 + Athena 查询（实测）

把 FSx for Lustre 的 Changelog 持续采集下来，按时间切片上传 S3，再用 Athena 用 SQL 查"谁、什么时候、删/改了哪个文件"。

Changelog 本身的说明和限制见 [README.md](README.md)。

## 1. 架构

```
Lustre 客户端（root）
 ├─ lustre-changelog@<MDT>.service   常驻：lfs changelog --follow → 解析成 JSON → 每 N 秒切一个 .jsonl.gz
 └─ lustre-changelog-upload.timer    每 1 分钟：把切好的文件上传 S3，成功后删本地
                     │
                     ▼
s3://<BUCKET>/lustre-changelog/mdt=<MDT>/dt=YYYY-MM-DD/<MDT>_<host>_<时间>.jsonl.gz
                     │
                     ▼
Athena 表 lustre_audit.changelog（分区投影，无需 MSCK / Crawler）
```

- 采集必须**常驻**（Changelog 记录几秒内就会被清除，定时去拉会丢）；"定时"的是**上传**。
- 本地先落盘再上传：S3 / 网络短暂故障不会丢数据。

## 2. 部署步骤

前提：客户端已挂载 Lustre；实例角色有目标 bucket 的 `s3:PutObject` 权限。

### 2.1 安装脚本
```bash
install -m755 scripts/lustre-changelog-collector.py /usr/local/bin/
install -m755 scripts/lustre-changelog-upload.sh    /usr/local/bin/
lfs mdts /mnt/lustre        # 得到 MDT 名称，如 divrbb4v-MDT0000
```

### 2.2 采集服务（每个 MDT 一个实例）
```ini
# /etc/systemd/system/lustre-changelog@.service
[Unit]
Description=Lustre changelog collector for %i
After=network-online.target remote-fs.target
[Service]
Environment=ROTATE_SEC=300
ExecStart=/usr/bin/python3 /usr/local/bin/lustre-changelog-collector.py %i
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
```
`ROTATE_SEC` = 多少秒切一个文件（实测用 60，生产建议 300）。没有记录的时间段不生成文件。**已实测** 300：200 ops/s 下每个文件 1.4–1.8 MB（gz），业务记录 0 缺失（第 11 节 T4）。

可选 `ROTATE_MAX_MB`（压缩前大小，默认 0 = 不启用）：满 `ROTATE_SEC` 或满大小先到先切，例如 `Environment=ROTATE_SEC=300 ROTATE_MAX_MB=64`（第 11 节 T8）。

### 2.3 上传定时器
```ini
# /etc/systemd/system/lustre-changelog-upload.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/lustre-changelog-upload.sh <BUCKET> lustre-changelog
```
```ini
# /etc/systemd/system/lustre-changelog-upload.timer
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
```

### 2.4 启动

**单 MDT：**
```bash
systemctl daemon-reload
systemctl enable --now lustre-changelog@divrbb4v-MDT0000.service lustre-changelog-upload.timer
```

**多 MDT（自动为每个 MDT 启动一个采集实例）：**
```bash
systemctl daemon-reload
for m in $(lfs mdts /mnt/lustre | awk '/ACTIVE/{sub(/_UUID$/,"",$2); print $2}'); do
  systemctl enable --now lustre-changelog@$m.service
done
systemctl enable --now lustre-changelog-upload.timer   # 上传 timer 只需一个，所有 MDT 的文件一起上传

# 检查：每个 MDT 都应有一个 running 实例
lfs mdts /mnt/lustre
systemctl list-units 'lustre-changelog@*' --no-pager
```

- **一个采集实例只读一个 MDT**（`lfs changelog --follow <MDT>`），不会自动读其它 MDT。
- **每个 MDT 的 seq 各自独立**；S3 / Athena 按 `mdt=` 分区，缺口检查需按 MDT 分别做。
- **扩容 Metadata IOPS 后要重新执行上面的循环**：Metadata IOPS 超过 12000 时 FSx 会增加 metadata server（[官方文档](https://docs.aws.amazon.com/fsx/latest/LustreGuide/managing-metadata-performance.html)），新 MDT 不采集会漏记录，且缺口检查发现不了。
- **已实测**（3 MDT，见第 10 节）：上面的循环原文执行即为 3 个 MDT 各启动 1 个 running 实例，3 个 `mdt=` 分区都有数据，每个 MDT seq 各自连续 0 缺口。

## 3. S3 中的数据格式

路径：
```
s3://<BUCKET>/lustre-changelog/mdt=divrbb4v-MDT0000/dt=2026-10-09/divrbb4v-MDT0000_ip-172-31-39-207..._20261009T061825Z.jsonl.gz
```

每行一条 JSON（实测样例）：
```json
{"mdt":"divrbb4v-MDT0000","seq":13134,"type":"UNLNK","type_code":"06UNLNK","time":"2026-10-09T06:18:30.919731382Z","flags":"0x1","collector":"ip-172-31-39-207.us-east-2.compute.internal","target_fid":"[0x200000403:0x1995:0x0]","ef":"0xf","uid":1000,"gid":1000,"client_nid":"172.31.39.207@tcp","client_ip":"172.31.39.207","parent_fid":"[0x200000403:0x1962:0x0]","path":"/clarch/user2.txt"}
{"mdt":"divrbb4v-MDT0000","seq":13133,"type":"RENME","type_code":"08RENME","time":"2026-10-09T06:18:30.918221737Z","flags":"0x0","collector":"ip-172-31-39-207.us-east-2.compute.internal","target_fid":"[0:0x0:0x0]","ef":"0xf","uid":1000,"gid":1000,"client_nid":"172.31.39.207@tcp","client_ip":"172.31.39.207","parent_fid":"[0x200000403:0x1962:0x0]","name":"user2.txt","source_fid":"[0x200000403:0x1995:0x0]","source_parent_fid":"[0x200000403:0x1962:0x0]","old_path":"/clarch/user.txt"}
```

| 字段 | 含义 |
|---|---|
| `seq` | Changelog 序号（递增，可用来检查是否有缺失） |
| `type` | CREAT / MKDIR / UNLNK / RMDIR / RENME / SATTR / TRUNC / LYOUT / HLINK / SLINK |
| `time` | 操作时间（UTC，纳秒） |
| `uid` `gid` | 操作者 |
| `client_ip` | 发起操作的客户端 IP |
| `path` | UNLNK / RMDIR 的完整路径（相对文件系统根）。**多 MDT 时只有部分记录有完整路径**，其余记录只有文件名（放在 `name`），见第 10 节 |
| `name` | CREAT / MKDIR 的文件名；RENME 的新名字 |
| `old_path` | RENME 的原完整路径（多 MDT 时可能只是原文件名，见第 10 节） |
| `flags` | UNLNK/RMDIR 中 `0x1` = 文件真正被删除（最后一个链接） |

## 4. Athena 建表

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
使用分区投影：新的一天 / 新文件上传后**直接可查**，不需要 `MSCK REPAIR` 或 Glue Crawler。
查询时必须在 WHERE 里指定 `mdt`（injected 投影要求）。**已实测**：`mdt='...'` 和 `mdt IN ('...-MDT0000','...-MDT0001','...-MDT0002')` 都可以；不写 `mdt` 或用 `mdt LIKE` 会报 `CONSTRAINT_VIOLATION`。多 MDT 查询用 `IN` 列出全部 MDT。

## 5. 查询样例（实测结果）

测试操作：建 50 个文件 → 普通用户 ec2-user 建 / 改名 / 删除 `user.txt` → root 改名 `f1.txt`、删 `f2` `f3` → `rm -rf` 整个目录。

### 谁删了哪些文件
```sql
SELECT "time", uid, client_ip, type, path
FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
  AND type IN ('UNLNK','RMDIR') AND flags='0x1'
ORDER BY seq LIMIT 10;
```
| time | uid | client_ip | type | path |
|---|---|---|---|---|
| 2026-10-09T06:18:30.919731382Z | 1000 | 172.31.39.207 | UNLNK | /clarch/user2.txt |
| 2026-10-09T06:18:30.924751823Z | 0 | 172.31.39.207 | UNLNK | /clarch/f2.txt |
| 2026-10-09T06:18:30.925292080Z | 0 | 172.31.39.207 | UNLNK | /clarch/f3.txt |
| 2026-10-09T06:18:30.928020289Z | 0 | 172.31.39.207 | UNLNK | /clarch/f47.txt |
| … | | | | |

### 某个文件的完整历史
```sql
SELECT "time", type, uid, client_ip, coalesce(path, old_path, name) AS f
FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
  AND (path LIKE '%user%' OR old_path LIKE '%user%' OR name LIKE 'user%')
ORDER BY seq;
```
| time | type | uid | client_ip | f |
|---|---|---|---|---|
| 06:18:30.914924380Z | CREAT | 1000 | 172.31.39.207 | user.txt |
| 06:18:30.918221737Z | RENME | 1000 | 172.31.39.207 | /clarch/user.txt（→ user2.txt） |
| 06:18:30.919731382Z | UNLNK | 1000 | 172.31.39.207 | /clarch/user2.txt |

### 重命名记录
```sql
SELECT "time", uid, old_path, name FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09' AND type='RENME';
```
| time | uid | old_path | name |
|---|---|---|---|
| 06:18:30.918221737Z | 1000 | /clarch/user.txt | user2.txt |
| 06:18:30.923168924Z | 0 | /clarch/f1.txt | f1_renamed.txt |

### 按用户统计操作
```sql
SELECT uid, type, count(*) AS n FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
GROUP BY uid, type ORDER BY uid, n DESC;
```
| uid | type | n |
|---|---|---|
| 0 | CREAT | 50 |
| 0 | UNLNK | 16 |
| 0 | RENME / MKDIR / SATTR | 1 / 1 / 1 |
| 1000 | CREAT / RENME / UNLNK | 1 / 1 / 1 |

### 检查有没有漏记录（序号缺口）
```sql
SELECT prev_seq, seq, seq - prev_seq - 1 AS missing FROM (
  SELECT seq, lag(seq) OVER (ORDER BY seq) AS prev_seq
  FROM (SELECT DISTINCT seq FROM lustre_audit.changelog WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'))
WHERE seq - prev_seq > 1;
```
采集器重启后可能重复读到已采集的记录，所以先按 `seq` 去重（见第 7 节第 3 条）。缺口里如果只有 HSM 类型，对审计无影响（第 11 节 T1/T4）。

## 6. 实测结果

| 项目 | 结果 |
|---|---|
| 操作数 | 72 条 Changelog（序号 13080–13151） |
| S3 中记录数 | 72 条，**序号连续，0 缺失** |
| 采集 → 文件可上传 | ≤ ROTATE_SEC（实测 60 秒） |
| 上传 → S3 | ≤ 1 分钟（timer 周期） |
| 操作 → Athena 可查 | 约 1–2 分钟 |
| Athena 单次查询 | 0.6 秒左右（扫描 1.7 KB） |
| 服务重启次数 | 0 |

## 7. 注意事项与限制

1. **只能在一台客户端上运行采集**，多台会产生重复记录（可用 `seq` 去重）。这台客户端是单点：它宕机期间的变更会丢失。
2. **采集进程停止期间的变更无法补回**（Changelog 几秒即被清除）。**已实测**：`kill -9` 丢约 0.7 秒、机器强制重启丢约 8 秒的记录，均可被上面的"序号缺口"查询发现（第 11 节 T5）。
3. **采集器重启后可能重复读到已采集的记录**（从 MDT 上仍保留的最早记录重新读），查询需按 `seq` 去重（`count(DISTINCT seq)` / `SELECT DISTINCT`）。
4. **批量操作**：**已实测** `rm -rf` 2000 / 10000 / 50000 个文件、`cp -r` 10000 个文件均 0 丢（峰值约 3000 条/秒，第 11 节 T7）。目前观察到的缺失只有两类：采集中断，以及 HSM 类型记录（由导出流程产生、清除很快，对审计无影响）。
5. **⚠️ 严禁在任何客户端执行 `lfs changelog_clear`**。**已实测**：客户端 root 执行 `lfs changelog_clear <MDT> cl1 0` 会成功（`cl1` 是 DRA 自动导出使用的 changelog 用户），导致执行期间新建的文件**没有导出到 S3**（900 个只导出 52 个）、采集也漏记录，且该 MDT 之后**不再清除 changelog**（2 小时未恢复）。漏导出的文件可用 `lfs hsm_archive` 补导出（第 11 节 T2）。建议写入运维规范，并监控 `lfs changelog <MDT> | head -1` 的最早记录时间（正常应在 10 秒内）。
6. **`lfs changelog --follow` 只读，不影响 DRA 自动导出**。**已实测**：有 / 无读者时导出完成 38 秒 / 40 秒，S3 对象、大小、md5 全部一致；多个读者可同时读同一 MDT，互不影响（第 11 节 T1）。
7. **多 MDT 文件系统**：每个 MDT 起一个 `lustre-changelog@<MDT>` 实例（命令见 2.4）。**扩容 Metadata IOPS 后检查 `lfs mdts`，为新增 MDT 启动实例。** **已实测**（第 10 节）：Metadata IOPS 36000 = 3 个 MDT；一个操作只记在一个 MDT 上，查询要用 `mdt IN (...)` 覆盖全部 MDT；跨 MDT rename 只记在目标目录所在 MDT。
8. **CREAT/MKDIR 只有文件名没有完整路径**，可通过 `parent_fid` 在文件系统上 `lfs fid2path` 解析，或用同目录下的 UNLNK/RENME 记录关联。
9. **只有开了自动导出 DRA 的文件系统才有 Changelog**（见 README）。
   - **建议：如果业务本身不需要 DRA，可以建一个"空的"自动导出 DRA，只用来开启 Changelog。**
   - **做法：新建一个空 S3 bucket（或空前缀），DRA 关联到一个业务不使用的空目录（如 `/.audit-dra` ↔ `s3://<audit-bucket>/dummy/`），只开 AutoExport（NEW / CHANGED / DELETED），不开 AutoImport。**
   - **实测 Changelog 记录的是整个文件系统的变更，不限于 DRA 路径**，所以业务目录的操作照样被审计；业务数据不会导出到 S3，基本无额外存储成本。
   - **已实测**：HSM 记录由自动导出产生，只涉及 DRA 路径下的文件，DRA 指向空目录时 HSM 噪声消失。实测同样操作（建 200 个 1MB 文件、覆盖写 50、rename 20、删除 20、mkdir 5）：DRA 外目录 HSM 0 条（CREAT 200 / RENME 20 / UNLNK 20 / MKDIR 6 照常记录）；DRA 内目录 HSM 540 条（180 个留存文件各 3 条），CREAT/RENME/UNLNK/MKDIR 条数与 DRA 外相同；S3 上只有 DRA 内的对象。
   - 仅适用于 PERSISTENT_2（支持 DRA 的部署类型）。仅导出 DRA 创建约 3 分钟。
10. **Changelog 不是 FSx for Lustre 官方文档的功能**，行为可能变化。
11. 数据量估算：本次每条记录压缩后约 23 字节（72 条 1679 字节）；每天 1000 万次操作约 230 MB/天。
12. 建议给 S3 前缀配置生命周期规则（如 90 天后转 Glacier / 1 年后删除）。

## 8. 文件

| 文件 | 说明 |
|---|---|
| [scripts/lustre-changelog-collector.py](scripts/lustre-changelog-collector.py) | 采集 + 解析 + 切片（2026-10-11 修正读缓冲问题，见 10.3；2026-10-12 增加每秒落盘、启动时转存遗留 `.part`、SIGTERM 正常退出、可选 `ROTATE_MAX_MB`，见 11 T5/T8） |
| [scripts/lustre-changelog-upload.sh](scripts/lustre-changelog-upload.sh) | 上传到 S3 |
| [scripts/athena_ddl.sql](scripts/athena_ddl.sql) | Athena 建表 |
| [scripts/lustre_load.py](scripts/lustre_load.py) | 规模测试负载脚本（限速混合文件操作） |
| [scripts/scale_analyze.py](scripts/scale_analyze.py) | 规模测试分析（seq 缺口 + 与负载对账） |
| [scripts/reliability/](scripts/reliability/) | 第 11 节可靠性测试脚本 |

## 9. 大规模测试

在 5 台客户端合计 200 ops/s、持续 30 分钟的混合文件负载下，验证本方案**是否丢记录、延迟多少、采集端占多少资源**。

### 9.1 环境

| 项目 | 配置 |
|---|---|
| 区域 / AZ | us-east-2 / us-east-2c |
| 文件系统 | FSx for Lustre PERSISTENT_2，**9600 GiB**，250 MB/s/TiB，Lustre 2.15，1 个 MDT |
| DRA | `/work` ↔ `s3://<bucket>/work/`，仅自动导出（NEW / CHANGED / DELETED） |
| 客户端 | **5 台 m6i.xlarge**，AL2023，lustre-client 2.15，root |
| 采集器 | 跑在其中 1 台（c1）：`lustre-changelog@<MDT>.service`（ROTATE_SEC=60）+ 每分钟上传 timer |
| Athena | 表 `lustre_audit.changelog`（DDL 见 [scripts/athena_ddl.sql](scripts/athena_ddl.sql)） |

### 9.2 负载

| 项目 | 值 |
|---|---|
| 并发 | 5 客户端 × 8 线程，每台限速 40 ops/s → **合计 200 ops/s** |
| 时长 | 1800 s（30 分钟） |
| 文件大小 | 2 MB |
| 比例 | 写（新建）40% / 读 30% / 原地覆盖写 10% / O_TRUNC 重写 10% / rename 5% / 删除 5% |
| 脚本 | [scripts/lustre_load.py](scripts/lustre_load.py) |

#### 负载结果：360000 次操作，0 失败，实际 200.0 ops/s

| 操作 | 次数 | P50 | P99 |
|---|---:|---:|---:|
| write（新建 2MB） | 144383 | 3.28 ms | 4.70 ms |
| read（读 2MB） | 107798 | 6.60 ms | 8.64 ms |
| overwrite | 35848 | 3.28 ms | 4.75 ms |
| trunc_rewrite | 35841 | 3.74 ms | 5.36 ms |
| rename | 18004 | 1.69 ms | 2.68 ms |
| delete | 18126 | 1.03 ms | 1.72 ms |

### 9.3 结果

#### 9.3.1 Changelog 完整性

| 项目 | 结果 |
|---|---|
| 采集记录总数 | **897163 条**（seq 1 – 897163） |
| seq 连续性 | **0 缺口 / 0 重复** |
| 记录速率 | 平均 498 条/s，峰值分钟 508 条/s |

按 type 统计：

| type | 条数 | 说明 |
|---|---:|---|
| HSM | 645130 | 自动导出 DRA 产生的 HSM 状态变化（占 72%） |
| CREAT | 144390 | 新建文件 |
| TRUNC | 35842 | O_TRUNC 重写 |
| MTIME | 35624 | 原地覆盖写 |
| UNLNK | 18127 | 删除 |
| RENME | 18004 | 重命名 |
| MKDIR | 45 | 建目录 |
| SATTR | 1 | |

#### 9.3.2 与负载对账（按文件名逐条匹配）

| 负载操作 | 次数 | 对应记录 | 命中率 |
|---|---:|---|---:|
| write | 144383 | CREAT | **100%** |
| rename | 18004 | RENME | **100%** |
| delete | 18126 | UNLNK | **100%** |
| overwrite + trunc_rewrite | 35848 + 35841 | TRUNC 35842 / MTIME 35624 | — |
| read | 107798 | 无记录（预期） | — |

（多出的少量 CREAT/UNLNK 是延迟探针文件。）

#### 9.3.3 延迟：操作 → Athena 可查

负载期间每 ~4 分钟在 c2 上建一个唯一文件，每 10 秒查一次 Athena 直到查到该 CREAT 记录：

| 探针 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Athena 可见延迟 | 80 s | 112 s | 111 s | 127 s | 111 s | 116 s |

**80 – 127 秒**，符合 ROTATE_SEC(60) + 上传周期(60) + 查询轮询(10) 的上限。

#### 9.3.4 采集端资源（c1，pidstat 每 10 秒采样，30 分钟）

| 进程 | 平均 CPU | 峰值 CPU | RSS |
|---|---:|---:|---:|
| python3 collector | **~1.0%** | 1.4% | **~12 MB** |
| lfs changelog --follow | 0.1% | 0.2% | 1.7 MB |

#### 9.3.5 数据量

| 项目 | 值 |
|---|---|
| 30 分钟 S3 文件 | 32 个 .jsonl.gz，共 **15.2 MB**（压缩后） |
| 单文件（1 分钟） | 平均 475 KB，最大 519 KB |
| 每条记录 | ~17 字节（压缩后） |
| 外推（同负载持续） | **~730 MB/天** |

#### 9.3.6 Athena 查询（30 分钟全量 ~90 万条，单日分区）

| 查询 | 结果 | 耗时 | 扫描量 |
|---|---|---:|---:|
| 谁删了哪些文件（UNLNK/RMDIR，LIMIT） | 返回 time/uid/client_ip/path | 2.5 s | 15.2 MB |
| 删除总数 | 18131 | 1.3 s | 15.2 MB |
| seq 缺口检查 | 0 缺口 / 0 缺失 | 2.0 s | 15.2 MB |
| 按 uid + type 统计 | 见 3.1 | 1.2 s | 15.2 MB |
| count / min / max seq | 897183 / 1 / 897183 | 1.0 s | 15.2 MB |

（查询在负载结束后进行，计数含少量探针/收尾记录。gzip JSON 不可列裁剪，每次扫描整个分区。）

#### 9.3.7 DRA 自动导出（可选项）

负载结束后：Lustre `/work` 文件数 **126263** = S3 `work/` 对象数 **126263**（另 45 个目录对象），**完全一致**。

### 9.4 复现命令

#### 9.4.1 挂载（每台客户端）
```bash
dnf install -y lustre-client sysstat
mkdir -p /mnt/lustre
mount -t lustre -o relatime,flock <FS_ID>.fsx.us-east-2.amazonaws.com@tcp:/<MOUNT_NAME> /mnt/lustre
lfs mdts /mnt/lustre          # 得到 MDT 名称，如 35brbb4v-MDT0000
```

#### 9.4.2 部署采集器（仅 c1）
```bash
install -m755 lustre-changelog-collector.py /usr/local/bin/
install -m755 lustre-changelog-upload.sh    /usr/local/bin/

cat > /etc/systemd/system/lustre-changelog@.service <<'EOF'
[Unit]
Description=Lustre changelog collector for %i
After=network-online.target remote-fs.target
[Service]
Environment=ROTATE_SEC=60
ExecStart=/usr/bin/python3 /usr/local/bin/lustre-changelog-collector.py %i
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/lustre-changelog-upload.service <<'EOF'
[Service]
Type=oneshot
ExecStart=/usr/local/bin/lustre-changelog-upload.sh <BUCKET> lustre-changelog
EOF

cat > /etc/systemd/system/lustre-changelog-upload.timer <<'EOF'
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now lustre-changelog@<MDT>.service lustre-changelog-upload.timer

# 资源采样
pidstat -h -r -u -p $(pgrep -f lustre-changelog-collector.py),$(pgrep -f 'lfs changelog') 10 > /tmp/pidstat.log &
```

#### 9.4.3 负载（5 台同时启动，n = c1..c5）
```bash
mkdir -p /mnt/lustre/work
nohup python3 /tmp/lustre_load.py --root /mnt/lustre/work --client $n --rate 40 --threads 8 \
    --duration 1800 --log /root/ops_$n.csv > /root/load_$n.out 2>&1 &
```

#### 9.4.4 延迟探针（在管理机上，负载期间每 ~4 分钟一次）
```bash
NAME=probe_${N}_$(date +%s)
ssh ec2-user@<c2> "echo x > /mnt/lustre/work/$NAME"; T1=$(date +%s.%N)
# 每 10 秒查一次，直到返回 1
SELECT count(*) FROM lustre_audit.changelog
WHERE mdt='<MDT>' AND dt='<YYYY-MM-DD>' AND name='<NAME>';
```

#### 9.4.5 分析
```bash
# 收集 5 台的 /root/ops_*.csv 到 ops/；把 changelog 从 S3 拉下来
aws s3 sync s3://<BUCKET>/lustre-changelog/ cl/
python3 scripts/scale_analyze.py ops/ cl/
```

### 9.5 结论

- 200 ops/s × 30 分钟（~500 条/s Changelog，共 89.7 万条），**0 丢失、0 缺口**，CREAT/RENME/UNLNK 与负载 **100% 对上**。
- 操作 → Athena 可查 **80 – 127 秒**（由 ROTATE_SEC 和上传周期决定）。
- 采集端 **~1% CPU / ~12 MB 内存**，可忽略。
- 开自动导出 DRA 后 **72% 的记录是 HSM**；压缩后 ~17 字节/条，此负载下 ~730 MB/天。

## 10. 多 MDT 测试（3 MDT）

按本文第 2–5 节原文命令，在 3 个 MDT 的文件系统上从头部署、操作、查询。

### 10.1 环境

| 项目 | 配置 |
|---|---|
| 文件系统 | FSx for Lustre PERSISTENT_2，**1200 GiB**，125 MB/s/TiB，Lustre 2.15，SSD |
| Metadata | `MetadataConfiguration={Mode=USER_PROVISIONED,Iops=36000}`（1200 GiB 下直接接受） |
| MDT 数 | **3 个**（`lfs mdts`：MDT0000 / MDT0001 / MDT0002 均 ACTIVE） |
| DRA | `/audit-dra` ↔ `s3://<BUCKET>/dummy/`，仅自动导出 |
| 客户端 | 1 台 m6i.large，AL2023，lustre-client 2.15.6 |
| 采集 | 2.4「多 MDT」循环原文执行 → 3 个 `lustre-changelog@<MDT>` 实例 running，ROTATE_SEC=60 |

**已实测：Metadata IOPS 36000 → 3 个 MDT**（每 12000 IOPS 一个 MDT，每个 MDT 约 1 亿 inode）。

### 10.2 测试操作

| 操作 | 说明 |
|---|---|
| 指定 MDT 建目录 | `lfs mkdir -i 0/1/2` 建 m0 / m1 / m2，`lfs getdirstripe -m` 确认分别在 MDT 0/1/2 |
| 默认 mkdir 30 个目录 | 自动分布：**MDT0 13 个 / MDT1 8 个 / MDT2 9 个** |
| 每个目录（共 33 个） | 建 50 文件、覆盖写 10、rename 5、删除 5、chmod 2 |
| 跨 MDT 移动文件 | `mv m0/f30 m1/x_from_m0_f30` |
| 跨 MDT 移动目录 | `mv m2/sub m0/sub_from_m2`（sub 含 3 个文件） |
| 删除跨 MDT 目录 | `rm -rf m0/sub_from_m2`；`rmdir m1/empty_on_m1` |
| 停一个采集实例 | 停 MDT0002 实例 30 秒，期间建 20 文件、删 2 个，再启动 |

### 10.3 结果

#### 每个 MDT 的记录（测试操作部分，与操作数逐项对上）

| MDT | 目录数 | CREAT | TRUNC | RENME | UNLNK | SATTR | MKDIR | RMDIR | seq | 缺口 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| MDT0000 | 14 | 700 | 140 | 71 | 70 | 28 | 15 | 0 | 1–1024 | **0** |
| MDT0001 | 9 | 450 | 91 | 46 | 45 | 18 | 10 | 1 | 1–661 | **0** |
| MDT0002 | 10 | 503 | 100 | 50 | 53 | 20 | 11 | 1 | 1–738 | **0** |

- 每个目录的操作只记在**该目录所在的 MDT** 上；3 个 S3 分区 `mdt=<FSNAME>-MDT000{0,1,2}/dt=...` 都有文件。
- 每个 MDT 的 seq 从 1 开始各自独立。
- HSM 记录 0 条（操作都在 DRA 外）。
- MDT0001 的 TRUNC 多 1 条（seq 1，DRA 创建期间由 FSx 内部节点产生，不是测试操作）。

#### 跨 MDT 操作记在哪里

| 操作 | 记录 | 记在哪个 MDT |
|---|---|---|
| `mv m0/f30 → m1/`（文件） | 1 条 RENME（old_path=`f30`，name=`x_from_m0_f30`） | **MDT0001**（目标目录所在），MDT0000 无记录 |
| `mv m2/sub → m0/`（目录） | 1 条 RENME（old_path=`sub`，name=`sub_from_m2`） | **MDT0000**（目标目录所在），MDT0002 无记录 |
| 移动后的目录 | `lfs getdirstripe -m` 仍为 2（目录本体不迁移） | — |
| `rm -rf m0/sub_from_m2` | 3 条 UNLNK + 1 条 RMDIR | **MDT0002**（目录本体所在），MDT0000 无记录 |
| `rmdir m1/empty_on_m1` | 1 条 RMDIR | MDT0001 |

结论：**按路径查某个目录的历史，必须查全部 MDT**（`mdt IN (...)`）。

#### 路径字段

| MDT | UNLNK 带完整路径（`path`） | RENME 的 `old_path` |
|---|---|---|
| MDT0000 | 70 / 70 | 完整路径（如 `/t/d25/f11`） |
| MDT0001 / MDT0002 | **0**（只有文件名，在 `name` 里） | 只有原文件名（如 `f11`） |

非 MDT0000 的记录要还原完整路径，用 `parent_fid` 在文件系统上 `lfs fid2path` 解析。

#### Athena

| 查询 | 结果 |
|---|---|
| 单个 `mdt='...'`（第 5 节全部查询） | 正常，每个 MDT 0.4–0.8 s |
| `mdt IN ('…-MDT0000','…-MDT0001','…-MDT0002')` | **可用**，一次返回 3 个 MDT |
| 不带 `mdt` 条件 / `mdt LIKE '…%'` | **报错** `CONSTRAINT_VIOLATION`（injected 投影要求静态等值条件） |
| 多 MDT 缺口检查（`PARTITION BY mdt`） | 可用，3 个 MDT 均 0 缺口 |

#### 停掉一个采集实例

MDT0002 实例停 30 秒，期间 22 条记录（20 CREAT + 2 UNLNK）**启动后未补回**；缺口检查准确报出 `1141 → 1164，缺 22`。

#### 采集脚本修正

原脚本用 `select()` + `readline()`：一批记录到达后，最后几条会留在 Python 读缓冲区，**直到该 MDT 再有新记录才写出**。实测 MDT0002 的最后 3 条（14:45:25 产生）5 分钟后才被采集。多 MDT 时，单个 MDT 往往一段时间没有新操作，这个问题更容易出现。已改为直接读 fd（`os.read`）后按行切分；修改后同样操作，最后一条记录在下一个 ROTATE_SEC 内正常写出。

### 10.4 复现命令

```bash
export AWS_REGION=us-east-2
aws fsx create-file-system --region us-east-2 --file-system-type LUSTRE --storage-capacity 1200 --storage-type SSD \
  --subnet-ids <SUBNET_ID> --security-group-ids <SG_ID> --file-system-type-version 2.15 \
  --lustre-configuration 'DeploymentType=PERSISTENT_2,PerUnitStorageThroughput=125,MetadataConfiguration={Mode=USER_PROVISIONED,Iops=36000}'
aws fsx create-data-repository-association --region us-east-2 --file-system-id <FS_ID> --file-system-path /audit-dra \
  --data-repository-path s3://<BUCKET>/dummy/ --s3 'AutoExportPolicy={Events=[NEW,CHANGED,DELETED]}'

# 客户端
dnf install -y lustre-client
mkdir -p /mnt/lustre
mount -t lustre -o relatime,flock <FS_ID>.fsx.us-east-2.amazonaws.com@tcp:/<MOUNT_NAME> /mnt/lustre
lfs mdts /mnt/lustre            # 3 个 ACTIVE
lfs df -i /mnt/lustre
# 部署：第 2.1–2.3 节原文（ROTATE_SEC=60），然后第 2.4 节「多 MDT」循环原文
```

测试操作：
```bash
L=/mnt/lustre/t; mkdir -p $L
lfs mkdir -i 0 $L/m0; lfs mkdir -i 1 $L/m1; lfs mkdir -i 2 $L/m2
for i in $(seq -w 1 30); do mkdir $L/d$i; done
for i in $(seq -w 1 30); do lfs getdirstripe -m $L/d$i; done | sort | uniq -c      # 默认分布
for d in m0 m1 m2 $(cd $L; ls -d d*); do
  D=$L/$d
  for i in $(seq 1 50); do echo data$i > $D/f$i; done
  for i in $(seq 1 10); do echo over$i > $D/f$i; done
  for i in $(seq 11 15); do mv $D/f$i $D/r$i; done
  for i in $(seq 16 20); do rm -f $D/f$i; done
  for i in 21 22; do chmod 600 $D/f$i; done
done
mkdir $L/m2/sub; for i in 1 2 3; do echo s$i > $L/m2/sub/s$i; done
mv $L/m0/f30 $L/m1/x_from_m0_f30          # 跨 MDT 移动文件
mv $L/m2/sub $L/m0/sub_from_m2            # 跨 MDT 移动目录
lfs getdirstripe -m $L/m0/sub_from_m2     # 仍为 2
mkdir $L/m1/empty_on_m1
rm -rf $L/m0/sub_from_m2
rmdir $L/m1/empty_on_m1

# 停一个实例
systemctl stop lustre-changelog@<FSNAME>-MDT0002.service
for i in $(seq 1 20); do echo x > $L/m2/stopped$i; done; rm -f $L/m2/stopped1 $L/m2/stopped2
sleep 30
systemctl start lustre-changelog@<FSNAME>-MDT0002.service
echo y > $L/m2/after_restart
```

Athena（建表用 [scripts/athena_ddl.sql](scripts/athena_ddl.sql)）：
```sql
-- 各 MDT 记录数 / seq
SELECT mdt, count(*), count(distinct seq), max(seq) FROM lustre_audit.changelog
WHERE mdt IN ('<FSNAME>-MDT0000','<FSNAME>-MDT0001','<FSNAME>-MDT0002') AND dt='<YYYY-MM-DD>'
GROUP BY mdt ORDER BY mdt;

-- 多 MDT 缺口检查
SELECT mdt, prev_seq, seq, seq - prev_seq - 1 AS missing FROM (
  SELECT mdt, seq, lag(seq) OVER (PARTITION BY mdt ORDER BY seq) AS prev_seq
  FROM lustre_audit.changelog
  WHERE mdt IN ('<FSNAME>-MDT0000','<FSNAME>-MDT0001','<FSNAME>-MDT0002') AND dt='<YYYY-MM-DD>')
WHERE seq - prev_seq > 1;

-- 所有 MDT 的删除
SELECT mdt, "time", uid, client_ip, type, coalesce(path, name) AS f FROM lustre_audit.changelog
WHERE mdt IN ('<FSNAME>-MDT0000','<FSNAME>-MDT0001','<FSNAME>-MDT0002') AND dt='<YYYY-MM-DD>'
  AND type IN ('UNLNK','RMDIR') AND flags='0x1' ORDER BY "time";

-- 跨 MDT rename
SELECT mdt, seq, "time", old_path, name, source_parent_fid, parent_fid FROM lustre_audit.changelog
WHERE mdt IN ('<FSNAME>-MDT0000','<FSNAME>-MDT0001','<FSNAME>-MDT0002') AND dt='<YYYY-MM-DD>' AND type='RENME';

-- 按用户统计
SELECT mdt, uid, type, count(*) n FROM lustre_audit.changelog
WHERE mdt IN ('<FSNAME>-MDT0000','<FSNAME>-MDT0001','<FSNAME>-MDT0002') AND dt='<YYYY-MM-DD>'
GROUP BY mdt, uid, type ORDER BY mdt, uid, n DESC;
```

### 10.5 结论

- 第 2.4 节多 MDT 循环原文可用：3 MDT → 3 个采集实例 → 3 个 S3 分区，每个 MDT seq 连续 **0 缺口**，记录数与操作数逐项对上。
- Metadata IOPS **36000 = 3 个 MDT**（1200 GiB 即可配置）。
- 一个操作只记在一个 MDT：跨 MDT rename 记在**目标目录**所在 MDT；删除记在**目录本体**所在 MDT。审计查询用 `mdt IN (...)` 覆盖全部 MDT（不写 `mdt` 会报错）。
- 只有 MDT0000 的记录带完整路径，其它 MDT 只有文件名，需 `parent_fid` + `lfs fid2path` 还原。
- 修正了采集脚本"最后几条记录要等下一条记录才写出"的问题。

## 11. 可靠性补测

针对采集方案的可靠性问题补测（2026-10-12）：读取是否影响 DRA 导出、客户端 `changelog_clear`、记录存活时长、采集异常、上传失败、突发批量操作、按大小切文件。

环境：FSx for Lustre PERSISTENT_2 / 2.15 / SSD / 125 MB/s/TiB / 1200 GiB / 1 MDT，us-east-2c；客户端 2 × m6i.large AL2023 lustre-client 2.15.6。
DRA：业务目录 `/work ↔ s3://<BUCKET>/work/`，AutoExport NEW/CHANGED/DELETED。采集器 c1，负载/探针 c2。
测试脚本见 [scripts/reliability/](scripts/reliability/)；采集脚本 [scripts/lustre-changelog-collector.py](scripts/lustre-changelog-collector.py) 已更新为本节 v2（见 T5/T8）。复现命令见 11.10。

### 11.1 一句话结论

| # | 问题 | 结论 |
|---|---|---|
| T1 | `--follow` 是否影响 DRA 导出 | **不影响**。有/无读者导出完成 38s / 40s，S3 对象、大小、md5 全部一致。多个读者互不抢记录 |
| T2 | 客户端能否 `changelog_clear` | **能，且危险**。`lfs changelog_clear <MDT> cl1 0` 返回 0；运行期间新文件 **848/900 没有导出到 S3**，事后该 MDT **停止清除记录**（>2h 未恢复） |
| T3 | 记录在 MDT 上存活多久 | 空闲 **5.8–7.6s**（P50 6.8s）；200 ops/s 负载下 **1.7–5.8s**（P50 3.8s） |
| T4 | ROTATE_SEC=300 是否丢 | 业务记录 **0 丢**（CREAT/RENME/UNLNK 与负载逐条 100% 对上）；单文件 **1.4–1.8 MB**（gz）。仅 HSM 类型丢 3750 条 |
| T5 | 进程/机器异常 | kill -9 丢 **~0.7s**（225 条），机器重启丢 **~8s**（2254 条），**全部可被 seq 缺口查询发现**。原脚本另有 2 个 bug（见下），已修 |
| T6 | 上传失败 10 分钟 | 本地堆积 2 个文件 / 3.4 MB；恢复后**第一次 timer（≤1 分钟）全部补传，0 缺口** |
| T7 | 突发批量操作 | `rm -rf` 2000 / 10000 / 50000 个文件、`cp -r` 10000 个文件：**0 丢**，CREAT/UNLNK 条数 = 文件数 |
| T8 | 按大小切文件 | 新增 `ROTATE_MAX_MB`，50000 突发切成 24 个文件（压缩前 2.0 MB / 压缩后 80–90 KB），0 缺口 |


### 11.2 T1 只读不消费，不影响 DRA 导出

操作（每组）：在 `/work/<组>` 建 5000 × 1MB、覆盖写 500、rename 200、删 200（最终 4800 个文件）。

| 组 | 读者 | 操作耗时 | 操作结束 → S3 完全对上 | 对象数 | 抽样 md5 / size |
|---|---|---|---|---|---|
| A | collector + 2 个 `lfs changelog --follow` | 31s | **38s** | 4800 | 13/13 一致，0 大小错 |
| B（对照） | 无 | 31s | **40s** | 4800 | 13/13 一致，0 大小错 |

改名后新 key 存在、旧 key 消失；删除的 key 消失（两组相同）。

**3 个读者同时读同一 MDT（seq 6–44808）：**

| 读者 | 条数 | 缺失 | 缺失类型 |
|---|---|---|---|
| collector（c1） | 44426 | 313 | 全部 HSM |
| follower 1（c2） | 44453 | 281 | 全部 HSM |
| follower 2（c2） | 44314 | 420 | 全部 HSM |

- 3 个读者的业务记录（CREAT 10500 / UNLNK 400 / RENME 400 / TRUNC 501）**完全一致、0 缺失**。
- 没有"一个读走了另一个就读不到"的现象：3 个读者缺的 HSM 记录各不相同（缺口都结束在 seq 末两位 `06`/`64` 处），3 个读者合起来只缺 69 条。
- 推测（未实测）：HSM 记录由导出流程产生、清除很快，读取稍慢的那批被 MDT 先清掉；对审计（谁删/改了文件）无影响。

### 11.3 T2 客户端执行 changelog_clear

| 命令 | 返回码 | 输出 |
|---|---|---|
| `lfs changelog_clear <MDT> cl1 0` | **0（成功）** | — |
| `lfs changelog_clear <MDT> cl2 0` | 2 | no changelog user: cl2 |
| `lfs changelog_clear <MDT> cl1 100` | 22 | record out of range: 100 |
| `lfs changelog_clear <MDT> cl3 5` / `cl99 0` | 2 | no changelog user |

后果实测（120s 内每 0.1s 执行一次 `cl1 0`，1141 次全部成功；期间建 1000 个 1MB 文件、删 100 个）：

| 项 | 预期 | 实测 |
|---|---|---|
| S3 上的对象 | 900 | **52**（848 个文件从未导出，`lfs hsm_state` = 0x0） |
| collector 记录 | 1000 CREAT + 100 UNLNK | **57 CREAT，0 UNLNK** |
| clear 停止后的新文件 | 50 导出 | 50 导出（正常） |
| 之后该 MDT 的记录清除 | 几秒清除 | **停止清除**：从 16:09 起的记录到 18:10 仍在（2 小时，2865 条），只增不减 |

- `cl1` 就是 DRA 自动导出用的 changelog 用户。客户端 root 可以替它确认记录 → 导出漏掉这些文件，审计也丢。
- 漏导出的文件**不会自动补**；对它们再做一次修改（touch / 重写 / rename）会触发导出；或执行 `lfs hsm_archive`（实测 842 个文件 < 2 分钟全部补到 S3）。`create-data-repository-task EXPORT` 在 AutoExport DRA 上被拒绝（"Export tasks are not supported for data repositories with Automatic Export enabled"）。
- 清除停止后，DRA 新的导出仍正常（新建/rename/删除 2 分钟内同步到 S3）。推测（未实测）：导出流程内部记录的已确认位置与被强制 clear 后的位置不一致，导致之后不再清除；长期会使 MDT 上 changelog 持续增长。
- **结论：严禁在任何客户端执行 `lfs changelog_clear`。** 建议在运维规范中明确禁止，并监控 `lfs changelog <MDT> | head -1` 的最早记录时间（正常应在 10 秒内）。

### 11.4 T3 MDT 上记录存活时长

方法：touch 一个唯一文件，然后每 0.2s 执行一次 `lfs changelog <MDT>`（非 follow），记录该 CREAT 最后一次出现的时间。每种 N=20。

| 条件 | min | P50 | max |
|---|---|---|---|
| 空闲 | 5.76s | 6.79s | 7.61s |
| 负载（200 ops/s，T4 期间） | 1.68s | 3.80s | 5.83s |

操作后 ≤0.01s 即可读到记录。

### 11.5 T4 ROTATE_SEC=300，200 ops/s × 18 分钟

负载：`lustre_load.py --rate 200 --threads 16 --duration 1080`（2MB 文件，写/读/覆盖/截断重写/rename/删除 = 40/30/10/10/5/5）。

| 项 | 结果 |
|---|---|
| 操作数 | 216000，0 失败，199.3 ops/s |
| write → CREAT | 86564 / 86564 |
| rename → RENME | 10804 / 10804 |
| delete → UNLNK | 10779 / 10779 |
| Changelog 总数 | 473631 条，seq 1–477381，重复 0 |
| 缺口 | 42 处 / 3750 条，**全部是 HSM**，集中在 17:11:54–17:13:11（负载结束后的导出收尾阶段） |
| 单文件大小（300s，gz） | 满 300s 的文件 **1.39–1.78 MB**（约 2.1 万条 / 分钟） |
| 每条压缩后 | 15.6 B |

### 11.6 T5 采集进程 / 机器异常（负载 100 ops/s 期间）

| 场景 | 采集器 | 中断 → 恢复 | seq 缺口 | 中断前未切的 .part |
|---|---|---|---|---|
| kill -9 | v1（原版） | 2s（systemd 重启） | 467 条（1.6s） | **25192 条遗留在 .part，永不上传** |
| 机器强制重启（sysrq-b） | v1 | 7s（开机 2s + mount + 启动） | 2452 条（9.8s） | **41001 条遗留在 .part，永不上传** |
| systemctl restart | v1 | — | 599 条 | 正常切文件（但 SIGTERM 无处理，gzip 尾部丢失） |
| kill -9 | **v2** | 2s | **225 条（0.7s）** | 启动时自动转存上传 |
| 机器强制重启 | **v2** | 8s | **2254 条（8.4s）** | 启动时自动转存上传 |

- 采集中断期间的记录无法补回（几秒即被清除），丢失量 ≈ 中断时长 × 记录速率。
- **所有缺口都能被 seq 缺口查询发现**（Athena 实测返回全部 5 处缺口及条数）。
- 已切到 `ready/` 的文件在 kill -9 / 重启后都保留，重启后照常上传。
- v1 的 2 个问题：
  1. gzip 写缓冲从不 flush，进程被杀时 `.part` 里最近的数据只在内存 → 丢失；
  2. 异常退出留下的 `.part` 没有任何代码处理，**永远不会上传**（实测 kill -9 一次就遗留 2.5 万条、重启一次遗留 4.1 万条，而且这些记录已被 MDT 清除，无法补回）。
- v2 修正（[scripts/lustre-changelog-collector.py](scripts/lustre-changelog-collector.py)）：
  1. 每秒 `flush + fsync` 一次 `.part`；
  2. 启动时把遗留 `.part` 中完整的行转存为 `ready/…-salvaged.jsonl.gz`；
  3. 处理 SIGTERM，`systemctl stop/restart` 时正常切文件退出。
  - 实测：v2 上线时把 v1 遗留的 3 个 `.part`（83618 条）全部转存上传；之后 kill -9 / 重启只丢中断时长内的记录。

### 11.7 T6 上传失败 10 分钟

方法：bucket policy 拒绝采集机实例角色对 `lustre-changelog/*` 的 `s3:PutObject`，持续 10.5 分钟（负载约 150–200 ops/s）。

| 项 | 结果 |
|---|---|
| 上传报错 | AccessDenied（journalctl 可见），文件留在本地 |
| 本地堆积 | 2 个文件 / 3.4 MB（ROTATE_SEC=300） |
| 采集 | 不受影响，持续运行 |
| 恢复后 | 下一次 timer（1 分钟内）全部上传，ready/ 清空 |
| seq 缺口 | 0 |

### 11.8 T7 突发批量操作

无其它负载；collector v2，ROTATE_SEC=300。建文件用 `xargs -P 32 touch`，等 15s 后 `rm -rf` 整个目录。

| 操作 | 耗时 | CREAT | UNLNK | seq 缺口 |
|---|---|---|---|---|
| 建 2000 → rm -rf | 1.1s / 1.6s | 2000 | 2000 | 0 |
| 建 10000 → rm -rf | 7.4s / 8.5s | 10000 | 10000 | 0 |
| 建 50000 → rm -rf | 31s / 34s | 50000 | 50000 | 0 |
| cp -r 10000 个 4KB 文件 → rm -rf | 17.7s / 6.5s | 10000 | 10000 | 0 |
| 建 50000 → rm -rf（T8，ROTATE_MAX_MB=2） | 33s / 40s | 50000 | 50000 | 0 |

- 读取速率跟得上：最高约 3000 条/s（50000 rm -rf）仍 0 缺口。
- README 中"2000 文件批量删除有缺失"未复现。结合 T2/T5 推测（未实测）：当时缺失更可能来自采集进程中断（重启 / 被杀，原脚本 .part 还不会上传）或 HSM 类记录，而非读取速度。

### 11.9 T8 按大小切文件（ROTATE_MAX_MB）

新增环境变量 `ROTATE_MAX_MB`（压缩前字节数，默认 0 = 不启用）；满 `ROTATE_SEC` 或满大小先到先切；同一秒内多次切分文件名加 `-1`、`-2` 后缀。

| 项 | 结果 |
|---|---|
| 50000 突发（约 10 万条） | 切成 24 个文件 |
| 每个文件 | 压缩前 2.0 MB（约 5000 条）/ 压缩后 80–90 KB |
| seq | 1283585–1406611 连续，**0 缺口** |

附：突发期间 MDT 清除跟不上，采集器重启后 `--follow` 会**从 MDT 上仍保留的最早记录重新读**（实测重复 98646 条）。**查询时需要按 `seq` 去重**（`count(distinct seq)` / `SELECT DISTINCT`）。


### 11.10 复现命令

占位符：<BUCKET> <FS_ID> <MOUNT_NAME> <SG> <SUBNET_ID> <VPC_ID> <MDT>=<FSNAME>-MDT0000

#### 环境
```bash
export AWS_REGION=us-east-2 AWS_DEFAULT_REGION=us-east-2
SG=$(aws ec2 create-security-group --group-name lustre-clv-$(date +%s) --description lustre-clv --vpc-id <VPC_ID> --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":988,\"ToPort\":988,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG\"}]},{\"IpProtocol\":\"tcp\",\"FromPort\":1018,\"ToPort\":1023,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG\"}]}]"
aws s3 mb s3://<BUCKET> --region us-east-2
aws fsx create-file-system --file-system-type LUSTRE --storage-capacity 1200 --storage-type SSD --subnet-ids <SUBNET_ID> \
  --security-group-ids $SG --file-system-type-version 2.15 --lustre-configuration 'DeploymentType=PERSISTENT_2,PerUnitStorageThroughput=125'
AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
aws ec2 run-instances --image-id $AMI --instance-type m6i.large --count 2 --key-name <KEY> --subnet-id <SUBNET_ID> \
  --security-group-ids $SG --iam-instance-profile Name=<PROFILE> --associate-public-ip-address
# 业务目录 DRA
aws fsx create-data-repository-association --file-system-id <FS_ID> --file-system-path /work \
  --data-repository-path s3://<BUCKET>/work/ --s3 'AutoExportPolicy={Events=[NEW,CHANGED,DELETED]}'
# 客户端（2 台）
dnf install -y lustre-client sysstat      # lustre-client-2.15.6
mkdir -p /mnt/lustre; mount -t lustre -o relatime,flock <FS_ID>.fsx.us-east-2.amazonaws.com@tcp:/<MOUNT_NAME> /mnt/lustre
```
采集机 c1 部署：第 2.1–2.3 节原文（ROTATE_SEC=60），然后
```bash
systemctl enable --now lustre-changelog@<MDT>.service lustre-changelog-upload.timer
```

#### T1
```bash
# c2：额外 2 个只读 follower
for k in 1 2; do nohup setsid lfs changelog --follow <MDT> > /root/follow$k.txt 2>&1 < /dev/null & done
# c1：实验组（collector + 2 follower 运行中）
bash scripts/reliability/t1ops.sh A2
# 管理机：轮询 S3 直到对上
bash scripts/reliability/t1check.sh <BUCKET> A2 <done_epoch>
# 对照组：停全部读者
pkill -x lfs                                            # c2
systemctl stop lustre-changelog@<MDT>.service           # c1
bash scripts/reliability/t1ops.sh B; bash scripts/reliability/t1check.sh <BUCKET> B <done_epoch>
# 三个读者 seq 对比
python3 scripts/reliability/seqgap.py /root/follow1.txt; python3 scripts/reliability/seqgap.py /root/follow2.txt
python3 scripts/reliability/seqgap.py <s3 sync 下来的 changelog>/*/*/*.gz
```

#### T2
```bash
M=<MDT>
for args in 'cl1 0' 'cl2 0' 'cl1 100' 'cl3 5' 'cl99 0'; do lfs changelog_clear $M $args; echo "changelog_clear $M $args -> rc=$?"; done
bash scripts/reliability/t2ops.sh       # 120s 内每 0.1s clear cl1 0，同时建 1000 删 100
aws s3 ls s3://<BUCKET>/work/T2/ | grep -c ' f'
# 修复（AutoExport DRA 上 create-data-repository-task EXPORT 被拒）：
cd /mnt/lustre/work/T2; for f in f*; do lfs hsm_state $f | grep -q archived || echo $f; done > /root/t2_unarch.txt
xargs -n 50 -a /root/t2_unarch.txt lfs hsm_archive
```

#### T3
```bash
bash scripts/reliability/t3probe.sh <MDT> 20 idle          # 空闲
bash scripts/reliability/t3probe.sh <MDT> 20 load          # 在 T4 负载期间（另一台客户端）
```

#### T4（采集机）
```bash
sed -i 's/ROTATE_SEC=60/ROTATE_SEC=300/' /etc/systemd/system/lustre-changelog@.service
systemctl daemon-reload; systemctl restart lustre-changelog@<MDT>.service
# 负载机
mkdir -p /mnt/lustre/work/load
python3 scripts/lustre_load.py --root /mnt/lustre/work/load --client c2 --rate 200 --threads 16 --duration 1080 --log /root/ops_c2.csv
# 分析（管理机）
aws s3 sync s3://<BUCKET>/lustre-changelog/mdt=<MDT>/ cl/
python3 scripts/scale_analyze.py ops/ cl/
```

#### T5（负载：lustre_load.py --rate 100 --threads 16 --duration 1200）
```bash
kill -9 $(pgrep -f lustre-changelog-collector.py)                 # a
echo 1 > /proc/sys/kernel/sysrq; sync; echo b > /proc/sysrq-trigger # b（经 SSM 下发）
python3 scripts/reliability/partsalvage.py /var/spool/lustre-changelog/*.part  # 查看遗留 .part
# 升级 v2
install -m755 scripts/lustre-changelog-collector.py /usr/local/bin/; systemctl restart lustre-changelog@<MDT>.service
```
Athena 缺口查询（按 seq 去重）：
```sql
SELECT prev_seq, seq, seq - prev_seq - 1 AS missing FROM (SELECT seq, lag(seq) OVER (ORDER BY seq) AS prev_seq FROM (SELECT DISTINCT seq FROM lustre_clv.changelog WHERE mdt='<MDT>' AND dt='2026-10-12')) WHERE seq - prev_seq > 1 ORDER BY seq
```

#### T6
```bash
cat > deny.json <<'J'
{"Version":"2012-10-17","Statement":[{"Sid":"T6DenyChangelogPut","Effect":"Deny","Principal":"*","Action":"s3:PutObject",
 "Resource":"arn:aws:s3:::<BUCKET>/lustre-changelog/*",
 "Condition":{"ArnLike":{"aws:PrincipalArn":"arn:aws:iam::<ACCOUNT_ID>:role/<ROLE>"}}}]}
J
aws s3api put-bucket-policy --bucket <BUCKET> --policy file://deny.json
# 10 分钟后
aws s3api delete-bucket-policy --bucket <BUCKET>
# 采集机观察
ls /var/spool/lustre-changelog/ready | wc -l; du -sh /var/spool/lustre-changelog/ready; journalctl -u lustre-changelog-upload.service --since -3min
```

#### T7
```bash
for n in 2000 10000 50000; do bash scripts/reliability/t7burst.sh $n n$n >> /root/t7_times.txt; sleep 20; done
bash scripts/reliability/t7cp.sh 10000 >> /root/t7_times.txt
python3 scripts/reliability/t7analyze.py cl/ t7_times.txt
```

#### T8
```bash
sed -i 's/^Environment=ROTATE_SEC=300$/Environment=ROTATE_SEC=300 ROTATE_MAX_MB=2/' /etc/systemd/system/lustre-changelog@.service
systemctl daemon-reload; systemctl restart lustre-changelog@<MDT>.service
bash scripts/reliability/t7burst.sh 50000 t8n50000
```
