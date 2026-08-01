#!/bin/bash
# lustre_throughput_flip.sh —— 每次运行把 FSx Lustre per-unit throughput 在 125<->250 翻转
# 记录发起时刻 + 目标值到日志，供 IO 监控对照
FS=fs-REDACTED
REGION=us-east-2
LOG=/home/ubuntu/.openclaw/workspace/throughput_flip.log
ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }

CUR=$(aws fsx describe-file-systems --file-system-ids $FS --region $REGION \
  --query 'FileSystems[0].LustreConfiguration.PerUnitStorageThroughput' --output text 2>/dev/null)

# 若有正在进行的变配，跳过（6h窗口未到会被拒绝）
ACT=$(aws fsx describe-file-systems --file-system-ids $FS --region $REGION \
  --query "FileSystems[0].AdministrativeActions[?AdministrativeActionType=='FILE_SYSTEM_UPDATE'&&Status!='COMPLETED'&&Status!='FAILED'] | length(@)" --output text 2>/dev/null)

if [ "$ACT" != "0" ] && [ -n "$ACT" ]; then
  echo "[$(ts)] SKIP: 已有进行中的变配 (count=$ACT), 当前 PerUnit=$CUR" >>"$LOG"
  echo "SKIP: change in progress"
  exit 0
fi

if [ "$CUR" = "125" ]; then TARGET=250; else TARGET=125; fi

RES=$(aws fsx update-file-system --file-system-id $FS --region $REGION \
  --lustre-configuration PerUnitStorageThroughput=$TARGET \
  --query 'FileSystem.Lifecycle' --output text 2>&1)

echo "[$(ts)] FLIP: $CUR -> $TARGET  (result: $RES)" >>"$LOG"
echo "FLIP $CUR -> $TARGET : $RES"
