#!/bin/bash
# 灌 1TB 数据到 S3：50 个 20GB 大文件，分散到 50 个 prefix (p00/ ~ p49/)
# 在压测实例上跑（同 AZ 内网 + S3 gateway endpoint，上传快）
set -e
BUCKET="$1"
if [ -z "$BUCKET" ]; then echo "usage: $0 <bucket>"; exit 1; fi
REGION=us-east-2
NFILES=50
SIZE_GB=20

echo "生成 1 个 ${SIZE_GB}GB 源文件 (随机不可压)..."
# 用 /dev/urandom 太慢，用 openssl 伪随机快很多；测吞吐内容无所谓，但要不可压避免S3端优化
head -c ${SIZE_GB}G /dev/zero | openssl enc -aes-256-ctr -pass pass:seed -nosalt 2>/dev/null > /mnt/src.bin &
GENPID=$!
wait $GENPID
echo "源文件生成完成: $(ls -lh /mnt/src.bin | awk '{print $5}')"

echo "并行上传 ${NFILES} 份到 ${NFILES} 个 prefix..."
UP=0
for i in $(seq 0 $((NFILES-1))); do
  P=$(printf "p%02d" $i)
  aws s3 cp /mnt/src.bin s3://$BUCKET/$P/obj_${P}_20g.bin --region $REGION --only-show-errors &
  UP=$((UP+1))
  # 限制并发上传数，避免本地磁盘/带宽爆
  if [ $((UP % 8)) -eq 0 ]; then wait; fi
done
wait
echo "上传完成。清理源文件。"
rm -f /mnt/src.bin
echo "===== bucket 内容 ====="
aws s3 ls s3://$BUCKET/ --recursive --region $REGION --summarize | tail -5
