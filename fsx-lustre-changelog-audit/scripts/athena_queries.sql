-- 1. 谁删了哪些文件
SELECT "time", uid, client_ip, type, path
FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
  AND type IN ('UNLNK','RMDIR') AND flags='0x1'
ORDER BY seq;

-- 2. 某个文件的完整历史
SELECT "time", type, uid, client_ip, coalesce(path, old_path, name) AS f
FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
  AND (path LIKE '%user%' OR old_path LIKE '%user%' OR name LIKE 'user%')
ORDER BY seq;

-- 3. 重命名记录
SELECT "time", uid, old_path, name
FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09' AND type='RENME';

-- 4. 按用户统计
SELECT uid, type, count(*) AS n
FROM lustre_audit.changelog
WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09'
GROUP BY uid, type ORDER BY uid, n DESC;

-- 5. 检查是否漏记录（序号缺口）
SELECT prev_seq, seq, seq - prev_seq - 1 AS missing FROM (
  SELECT seq, lag(seq) OVER (ORDER BY seq) AS prev_seq
  FROM lustre_audit.changelog WHERE mdt='divrbb4v-MDT0000' AND dt='2026-10-09')
WHERE seq - prev_seq > 1;
