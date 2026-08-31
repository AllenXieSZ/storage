#!/bin/bash
# ssmrun.sh <iid> "<cmd>"
IID="$1"; shift; CMD="$*"
CID=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript \
  --parameters "commands=[\"$CMD\"]" --region us-east-2 --timeout-seconds 3600 \
  --query 'Command.CommandId' --output text 2>&1)
if [[ "$CID" != cmd-* && "$CID" != *-*-*-*-* ]]; then echo "SEND_FAIL: $CID"; exit 1; fi
for i in $(seq 1 240); do
  ST=$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --region us-east-2 --query 'Status' --output text 2>/dev/null)
  if [[ "$ST" == "Success" || "$ST" == "Failed" || "$ST" == "Cancelled" || "$ST" == "TimedOut" ]]; then break; fi
  sleep 5
done
echo "=== STATUS: $ST ==="
aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --region us-east-2 --query 'StandardOutputContent' --output text
echo "=== STDERR ==="
aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --region us-east-2 --query 'StandardErrorContent' --output text
