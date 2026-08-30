#!/bin/bash
# Run an arbitrary shell script on the EC2 via SSM RunShellScript
# Usage: ./ssmrun.sh "<shell command(s)>"
source "$(dirname "$0")/resources.env"
CMD="$*"
REGION=us-east-2
ESC=$(printf '%s' "$CMD" | python3 -c 'import json,sys; print(json.dumps([sys.stdin.read()]))')
cat > /tmp/ssm_r.json <<JSON
{"commands":$ESC}
JSON
CID=$(aws ssm send-command --region $REGION --instance-ids $IID \
  --document-name "AWS-RunShellScript" --parameters file:///tmp/ssm_r.json \
  --query 'Command.CommandId' --output text 2>&1)
for i in $(seq 1 200); do
  st=$(aws ssm get-command-invocation --region $REGION --command-id "$CID" --instance-id $IID --query 'Status' --output text 2>/dev/null)
  [ "$st" = "Success" -o "$st" = "Failed" ] && break
  sleep 3
done
echo "STATUS=$st"
echo "=== STDOUT ==="
aws ssm get-command-invocation --region $REGION --command-id "$CID" --instance-id $IID --query 'StandardOutputContent' --output text 2>&1
echo "=== STDERR ==="
aws ssm get-command-invocation --region $REGION --command-id "$CID" --instance-id $IID --query 'StandardErrorContent' --output text 2>&1
