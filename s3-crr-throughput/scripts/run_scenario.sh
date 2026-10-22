#!/bin/bash
# 用法: ./run_scenario.sh <a|b|c>
#  a = 1 条规则(全桶, Filter.Prefix="")         -> 1 个 Batch Replication 作业
#  b = 2 条规则(g0/ , g1/)                       -> 2 个作业(各按前缀过滤 manifest)
#  c = 4 条规则(g0/p0/ g0/p1/ g1/p2/ g1/p3/)     -> 4 个作业
# 每个场景用全新目标桶；源桶复制配置整体替换为本场景的规则集。
set -euo pipefail
cd "$(dirname "$0")"
S=$1
E=$(cat EPOCH)
ACC=$(aws sts get-caller-identity --query Account --output text)
SRC=s3-crr-src-$E
DST=s3-crr-dst-$S-$E
REPL_ROLE=arn:aws:iam::$ACC:role/s3crr-repl-$E
BATCH_ROLE=arn:aws:iam::$ACC:role/s3crr-batch-$E
case $S in
  a|a2) PREFIXES=("") ;;
  b|b2) PREFIXES=("g0/" "g1/") ;;
  c) PREFIXES=("g0/p0/" "g0/p1/" "g1/p2/" "g1/p3/") ;;
esac
OUT=runs/$S; mkdir -p $OUT

# 1) 复制配置（N 条规则，不同 Priority，开 Metrics，不开 RTC）
python3 - "$DST" "$REPL_ROLE" "${PREFIXES[@]}" > $OUT/replication.json <<'PY'
import json,sys
dst,role,*pfx=sys.argv[1:]
rules=[]
for i,p in enumerate(pfx):
    rules.append({"ID":f"rule{i}","Priority":i+1,"Status":"Enabled",
      "Filter":{"Prefix":p},
      "DeleteMarkerReplication":{"Status":"Disabled"},
      "Destination":{"Bucket":f"arn:aws:s3:::{dst}","StorageClass":"STANDARD",
         "Metrics":{"Status":"Enabled"}}})
print(json.dumps({"Role":role,"Rules":rules},indent=2))
PY
aws s3api put-bucket-replication --bucket $SRC --region us-east-2 --replication-configuration file://$OUT/replication.json
aws s3api get-bucket-replication --bucket $SRC --region us-east-2 > $OUT/replication.applied.json
echo "replication config applied $(date -u +%FT%TZ); waiting 300s for propagation (doc: expect a few minutes delay)"
sleep 300

# 2) N 个 Batch Replication 作业（S3 生成 manifest，按前缀过滤；不过滤 ReplicationStatus，
#    因为 A 跑完后源对象状态=COMPLETED，B/C 需要复制到新目标）
: > $OUT/jobs.txt
for i in "${!PREFIXES[@]}"; do
  p=${PREFIXES[$i]}
  if [ -z "$p" ]; then FILTER='{"EligibleForReplication":true}'
  else FILTER="{\"EligibleForReplication\":true,\"KeyNameConstraint\":{\"MatchAnyPrefix\":[\"$p\"]}}"; fi
  cat > $OUT/job$i.manifest-generator.json <<J
{"S3JobManifestGenerator":{"ExpectedBucketOwner":"$ACC","SourceBucket":"arn:aws:s3:::$SRC","EnableManifestOutput":false,"Filter":$FILTER}}
J
  cat > $OUT/job$i.report.json <<J
{"Bucket":"arn:aws:s3:::$SRC","Prefix":"reports/$S/job$i","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}
J
  JID=$(aws s3control create-job --region us-east-2 --account-id $ACC \
    --operation '{"S3ReplicateObject":{}}' \
    --report file://$OUT/job$i.report.json \
    --manifest-generator file://$OUT/job$i.manifest-generator.json \
    --priority 10 --role-arn $BATCH_ROLE --no-confirmation-required \
    --description "crr-bench-$S-job$i" --query JobId --output text)
  echo "$JID $p $(date -u +%FT%TZ)" | tee -a $OUT/jobs.txt
done
T0=$(date +%s); echo "T0 $T0 $(date -u +%FT%TZ)" > $OUT/t0

# 3) 轮询（30s）
LOG=$OUT/poll.log
while true; do
  now=$(date +%s); alldone=1
  while read JID P TS; do
    aws s3control describe-job --region us-east-2 --account-id $ACC --job-id $JID \
      --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed,ProgressSummary.Timers.ElapsedTimeInActiveSeconds]' --output text > /tmp/js.$$ || echo "ERR" > /tmp/js.$$
    st=$(cut -f1 /tmp/js.$$)
    echo "$(date -u +%FT%TZ) +$((now-T0))s $JID ${P:-ALL} $(tr '\t' ' ' < /tmp/js.$$)" | tee -a $LOG
    case $st in Complete|Failed|Cancelled) ;; *) alldone=0;; esac
  done < $OUT/jobs.txt
  [ $alldone = 1 ] && break
  sleep 30
done
T1=$(date +%s); echo "T1 $T1 $(date -u +%FT%TZ) wall=$((T1-T0))s" | tee $OUT/t1
while read JID P TS; do
  aws s3control describe-job --region us-east-2 --account-id $ACC --job-id $JID > $OUT/describe-$JID.json
done < $OUT/jobs.txt
echo DONE
