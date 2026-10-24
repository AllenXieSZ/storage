#!/bin/bash
# 小文件单次运行: ./run_small.sh <s1|s2>   1 规则(Prefix="") -> 1 目标桶(预建), 1 job
set -euo pipefail
cd "$(dirname "$0")"
RUN=$1
E=$(cat EPOCH)
ACC=$(aws sts get-caller-identity --query Account --output text)
SRC=s3-crr-src-small-$E
REPL_ROLE=arn:aws:iam::$ACC:role/s3crr-repl-$E
BATCH_ROLE=arn:aws:iam::$ACC:role/s3crr-batch-$E
OUT=runs/$RUN; mkdir -p $OUT
D=s3-crr-dst-$RUN-$E; echo $D > $OUT/dst_buckets.txt
aws s3api head-bucket --bucket $D --region us-west-2 && echo "precreated $D (exists)"
aws s3api get-bucket-metrics-configuration --bucket $D --region us-west-2 --id all
cat > $OUT/replication.json <<J
{"Role":"$REPL_ROLE","Rules":[{"ID":"rule0","Priority":1,"Status":"Enabled","Filter":{"Prefix":""},
 "DeleteMarkerReplication":{"Status":"Disabled"},
 "Destination":{"Bucket":"arn:aws:s3:::$D","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}}]}
J
aws s3api put-bucket-replication --bucket $SRC --region us-east-2 --replication-configuration file://$OUT/replication.json
aws s3api get-bucket-replication --bucket $SRC --region us-east-2 > $OUT/replication.applied.json
echo "replication applied $(date -u +%FT%TZ)"; sleep 300; echo "propagation wait done $(date -u +%FT%TZ)"
cat > $OUT/job0.manifest-generator.json <<J
{"S3JobManifestGenerator":{"ExpectedBucketOwner":"$ACC","SourceBucket":"arn:aws:s3:::$SRC","EnableManifestOutput":false,"Filter":{"EligibleForReplication":true}}}
J
cat > $OUT/job0.report.json <<J
{"Bucket":"arn:aws:s3:::$SRC","Prefix":"reports/$RUN/job0","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}
J
JID=$(aws s3control create-job --region us-east-2 --account-id $ACC \
  --operation '{"S3ReplicateObject":{}}' \
  --report file://$OUT/job0.report.json \
  --manifest-generator file://$OUT/job0.manifest-generator.json \
  --priority 10 --role-arn $BATCH_ROLE --no-confirmation-required \
  --description "crr-small-$RUN-job0" --query JobId --output text)
echo "$JID ALL $(date -u +%FT%TZ)" | tee $OUT/jobs.txt
T0=$(date +%s); echo "T0 $T0 $(date -u +%FT%TZ)" > $OUT/t0
LOG=$OUT/poll.log; ABORT=0
while true; do
  now=$(date +%s)
  R=$(aws s3control describe-job --region us-east-2 --account-id $ACC --job-id $JID \
    --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed,ProgressSummary.Timers.ElapsedTimeInActiveSeconds]' --output text 2>/dev/null || echo ERR)
  echo "$(date -u +%FT%TZ) +$((now-T0))s $JID $(echo $R)" >> $LOG
  st=$(echo "$R" | cut -f1)
  case $st in Complete|Failed|Cancelled) break;; esac
  fl=$(echo "$R" | cut -f4); [[ "$fl" =~ ^[0-9]+$ ]] && [ "$fl" -gt 10000 ] && { echo "MANY FAILED -> cancel" | tee -a $LOG; aws s3control update-job-status --region us-east-2 --account-id $ACC --job-id $JID --requested-job-status Cancelled; ABORT=1; }
  if [ $((now-T0)) -gt 5400 ]; then ABORT=1; echo "TIMEOUT >90min -> cancel" | tee -a $LOG; aws s3control update-job-status --region us-east-2 --account-id $ACC --job-id $JID --requested-job-status Cancelled || true; sleep 60; break; fi
  sleep 30
done
[ "$st" = Failed ] && ABORT=1
T1=$(date +%s); echo "T1 $T1 $(date -u +%FT%TZ) wall=$((T1-T0))s" | tee $OUT/t1
aws s3control describe-job --region us-east-2 --account-id $ACC --job-id $JID > $OUT/describe-$JID.json
FAILED=$(python3 -c "import json;print(json.load(open('$OUT/describe-$JID.json'))['Job']['ProgressSummary']['NumberOfTasksFailed'])")
echo "failed_tasks=$FAILED"; [ "$FAILED" -gt 100 ] && ABORT=1
echo $ABORT > $OUT/abort; echo "RUN_DONE $RUN abort=$ABORT"
