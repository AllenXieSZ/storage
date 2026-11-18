#!/bin/bash
# v2 实测脚本：在测试 FS 上验证幂等 / 隔周 / CSV 读取 / 错误处理 / Scheduler 真实触发 + DLQ
FS=${FS:-fs-0eeabbe93f4cc61f0}; R=${R:-us-east-2}; B=${B:-s3lambdatest2}; K=fsx-mw/fsx_lustre_list.csv
F=fsx-mw-scheduler; CSV=${CSV:-test.csv}
mw(){ echo "   >> 当前窗口: $(aws fsx describe-file-systems --region $R --file-system-ids $FS --query 'FileSystems[0].LustreConfiguration.WeeklyMaintenanceStartTime' --output text)"; }
inv(){ aws lambda invoke --region $R --function-name $F --cli-binary-format raw-in-base64-out --payload "$1" /tmp/o.json --query '[StatusCode,FunctionError]' --output text | tr '\n\t' '  '; cat /tmp/o.json; echo; }

echo "## T0 初始"; mw
echo "## T1 跳过周 skip (now=2026-11-24 周二14:00，属于 11-23 跳过周)"; inv "{\"action\":\"skip\",\"fs_id\":\"$FS\",\"now\":\"2026-11-24T14:00:00Z\"}"; mw
echo "## T2 重复 skip（幂等）"; inv "{\"action\":\"skip\",\"fs_id\":\"$FS\",\"now\":\"2026-11-24T14:00:00Z\"}"; mw
echo "## T3 restore"; inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
echo "## T4 重复 restore（幂等）"; inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
echo "## T5 非跳过周 skip (now=2026-12-01)"; inv "{\"action\":\"skip\",\"fs_id\":\"$FS\",\"now\":\"2026-12-01T14:00:00Z\"}"; mw
echo "## T6 再下一周是跳过周 (now=2026-12-08)"; inv "{\"action\":\"skip\",\"fs_id\":\"$FS\",\"now\":\"2026-12-08T14:00:00Z\"}"; mw
echo "   跨年检查（不调用 FSx，只算）:"; python3 -c "
from datetime import date,timedelta
f=date(2026,11,23);m=f
for d in ['2026-12-22','2026-12-29','2027-01-05','2027-01-12']:
  x=date.fromisoformat(d);w=((x-timedelta(days=x.weekday()))-f).days//7;print('    ',d,'跳过' if w%2==0 else '正常维护')"
inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
echo "## T7 skip 和 restore 同时触发（预留并发=1）"; inv "{\"action\":\"skip\",\"fs_id\":\"$FS\",\"force\":true}" & sleep 0.3; inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}" & wait; mw
echo "   再 restore 一次兜底"; inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
echo "## T8 手工把窗口改乱为 6:10:00，restore 应按 CSV 改回"; aws fsx update-file-system --region $R --file-system-id $FS --lustre-configuration WeeklyMaintenanceStartTime=6:10:00 >/dev/null; sleep 5; mw
inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
echo "## T9 只改 S3 上的 CSV（不重新部署）为 5:18:30，restore 应读到新值"; sed "s/,3:02:00,/,5:18:30,/" $CSV > /tmp/c2.csv; aws s3 cp /tmp/c2.csv s3://$B/$K --quiet
inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
aws s3 cp $CSV s3://$B/$K --quiet; inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
echo "## T10 错误：CSV 中没有该 FS"; head -1 $CSV > /tmp/c3.csv; aws s3 cp /tmp/c3.csv s3://$B/$K --quiet
inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; aws s3 cp $CSV s3://$B/$K --quiet
echo "## T11 错误：非法参数"; inv '{"action":"oops"}'
echo "## T12 Scheduler 真实触发：一次性计划 skip(force) + 一个不存在的 FS（重试0次，应进 DLQ）"
ACCT=$(aws sts get-caller-identity --query Account --output text); ROLE=arn:aws:iam::$ACCT:role/fsx-mw-scheduler-invoke-role
Q=$(aws sqs get-queue-url --region $R --queue-name fsx-mw-dlq --query QueueUrl --output text); QA=$(aws sqs get-queue-attributes --region $R --queue-url $Q --attribute-names QueueArn --query Attributes.QueueArn --output text)
AT=$(date -u -d '+90 sec' +%Y-%m-%dT%H:%M:%S)
for n in ok bad; do [ $n = ok ] && IN="{\\\"action\\\":\\\"skip\\\",\\\"fs_id\\\":\\\"$FS\\\",\\\"force\\\":true}" || IN="{\\\"action\\\":\\\"restore\\\",\\\"fs_id\\\":\\\"fs-00000000000000000\\\"}"
aws scheduler create-schedule --region $R --group-name fsx-mw --name fsx-mw-test-$n --schedule-expression "at($AT)" --schedule-expression-timezone UTC --flexible-time-window Mode=OFF --action-after-completion DELETE \
 --target "{\"Arn\":\"arn:aws:lambda:$R:$ACCT:function:$F\",\"RoleArn\":\"$ROLE\",\"Input\":\"$IN\",\"RetryPolicy\":{\"MaximumRetryAttempts\":0},\"DeadLetterConfig\":{\"Arn\":\"$QA\"}}" --query ScheduleArn --output text; done
echo "   计划触发时间 $AT UTC，等待 6 分钟..."; sleep 360; mw
echo "   Lambda 日志:"; aws logs filter-log-events --region $R --log-group-name /aws/lambda/$F --start-time $(( ($(date +%s) - 300) * 1000 )) --query 'events[].message' --output text | tr '\t' '\n' | grep -E 'fs-|MWError|Error' | head
echo "   DLQ:"; aws sqs receive-message --region $R --queue-url $Q --max-number-of-messages 5 --wait-time-seconds 10 --query 'Messages[].Body' --output text | python3 -c "import sys,json
for l in sys.stdin.read().split('\\t'):
  l=l.strip()
  if not l: continue
  try: d=json.loads(l); print('    ',d.get('requestContext',{}).get('condition'),d.get('requestPayload'),str(d.get('responsePayload'))[:200])
  except Exception: print('    ',l[:300])"
inv "{\"action\":\"restore\",\"fs_id\":\"$FS\"}"; mw
