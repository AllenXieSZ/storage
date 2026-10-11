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
4. **多 MDT 文件系统**：每个 MDT 起一个 `lustre-changelog@<MDT>` 实例（命令见 2.4）。**扩容 Metadata IOPS 后检查 `lfs mdts`，为新增 MDT 启动实例。** **已实测**（第 10 节）：Metadata IOPS 36000 = 3 个 MDT；一个操作只记在一个 MDT 上，查询要用 `mdt IN (...)` 覆盖全部 MDT；跨 MDT rename 只记在目标目录所在 MDT。
5. **CREAT/MKDIR 只有文件名没有完整路径**，可通过 `parent_fid` 在文件系统上 `lfs fid2path` 解析，或用同目录下的 UNLNK/RENME 记录关联。
6. **只有开了自动导出 DRA 的文件系统才有 Changelog**（见 README）。
   - **建议：如果业务本身不需要 DRA，可以建一个"空的"自动导出 DRA，只用来开启 Changelog。**
   - **做法：新建一个空 S3 bucket（或空前缀），DRA 关联到一个业务不使用的空目录（如 `/.audit-dra` ↔ `s3://<audit-bucket>/dummy/`），只开 AutoExport（NEW / CHANGED / DELETED），不开 AutoImport。**
   - **实测 Changelog 记录的是整个文件系统的变更，不限于 DRA 路径**，所以业务目录的操作照样被审计；业务数据不会导出到 S3，基本无额外存储成本。
   - **已实测**：HSM 记录由自动导出产生，只涉及 DRA 路径下的文件，DRA 指向空目录时 HSM 噪声消失。实测同样操作（建 200 个 1MB 文件、覆盖写 50、rename 20、删除 20、mkdir 5）：DRA 外目录 HSM 0 条（CREAT 200 / RENME 20 / UNLNK 20 / MKDIR 6 照常记录）；DRA 内目录 HSM 540 条（180 个留存文件各 3 条），CREAT/RENME/UNLNK/MKDIR 条数与 DRA 外相同；S3 上只有 DRA 内的对象。
   - 仅适用于 PERSISTENT_2（支持 DRA 的部署类型）。仅导出 DRA 创建约 3 分钟。
7. **Changelog 不是 FSx for Lustre 官方文档的功能**，行为可能变化。
8. 数据量估算：本次每条记录压缩后约 23 字节（72 条 1679 字节）；每天 1000 万次操作约 230 MB/天。
9. 建议给 S3 前缀配置生命周期规则（如 90 天后转 Glacier / 1 年后删除）。

## 8. 文件

| 文件 | 说明 |
|---|---|
| [scripts/lustre-changelog-collector.py](scripts/lustre-changelog-collector.py) | 采集 + 解析 + 切片（2026-10-11 修正读缓冲问题，见 10.3） |
| [scripts/lustre-changelog-upload.sh](scripts/lustre-changelog-upload.sh) | 上传到 S3 |
| [scripts/athena_ddl.sql](scripts/athena_ddl.sql) | Athena 建表 |
| [scripts/lustre_load.py](scripts/lustre_load.py) | 规模测试负载脚本（限速混合文件操作） |
| [scripts/scale_analyze.py](scripts/scale_analyze.py) | 规模测试分析（seq 缺口 + 与负载对账） |

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
