#!/bin/bash
# Round2 单次运行: ./run_r2.sh <scen a|b|c|d> <round 1|2|3> [prev_dst_buckets_file_to_delete]
#  a = 1 规则(Prefix="")            -> 1 目标桶, 1 job
#  b = 2 规则(g0/ g1/)              -> 1 目标桶, 2 job
#  c = 4 规则(g0/p0/ g0/p1/ g1/p2/ g1/p3/) -> 1 目标桶, 4 job
#  d = 4 规则(同 c)                 -> 4 个不同目标桶(us-west-2), 4 job
# 每次运行全新目标桶；建桶后立即开 1 分钟 request metrics (Id=all)。
set -euo pipefail
cd "$(dirname "$0")"
S=$1; R=$2; PREV=${3:-}
E=$(cat EPOCH)
ACC=$(aws sts get-caller-identity --query Account --output text)
SRC=s3-crr-src-$E
REPL_ROLE=arn:aws:iam::$ACC:role/s3crr-repl-$E
BATCH_ROLE=arn:aws:iam::$ACC:role/s3crr-batch-$E
RUN=$S$R
OUT=runs/$RUN; mkdir -p $OUT
case $S in
  a) PREFIXES=("") ;;
  b) PREFIXES=("g0/" "g1/") ;;
  c|d) PREFIXES=("g0/p0/" "g0/p1/" "g1/p2/" "g1/p3/") ;;
esac
DSTS=()
for i in "${!PREFIXES[@]}"; do
  if [ $S = d ]; then DSTS+=("s3-crr-dst-$RUN-$i-$E"); else DSTS+=("s3-crr-dst-$RUN-$E"); fi
done
printf "%s\n" "${DSTS[@]}" | sort -u > $OUT/dst_buckets.txt

# 1) 目标桶 + versioning + 1 分钟 request metrics
for D in $(cat $OUT/dst_buckets.txt); do
  # 预建(precreate_dst.sh)的桶直接复用：request metrics 需约 15 分钟才开始上报(官方文档)，所以提前建桶开指标
  if aws s3api head-bucket --bucket $D --region us-west-2 2>/dev/null; then
    echo "precreated $D (exists)"
  else
    aws s3api create-bucket --bucket $D --region us-west-2 --create-bucket-configuration LocationConstraint=us-west-2 >/dev/null
    echo "created $D $(date -u +%FT%TZ)"
  fi
  aws s3api put-bucket-versioning --bucket $D --versioning-configuration Status=Enabled --region us-west-2
  aws s3api get-bucket-metrics-configuration --bucket $D --region us-west-2 --id all >/dev/null 2>&1 || \
    aws s3api put-bucket-metrics-configuration --bucket $D --region us-west-2 --id all --metrics-configuration Id=all
done

# 2) 复制配置
python3 - "$REPL_ROLE" "${#PREFIXES[@]}" "${DSTS[@]}" -- "${PREFIXES[@]}" > $OUT/replication.json <<'PY'
import json,sys
a=sys.argv[1:]; role=a[0]; n=int(a[1]); dsts=a[2:2+n]; pfx=a[3+n:]
if len(pfx)<n: pfx=pfx+[""]*(n-len(pfx))
rules=[]
for i,(d,p) in enumerate(zip(dsts,pfx)):
    rules.append({"ID":f"rule{i}","Priority":i+1,"Status":"Enabled","Filter":{"Prefix":p},
      "DeleteMarkerReplication":{"Status":"Disabled"},
      "Destination":{"Bucket":f"arn:aws:s3:::{d}","StorageClass":"STANDARD","Metrics":{"Status":"Enabled"}}})
print(json.dumps({"Role":role,"Rules":rules},indent=2))
PY
aws s3api put-bucket-replication --bucket $SRC --region us-east-2 --replication-configuration file://$OUT/replication.json
aws s3api get-bucket-replication --bucket $SRC --region us-east-2 > $OUT/replication.applied.json
TCFG=$(date +%s); echo "replication applied $(date -u +%FT%TZ)"

# 2b) 在等待传播期间删除上一次运行的目标桶（已校验过）
if [ -n "$PREV" ] && [ -s "$PREV" ]; then ./delete_dst.sh "$PREV" || echo "WARN delete prev failed"; fi
NOW=$(date +%s); W=$((300-(NOW-TCFG))); [ $W -gt 0 ] && sleep $W
echo "propagation wait done $(date -u +%FT%TZ) ($(( $(date +%s)-TCFG ))s)"

# 3) N 个 Batch Replication 作业
: > $OUT/jobs.txt
for i in "${!PREFIXES[@]}"; do
  p=${PREFIXES[$i]}
  if [ -z "$p" ]; then FILTER='{"EligibleForReplication":true}'
  else FILTER="{\"EligibleForReplication\":true,\"KeyNameConstraint\":{\"MatchAnyPrefix\":[\"$p\"]}}"; fi
  cat > $OUT/job$i.manifest-generator.json <<J
{"S3JobManifestGenerator":{"ExpectedBucketOwner":"$ACC","SourceBucket":"arn:aws:s3:::$SRC","EnableManifestOutput":false,"Filter":$FILTER}}
J
  cat > $OUT/job$i.report.json <<J
{"Bucket":"arn:aws:s3:::$SRC","Prefix":"reports/$RUN/job$i","Format":"Report_CSV_20180820","Enabled":true,"ReportScope":"FailedTasksOnly"}
J
  JID=$(aws s3control create-job --region us-east-2 --account-id $ACC \
    --operation '{"S3ReplicateObject":{}}' \
    --report file://$OUT/job$i.report.json \
    --manifest-generator file://$OUT/job$i.manifest-generator.json \
    --priority 10 --role-arn $BATCH_ROLE --no-confirmation-required \
    --description "crr-r2-$RUN-job$i" --query JobId --output text)
  echo "$JID ${p:-ALL} $(date -u +%FT%TZ)" | tee -a $OUT/jobs.txt
done
T0=$(date +%s); echo "T0 $T0 $(date -u +%FT%TZ)" > $OUT/t0

# 4) 轮询 30s；>30 min 视为异常
LOG=$OUT/poll.log; ABORT=0
while true; do
  now=$(date +%s); alldone=1
  while read JID P TS; do
    aws s3control describe-job --region us-east-2 --account-id $ACC --job-id $JID \
      --query 'Job.[Status,ProgressSummary.TotalNumberOfTasks,ProgressSummary.NumberOfTasksSucceeded,ProgressSummary.NumberOfTasksFailed,ProgressSummary.Timers.ElapsedTimeInActiveSeconds]' --output text > /tmp/js.$$ 2>/dev/null || echo "ERR" > /tmp/js.$$
    st=$(cut -f1 /tmp/js.$$)
    echo "$(date -u +%FT%TZ) +$((now-T0))s $JID $P $(tr '\t' ' ' < /tmp/js.$$)" >> $LOG
    case $st in Complete|Failed|Cancelled) ;; *) alldone=0;; esac
    [ "$st" = Failed ] && ABORT=1
  done < $OUT/jobs.txt
  [ $alldone = 1 ] && break
  if [ $((now-T0)) -gt 1800 ]; then ABORT=1; echo "TIMEOUT >30min" | tee -a $LOG; break; fi
  sleep 30
done
T1=$(date +%s); echo "T1 $T1 $(date -u +%FT%TZ) wall=$((T1-T0))s" | tee $OUT/t1
while read JID P TS; do
  aws s3control describe-job --region us-east-2 --account-id $ACC --job-id $JID > $OUT/describe-$JID.json
done < $OUT/jobs.txt
FAILED=$(python3 -c "
import json,glob
print(sum(json.load(open(f))['Job']['ProgressSummary']['NumberOfTasksFailed'] for f in glob.glob('$OUT/describe-*.json')))")
echo "failed_tasks=$FAILED"
[ "$FAILED" -gt 100 ] && ABORT=1
echo $ABORT > $OUT/abort
echo "RUN_DONE $RUN abort=$ABORT"
