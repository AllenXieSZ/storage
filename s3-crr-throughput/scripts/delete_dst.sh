#!/bin/bash
# 删除目标桶全部版本 + metrics 配置 + 桶本身。参数: 桶名列表文件
set -u
for D in $(cat "$1"); do
  AWS_REGION=us-west-2 ~/bin/s5cmd --numworkers 256 rm --all-versions "s3://$D/*" > /tmp/rm-$D.out 2>&1
  left=$(AWS_REGION=us-west-2 ~/bin/s5cmd ls --all-versions "s3://$D/*" 2>/dev/null | wc -l)
  aws s3api delete-bucket-metrics-configuration --bucket $D --id all --region us-west-2 2>/dev/null
  aws s3api delete-bucket --bucket $D --region us-west-2 && echo "deleted $D (left_before_delete=$left) $(date -u +%FT%TZ)" || echo "DELETE FAILED $D left=$left"
done
