#!/bin/bash
# 预建目标桶 + versioning + 1 分钟 request metrics（官方：约 15 分钟后才开始上报）
cd "$(dirname "$0")"; E=$(cat EPOCH)
for RUN in "$@"; do
  if [ ${RUN:0:1} = d ]; then L="s3-crr-dst-$RUN-0-$E s3-crr-dst-$RUN-1-$E s3-crr-dst-$RUN-2-$E s3-crr-dst-$RUN-3-$E"; else L=s3-crr-dst-$RUN-$E; fi
  for D in $L; do
    aws s3api create-bucket --bucket $D --region us-west-2 --create-bucket-configuration LocationConstraint=us-west-2 >/dev/null
    aws s3api put-bucket-versioning --bucket $D --versioning-configuration Status=Enabled --region us-west-2
    aws s3api put-bucket-metrics-configuration --bucket $D --region us-west-2 --id all --metrics-configuration Id=all
    echo "$(date -u +%FT%TZ) precreated $D"
  done
done
