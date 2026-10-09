#!/bin/bash
# 把已切好的文件按日期分区上传到 S3，成功后删除本地
SPOOL=${SPOOL:-/var/spool/lustre-changelog}; BUCKET=$1; PREFIX=${2:-lustre-changelog}
for f in $SPOOL/ready/*.jsonl.gz; do
  [ -e "$f" ] || continue
  b=$(basename $f); mdt=${b%%_*}; ts=${b##*_}; d=${ts:0:4}-${ts:4:2}-${ts:6:2}
  aws s3 cp "$f" "s3://$BUCKET/$PREFIX/mdt=$mdt/dt=$d/$b" --only-show-errors && rm -f "$f"
done
