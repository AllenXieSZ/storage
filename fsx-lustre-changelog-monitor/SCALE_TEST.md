# Changelog → S3 → Athena 审计方案：规模测试（实测）

在 5 台客户端合计 200 ops/s、持续 30 分钟的混合文件负载下，验证 [EXPORT_TO_S3.md](EXPORT_TO_S3.md) 方案**是否丢记录、延迟多少、采集端占多少资源**。

## 1. 环境

| 项目 | 配置 |
|---|---|
| 区域 / AZ | us-east-2 / us-east-2c |
| 文件系统 | FSx for Lustre PERSISTENT_2，**9600 GiB**，250 MB/s/TiB，Lustre 2.15，1 个 MDT |
| DRA | `/work` ↔ `s3://<bucket>/work/`，仅自动导出（NEW / CHANGED / DELETED） |
| 客户端 | **5 台 m6i.xlarge**，AL2023，lustre-client 2.15，root |
| 采集器 | 跑在其中 1 台（c1）：`lustre-changelog@<MDT>.service`（ROTATE_SEC=60）+ 每分钟上传 timer |
| Athena | 表 `lustre_audit.changelog`（DDL 见 [scripts/athena_ddl.sql](scripts/athena_ddl.sql)） |

## 2. 负载

| 项目 | 值 |
|---|---|
| 并发 | 5 客户端 × 8 线程，每台限速 40 ops/s → **合计 200 ops/s** |
| 时长 | 1800 s（30 分钟） |
| 文件大小 | 2 MB |
| 比例 | 写（新建）40% / 读 30% / 原地覆盖写 10% / O_TRUNC 重写 10% / rename 5% / 删除 5% |
| 脚本 | [scripts/lustre_load.py](scripts/lustre_load.py) |

### 负载结果：360000 次操作，0 失败，实际 200.0 ops/s

| 操作 | 次数 | P50 | P99 |
|---|---:|---:|---:|
| write（新建 2MB） | 144383 | 3.28 ms | 4.70 ms |
| read（读 2MB） | 107798 | 6.60 ms | 8.64 ms |
| overwrite | 35848 | 3.28 ms | 4.75 ms |
| trunc_rewrite | 35841 | 3.74 ms | 5.36 ms |
| rename | 18004 | 1.69 ms | 2.68 ms |
| delete | 18126 | 1.03 ms | 1.72 ms |

## 3. 结果

### 3.1 Changelog 完整性

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

### 3.2 与负载对账（按文件名逐条匹配）

| 负载操作 | 次数 | 对应记录 | 命中率 |
|---|---:|---|---:|
| write | 144383 | CREAT | **100%** |
| rename | 18004 | RENME | **100%** |
| delete | 18126 | UNLNK | **100%** |
| overwrite + trunc_rewrite | 35848 + 35841 | TRUNC 35842 / MTIME 35624 | — |
| read | 107798 | 无记录（预期） | — |

（多出的少量 CREAT/UNLNK 是延迟探针文件。）

### 3.3 延迟：操作 → Athena 可查

负载期间每 ~4 分钟在 c2 上建一个唯一文件，每 10 秒查一次 Athena 直到查到该 CREAT 记录：

| 探针 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Athena 可见延迟 | 80 s | 112 s | 111 s | 127 s | 111 s | 116 s |

**80 – 127 秒**，符合 ROTATE_SEC(60) + 上传周期(60) + 查询轮询(10) 的上限。

### 3.4 采集端资源（c1，pidstat 每 10 秒采样，30 分钟）

| 进程 | 平均 CPU | 峰值 CPU | RSS |
|---|---:|---:|---:|
| python3 collector | **~1.0%** | 1.4% | **~12 MB** |
| lfs changelog --follow | 0.1% | 0.2% | 1.7 MB |

### 3.5 数据量

| 项目 | 值 |
|---|---|
| 30 分钟 S3 文件 | 32 个 .jsonl.gz，共 **15.2 MB**（压缩后） |
| 单文件（1 分钟） | 平均 475 KB，最大 519 KB |
| 每条记录 | ~17 字节（压缩后） |
| 外推（同负载持续） | **~730 MB/天** |

### 3.6 Athena 查询（30 分钟全量 ~90 万条，单日分区）

| 查询 | 结果 | 耗时 | 扫描量 |
|---|---|---:|---:|
| 谁删了哪些文件（UNLNK/RMDIR，LIMIT） | 返回 time/uid/client_ip/path | 2.5 s | 15.2 MB |
| 删除总数 | 18131 | 1.3 s | 15.2 MB |
| seq 缺口检查 | 0 缺口 / 0 缺失 | 2.0 s | 15.2 MB |
| 按 uid + type 统计 | 见 3.1 | 1.2 s | 15.2 MB |
| count / min / max seq | 897183 / 1 / 897183 | 1.0 s | 15.2 MB |

（查询在负载结束后进行，计数含少量探针/收尾记录。gzip JSON 不可列裁剪，每次扫描整个分区。）

### 3.7 DRA 自动导出（可选项）

负载结束后：Lustre `/work` 文件数 **126263** = S3 `work/` 对象数 **126263**（另 45 个目录对象），**完全一致**。

## 4. 复现命令

### 4.1 挂载（每台客户端）
```bash
dnf install -y lustre-client sysstat
mkdir -p /mnt/lustre
mount -t lustre -o relatime,flock <FS_ID>.fsx.us-east-2.amazonaws.com@tcp:/<MOUNT_NAME> /mnt/lustre
lfs mdts /mnt/lustre          # 得到 MDT 名称，如 35brbb4v-MDT0000
```

### 4.2 部署采集器（仅 c1）
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

### 4.3 负载（5 台同时启动，n = c1..c5）
```bash
mkdir -p /mnt/lustre/work
nohup python3 /tmp/lustre_load.py --root /mnt/lustre/work --client $n --rate 40 --threads 8 \
    --duration 1800 --log /root/ops_$n.csv > /root/load_$n.out 2>&1 &
```

### 4.4 延迟探针（在管理机上，负载期间每 ~4 分钟一次）
```bash
NAME=probe_${N}_$(date +%s)
ssh ec2-user@<c2> "echo x > /mnt/lustre/work/$NAME"; T1=$(date +%s.%N)
# 每 10 秒查一次，直到返回 1
SELECT count(*) FROM lustre_audit.changelog
WHERE mdt='<MDT>' AND dt='<YYYY-MM-DD>' AND name='<NAME>';
```

### 4.5 分析
```bash
# 收集 5 台的 /root/ops_*.csv 到 ops/；把 changelog 从 S3 拉下来
aws s3 sync s3://<BUCKET>/lustre-changelog/ cl/
python3 scripts/scale_analyze.py ops/ cl/
```

## 5. 结论

- 200 ops/s × 30 分钟（~500 条/s Changelog，共 89.7 万条），**0 丢失、0 缺口**，CREAT/RENME/UNLNK 与负载 **100% 对上**。
- 操作 → Athena 可查 **80 – 127 秒**（由 ROTATE_SEC 和上传周期决定）。
- 采集端 **~1% CPU / ~12 MB 内存**，可忽略。
- 开自动导出 DRA 后 **72% 的记录是 HSM**；压缩后 ~17 字节/条，此负载下 ~730 MB/天。
