#!/bin/bash
# Drive ONTAP CLI via SSM->EC2->sshpass ssh to FSxN mgmt endpoint
# Usage: ./ontap.sh "<ontap cli command>"
source "$(dirname "$0")/resources.env"
CMD="$*"
REGION=us-east-2
# escape single quotes in CMD for embedding
ESC=$(printf '%s' "$CMD" | sed "s/'/'\\\\''/g")
cat > /tmp/ssm_o.json <<JSON
{"commands":["sshpass -p '$FSXPW' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 fsxadmin@$MGMT '$ESC'"]}
JSON
CID=$(aws ssm send-command --region $REGION --instance-ids $IID \
  --document-name "AWS-RunShellScript" --parameters file:///tmp/ssm_o.json \
  --query 'Command.CommandId' --output text 2>&1)
for i in $(seq 1 60); do
  st=$(aws ssm get-command-invocation --region $REGION --command-id "$CID" --instance-id $IID --query 'Status' --output text 2>/dev/null)
  [ "$st" = "Success" -o "$st" = "Failed" ] && break
  sleep 3
done
echo "=== STDOUT ==="
aws ssm get-command-invocation --region $REGION --command-id "$CID" --instance-id $IID --query 'StandardOutputContent' --output text 2>&1
echo "=== STDERR ==="
aws ssm get-command-invocation --region $REGION --command-id "$CID" --instance-id $IID --query 'StandardErrorContent' --output text 2>&1
