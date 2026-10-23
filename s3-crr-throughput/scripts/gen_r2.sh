#!/bin/bash
# Round2 数据生成（user-data, c7gn.16xlarge us-east-2）。完成后结果写到源桶 _gen/ 再关机(terminate)。
set -x
exec > /var/log/gen.log 2>&1
SRC=s3-crr-src-1792758433
cd /root
curl -sL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-arm64.tar.gz | tar xz
dd if=/dev/urandom of=/dev/shm/src.bin bs=1M count=16; sync
md5sum /dev/shm/src.bin
python3 -c "
import hashlib
with open('/root/cmds.txt','w') as f:
  for p in range(4):
    g=p//2
    for i in range(32768):
      h=hashlib.md5(f'{p}-{i}'.encode()).hexdigest()[:2]
      f.write(f'cp /dev/shm/src.bin s3://$SRC/g{g}/p{p}/{h}/obj_{i:05d}\n')
"
wc -l cmds.txt
date -u +%FT%TZ > upload_start
./s5cmd --numworkers 1024 --retry-count 10 run cmds.txt > upload.out 2> upload.err
date -u +%FT%TZ > upload_end
{ cat upload_start upload_end; grep -c '^cp' upload.out; wc -l < upload.err; md5sum /dev/shm/src.bin; ./s5cmd du "s3://$SRC/g*"; } > gen_output.txt 2>&1
cp /var/log/gen.log gen.log
aws s3 cp gen_output.txt s3://$SRC/_gen/gen_output.txt --region us-east-2 || true
aws s3 cp gen.log s3://$SRC/_gen/gen.log --region us-east-2 || true
shutdown -h now
