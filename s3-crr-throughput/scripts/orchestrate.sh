#!/bin/bash
# 12 次运行编排：第1轮 A B C D；第2轮 B C D A；第3轮 C D A B。
# 每次: run_r2.sh(建桶+metrics -> 复制配置 -> [等待期间删上一次目标桶] -> 300s -> jobs -> 轮询)
#       -> verify_dst.sh -> 检查上次目标桶 PUT 已回落 -> 下一次
# 止损: abort 标志(job Failed / >30min / 失败任务>100) 或累计估算 > $560 时停止。
cd "$(dirname "$0")"
ORDER="a1 b1 c1 d1 b2 c2 d2 a2 c3 d3 a3 b3"
GEN_COST=2.0          # 数据生成(EC2+PUT) 估算
COST=$GEN_COST
PREV=""
declare -A RC=([a]=42.00 [b]=42.25 [c]=42.75 [d]=42.75)
for RUN in $ORDER; do
  S=${RUN:0:1}; R=${RUN:1:1}
  NEXT=$(python3 -c "print(round($COST+${RC[$S]},2))")
  if python3 -c "import sys; sys.exit(0 if $NEXT>560 else 1)"; then echo "BUDGET STOP before $RUN (would be \$$NEXT)"; break; fi
  echo "=== START $RUN $(date -u +%FT%TZ) cum_before=\$$COST"
  ./run_r2.sh $S $R "$PREV" > runs_$RUN.out 2>&1
  rc=$?
  tail -3 runs_$RUN.out
  COST=$NEXT
  echo "cum_cost_est=\$$COST after $RUN"
  ./verify_dst.sh $RUN
  ab=$(cat runs/$RUN/abort 2>/dev/null || echo 1)
  PREV=runs/$RUN/dst_buckets.txt
  if [ $rc != 0 ] || [ "$ab" != 0 ]; then echo "ABORT after $RUN rc=$rc abort=$ab"; break; fi
  # 等最近 3 分钟目标桶 PUT 回落 (<100/min) 再继续（CW 有 1~3 min 延迟，下次运行还有 300s 传播等待）
  sleep 120
  for D in $(cat $PREV); do
    aws cloudwatch get-metric-statistics --region us-west-2 --namespace AWS/S3 --metric-name PutRequests \
      --dimensions Name=BucketName,Value=$D Name=FilterId,Value=all --start-time $(date -u -d '-6 min' +%FT%TZ) --end-time $(date -u +%FT%TZ) \
      --period 60 --statistics Sum --query 'Datapoints[].[Timestamp,Sum]' --output text | sort | tr '\n' ' '; echo " <- recent PUT/min $D"
  done
done
echo "=== ORCH END $(date -u +%FT%TZ) cum_cost_est=\$$COST last=$PREV"
echo "$PREV" > LAST_PREV
