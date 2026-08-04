#!/bin/bash
# aurora-dml.sh — 每日 ~20GB DML 负载生成器（模拟 transaction log）
# 部署在跳板 EC2 上，通过 cron 每天运行。
# 机制：seed 表 1000 行×1KB，cross join 自扩展，每轮 INSERT 100 万行(~1GB)+DELETE，
#       跑 20 轮≈20GB binlog/redo log，表本身不膨胀（模拟真实 OLTP 事务负载）。
# 实测单轮(1M行 insert+delete)≈75秒，20 轮≈25 分钟。
#
# ⚠️ 密码请用环境变量或 IAM 认证，勿硬编码。此处为占位符。
set -uo pipefail

ENDPOINT="${AURORA_ENDPOINT:-aurora-backup-test.cluster-XXXX.us-east-2.rds.amazonaws.com}"
USER="${AURORA_USER:-admin}"
PASS="${AURORA_PASS:-REDACTED}"
DB="${AURORA_DB:-txnlog}"
LOG="/var/log/aurora-dml.log"

MYSQL="mysql -h $ENDPOINT -u $USER -p$PASS $DB --connect-timeout=30"

echo "===== $(date -u '+%Y-%m-%d %H:%M:%S UTC') START DML run =====" >> "$LOG"

$MYSQL 2>>"$LOG" <<'SQL'
CREATE TABLE IF NOT EXISTS txn (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch BIGINT NOT NULL,
  payload VARCHAR(1024) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_batch (batch)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS seed (n INT PRIMARY KEY, p VARCHAR(1024));
SQL

CNT=$($MYSQL -N -e "SELECT COUNT(*) FROM seed;" 2>>"$LOG")
if [ "${CNT:-0}" -lt 1000 ]; then
  $MYSQL 2>>"$LOG" <<'SQL'
INSERT INTO seed (n,p)
SELECT x, REPEAT(MD5(RAND()),32)
FROM (
  SELECT (a.i + b.i*10 + c.i*100) AS x
  FROM (SELECT 0 i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) a
  CROSS JOIN (SELECT 0 i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) b
  CROSS JOIN (SELECT 0 i UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) c
) t
ON DUPLICATE KEY UPDATE p=VALUES(p);
SQL
fi

# 每轮 INSERT 100万行(~1GB) + DELETE，20 轮≈20GB log，表保持有界
BATCH_ID=$(date +%s)
ROUNDS=20
for (( r=1; r<=ROUNDS; r++ )); do
  $MYSQL 2>>"$LOG" <<SQL
INSERT INTO txn (batch,payload) SELECT $BATCH_ID, s1.p FROM seed s1 CROSS JOIN seed s2;
DELETE FROM txn WHERE batch=$BATCH_ID;
SQL
  echo "  round $r/$ROUNDS done at $(date -u '+%H:%M:%S')" >> "$LOG"
done

ROWCOUNT=$($MYSQL -N -e "SELECT COUNT(*) FROM txn;" 2>>"$LOG" || echo "?")
echo "===== $(date -u '+%Y-%m-%d %H:%M:%S UTC') END DML run, remaining rows=$ROWCOUNT =====" >> "$LOG"
