#!/usr/bin/env bash
# 统计 S3 前缀下每个文件的版本数、删除标记数，以及最新版本是对象还是删除标记
# 用法: ./s3-version-check.sh <bucket> <prefix1> [prefix2 ...]
#   例: AWS_REGION=us-east-2 ./s3-version-check.sh my-bucket bidir export
set -euo pipefail
B="${1:?用法: $0 <bucket> <prefix1> [prefix2 ...]}"; shift
REGION="${AWS_REGION:-us-east-2}"
echo "bucket=$B  versioning=$(aws s3api get-bucket-versioning --region "$REGION" --bucket "$B" --query Status --output text)"
for p in "$@"; do
 echo "== s3://$B/$p/"
 aws s3api list-object-versions --region "$REGION" --bucket "$B" --prefix "$p/" --output json | python3 -c '
import json,sys,collections
d=json.load(sys.stdin); c=collections.defaultdict(lambda:[0,0,False])
for v in d.get("Versions") or []:
    k=v["Key"].split("/")[-1]
    if not k: continue
    c[k][0]+=1; c[k][2]=c[k][2] or v["IsLatest"]
for m in d.get("DeleteMarkers") or []:
    k=m["Key"].split("/")[-1]; c[k][1]+=1
    if m["IsLatest"]: c[k][2]="DEL"
print("  files=%d versions=%d deletemarkers=%d"%(len(c),sum(x[0] for x in c.values()),sum(x[1] for x in c.values())))
for k in sorted(c): print("   %-12s versions=%d delmarkers=%d latest=%s"%(k,c[k][0],c[k][1],"删除标记" if c[k][2]=="DEL" else "对象"))
'
done
