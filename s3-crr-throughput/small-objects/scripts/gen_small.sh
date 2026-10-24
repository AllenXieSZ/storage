#!/bin/bash
# 小文件数据生成（user-data, c7gn.16xlarge us-east-2）：1,024,000 × 512 KiB。完成后结果写源桶 _gen/ 再关机(terminate)。
set -x
exec > /var/log/gen.log 2>&1
SRC=s3-crr-src-small-1792770913
cd /root
curl -sL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-arm64.tar.gz | tar xz
dd if=/dev/urandom of=/dev/shm/src.bin bs=512K count=1; sync
ls -l /dev/shm/src.bin; md5sum /dev/shm/src.bin
python3 -c "
import hashlib
with open('/root/cmds.txt','w') as f:
  for i in range(1024000):
    h=hashlib.md5(str(i).encode()).hexdigest()[:3]
    f.write(f'cp /dev/shm/src.bin s3://$SRC/{h}/obj_{i:07d}\n')
"
wc -l cmds.txt
date -u +%FT%TZ > upload_start
./s5cmd --numworkers 2048 --retry-count 10 run cmds.txt > upload.out 2> upload.err
date -u +%FT%TZ > upload_end
# 补传缺失
AWS_REGION=us-east-2 ./s5cmd ls "s3://$SRC/*" | awk '{print $4}' | sort > have.txt
awk '{print $3}' cmds.txt | sed "s#s3://$SRC/##" | sort > want.txt
comm -23 want.txt have.txt > missing.txt
if [ -s missing.txt ]; then sed "s#^#cp /dev/shm/src.bin s3://$SRC/#" missing.txt > retry.txt; ./s5cmd --numworkers 512 --retry-count 10 run retry.txt > retry.out 2> retry.err; fi
date -u +%FT%TZ > retry_end
{ cat upload_start upload_end retry_end; grep -c '^cp' upload.out; wc -l < upload.err; head -5 upload.err; echo "missing_after_pass1=$(wc -l < missing.txt)"; md5sum /dev/shm/src.bin; ./s5cmd du "s3://$SRC/*"; } > gen_output.txt 2>&1
cp /var/log/gen.log gen.log
aws s3 cp gen_output.txt s3://$SRC/_gen/gen_output.txt --region us-east-2 || true
aws s3 cp gen.log s3://$SRC/_gen/gen.log --region us-east-2 || true
shutdown -h now
