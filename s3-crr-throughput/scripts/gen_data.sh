#!/bin/bash
# 数据生成脚本（在 us-east-2 c7gn.16xlarge 上以 user-data 运行）
set -euxo pipefail
exec > /var/log/gen.log 2>&1
SRC=s3-crr-src-<E>
cd /root
curl -sL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-arm64.tar.gz | tar xz
# 1) 先完整生成 16MiB 随机源文件（阻塞），再上传
dd if=/dev/urandom of=/dev/shm/src.bin bs=1M count=16
sync
# 2) 生成 131072 条 cp 命令：4 前缀 × 32768，前缀内用 md5 前 2 位散开
python3 -c "
import hashlib
with open('/root/cmds.txt','w') as f:
  for p in range(4):
    for i in range(32768):
      h=hashlib.md5(f'{p}-{i}'.encode()).hexdigest()[:2]
      f.write(f'cp /dev/shm/src.bin s3://$SRC/p{p}/{h}/obj_{i:05d}\n')
"
wc -l /root/cmds.txt
date -u +%FT%TZ > /root/upload_start
/root/s5cmd --numworkers 1024 --retry-count 10 run /root/cmds.txt > /root/upload.out 2>/root/upload.err || true
date -u +%FT%TZ > /root/upload_end
grep -c '^cp' /root/upload.out || true
wc -l /root/upload.err
touch /root/DONE
