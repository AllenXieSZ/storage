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
`ROTATE_SEC` = 多少秒切一个文件（实测用 60，生产建议 300）。没有记录的时间段不生成文件。

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
```bash
systemctl daemon-reload
systemctl enable --now lustre-changelog@divrbb4v-MDT0000.service lustre-changelog-upload.timer
```

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
| `path` | UNLNK / RMDIR 的完整路径（相对文件系统根） |
| `name` | CREAT / MKDIR 的文件名；RENME 的新名字 |
| `old_path` | RENME 的原完整路径 |
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
查询时必须在 WHERE 里指定 `mdt`（injected 投影要求）。

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
  FROM lustre_audit.changelog WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09')
WHERE seq - prev_seq > 1;
```

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
2. **采集进程停止期间的变更无法补回**（Changelog 几秒即被清除）。可用上面的"序号缺口"查询发现缺失。
3. **高频批量操作可能漏记录**：README 中记录过一次 2000 文件批量删除时有缺失。
4. **多 MDT 文件系统**：每个 MDT 起一个 `lustre-changelog@<MDT>` 实例。
5. **CREAT/MKDIR 只有文件名没有完整路径**，可通过 `parent_fid` 在文件系统上 `lfs fid2path` 解析，或用同目录下的 UNLNK/RENME 记录关联。
6. **只有开了自动导出 DRA 的文件系统才有 Changelog**（见 README）。
7. **Changelog 不是 FSx for Lustre 官方文档的功能**，行为可能变化。
8. 数据量估算：本次每条记录压缩后约 23 字节（72 条 1679 字节）；每天 1000 万次操作约 230 MB/天。
9. 建议给 S3 前缀配置生命周期规则（如 90 天后转 Glacier / 1 年后删除）。

## 8. 文件

| 文件 | 说明 |
|---|---|
| [scripts/lustre-changelog-collector.py](scripts/lustre-changelog-collector.py) | 采集 + 解析 + 切片 |
| [scripts/lustre-changelog-upload.sh](scripts/lustre-changelog-upload.sh) | 上传到 S3 |
| [scripts/athena_ddl.sql](scripts/athena_ddl.sql) | Athena 建表 |
