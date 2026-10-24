#!/bin/bash
# 校验: 目标桶 (size,key) 与源 obj_ 对象逐条一致 + 抽样 head-object。参数: run 名
set -eu
cd "$(dirname "$0")"; RUN=$1; OUT=runs/$RUN; D=$(cat $OUT/dst_buckets.txt); E=$(cat EPOCH)
AWS_REGION=us-west-2 ~/bin/s5cmd --numworkers 256 ls "s3://$D/*" | awk '{print $3, $4}' > $OUT/dst_keys.raw
grep -E ' [0-9a-f]{3}/obj_' $OUT/dst_keys.raw | sort > $OUT/dst_keys.txt
EXTRA=$(grep -vcE ' [0-9a-f]{3}/obj_' $OUT/dst_keys.raw || true)
MISS=$(comm -23 runs/src_keys.txt $OUT/dst_keys.txt | wc -l)
MORE=$(comm -13 runs/src_keys.txt $OUT/dst_keys.txt | wc -l)
echo "verify $RUN: dst_obj=$(wc -l < $OUT/dst_keys.txt) missing=$MISS extra_obj=$MORE non_obj(reports etc)=$EXTRA" | tee $OUT/verify.txt
for k in $(shuf -n 5 --random-source=<(yes) runs/src_keys.txt | awk '{print $2}'); do
  aws s3api head-object --bucket $D --key $k --region us-west-2 --query '[ContentLength,ReplicationStatus,ETag,ServerSideEncryption]' --output text | sed "s#^#head $k #" | tee -a $OUT/verify.txt
  aws s3api head-object --bucket s3-crr-src-small-$E --key $k --region us-east-2 --query '[ContentLength,ReplicationStatus,ETag]' --output text | sed "s#^#  src  #" | tee -a $OUT/verify.txt
done
rm -f $OUT/dst_keys.raw; gzip -f $OUT/dst_keys.txt
