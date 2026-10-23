#!/bin/bash
# 校验: 目标桶(们)合并后的 (size,key) 与源 g* 对象一致。参数: run 名
set -eu
cd "$(dirname "$0")"; RUN=$1; OUT=runs/$RUN
: > $OUT/dst_keys.raw
for D in $(cat $OUT/dst_buckets.txt); do
  AWS_REGION=us-west-2 ~/bin/s5cmd ls "s3://$D/*" | awk '{print $3, $4}' >> $OUT/dst_keys.raw
done
grep -E ' g[01]/' $OUT/dst_keys.raw | sort > $OUT/dst_keys.txt
EXTRA=$(grep -vcE ' g[01]/' $OUT/dst_keys.raw || true)
MISS=$(comm -23 runs/src_keys.txt $OUT/dst_keys.txt | wc -l)
MORE=$(comm -13 runs/src_keys.txt $OUT/dst_keys.txt | wc -l)
echo "verify $RUN: dst_g_objs=$(wc -l < $OUT/dst_keys.txt) missing=$MISS extra_g=$MORE non_g(reports etc)=$EXTRA" | tee $OUT/verify.txt
rm -f $OUT/dst_keys.raw
