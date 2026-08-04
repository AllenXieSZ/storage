#!/bin/bash
# collect-aurora-backup-metrics.sh
# 采集 Aurora backup 相关 CloudWatch 指标 + Cost Explorer 实际费用，
# 用于验算 Aurora backup 费用公式与实测/账单对比。
#
# 用法: ./collect-aurora-backup-metrics.sh [cluster-id] [region]
set -uo pipefail

CLUSTER="${1:-aurora-backup-test}"
REGION="${2:-us-east-2}"
NOW=$(date -u '+%Y-%m-%dT%H:%M:%S')
DAY_AGO=$(date -u -d '25 hours ago' '+%Y-%m-%dT%H:%M:%S')
PRICE=0.021   # $/GB-month, us-east-2 Aurora backup storage 超额单价

metric() {
  aws cloudwatch get-metric-statistics --region "$REGION" \
    --namespace AWS/RDS --metric-name "$1" \
    --dimensions Name=DBClusterIdentifier,Value="$CLUSTER" \
    --start-time "$DAY_AGO" --end-time "$NOW" \
    --period 86400 --statistics Maximum \
    --query 'Datapoints|sort_by(@,&Timestamp)[-1].Maximum' --output text 2>/dev/null
}

VOL=$(metric VolumeBytesUsed)
RET=$(metric BackupRetentionPeriodStorageUsed)
SNAP=$(metric SnapshotStorageUsed)
BILLED=$(metric TotalBackupStorageBilled)

b2g() { python3 -c "v='$1'; print('%.4f'%(float(v)/1024/1024/1024)) if v not in ('None','') else print('—')"; }

VOL_G=$(b2g "$VOL"); RET_G=$(b2g "$RET"); SNAP_G=$(b2g "$SNAP"); BILLED_G=$(b2g "$BILLED")

# 公式算费用（月）: TotalBackupStorageBilled(GB) × $0.021
COST=$(python3 -c "
b='$BILLED'
print('%.4f'%((float(b)/1024/1024/1024)*$PRICE)) if b not in ('None','') else print('0.0000')
")

# Cost Explorer 实际 Aurora backup 费用（本月至今）
MONTH_START=$(date -u '+%Y-%m-01')
TODAY=$(date -u '+%Y-%m-%d')
CE=$(aws ce get-cost-and-usage --region us-east-1 \
  --time-period Start=$MONTH_START,End=$TODAY \
  --granularity MONTHLY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE_GROUP","Values":["Aurora: Backup Storage"]}}' \
  --query 'ResultsByTime[-1].Total.UnblendedCost.Amount' --output text 2>/dev/null || echo "n/a")

echo "date=$TODAY"
echo "VolumeBytesUsed=${VOL_G} GB"
echo "BackupRetentionPeriodStorageUsed=${RET_G} GB"
echo "SnapshotStorageUsed=${SNAP_G} GB"
echo "TotalBackupStorageBilled=${BILLED_G} GB"
echo "FormulaCost(month)=\$${COST}"
echo "CostExplorer_AuroraBackup(month-to-date)=\$${CE}"
echo ""
echo "# markdown row:"
echo "| $TODAY | $VOL_G | $RET_G | $SNAP_G | $BILLED_G | \$$COST | \$$CE | |"
