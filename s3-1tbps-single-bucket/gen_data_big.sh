#!/bin/bash
set -e
BUCKET="$1"; NFILES="${2:-200}"; SIZE_GB="${3:-20}"
REGION=us-east-2
# 步骤1: 完整生成源文件(阻塞直到完成)
if [ ! -f /mnt/src.bin ] || [ "$(stat -c%s /mnt/src.bin 2>/dev/null || echo 0)" -lt $((SIZE_GB*1000000000)) ]; then
  echo "生成 ${SIZE_GB}GB 源文件..."
  head -c ${SIZE_GB}G /dev/zero | openssl enc -aes-256-ctr -pass pass:seed -nosalt 2>/dev/null > /mnt/src.bin
fi
SZ=$(stat -c%s /mnt/src.bin)
echo "源文件就绪: $SZ bytes"
# 步骤2: 并行上传(源文件已固定大小,不会 IncompleteBody)
echo "上传 ${NFILES} 份到 ${NFILES} prefix..."
UP=0
for i in $(seq 0 $((NFILES-1))); do
  P=$(printf "p%03d" $i)
  aws s3 cp /mnt/src.bin s3://$BUCKET/$P/obj_${P}.bin --region $REGION --only-show-errors && echo "ok $P" &
  UP=$((UP+1)); [ $((UP % 12)) -eq 0 ] && wait
done
wait
rm -f /mnt/src.bin
echo "DONE objects=$(aws s3 ls s3://$BUCKET/ --recursive --region $REGION | wc -l)"
