#!/bin/bash
# user-data：新加坡 c8gn.16xlarge 上生成 131072 × 16MiB（g/p 两层布局，与第一轮一致）
exec > /var/log/gen.log 2>&1
set -x
cd /root; SRC=s3-crr-src-sg-<E>
export AWS_REGION=ap-southeast-1
curl -sL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-arm64.tar.gz | tar xz
dd if=/dev/urandom of=/dev/shm/src.bin bs=1M count=16; sync
python3 -c "
import hashlib
with open('/root/cmds.txt','w') as f:
  for p in range(4):
    g=p//2
    for i in range(32768):
      h=hashlib.md5(f'{p}-{i}'.encode()).hexdigest()[:2]
      f.write(f'cp /dev/shm/src.bin s3://$SRC/g{g}/p{p}/{h}/obj_{i:05d}\n')
"
wc -l cmds.txt; head -1 cmds.txt; md5sum /dev/shm/src.bin
date -u +%FT%TZ > upload_start
./s5cmd --numworkers 1024 --retry-count 10 run cmds.txt > upload.out 2> upload.err
date -u +%FT%TZ > upload_end
cat upload_start upload_end; grep -c '^cp' upload.out; wc -l < upload.err
./s5cmd ls --all-versions "s3://$SRC/*" | wc -l
./s5cmd du "s3://$SRC/*"
touch /root/DONE
