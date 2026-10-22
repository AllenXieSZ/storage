set -x
cd /root; SRC=s3-crr-src-<E>
./s5cmd --numworkers 512 rm --all-versions "s3://$SRC/*" > rm2.out 2>&1; ./s5cmd ls --all-versions "s3://$SRC/*" | wc -l
python3 -c "
import hashlib
with open('/root/cmds.txt','w') as f:
  for p in range(4):
    g=p//2
    for i in range(32768):
      h=hashlib.md5(f'{p}-{i}'.encode()).hexdigest()[:2]
      f.write(f'cp /dev/shm/src.bin s3://$SRC/g{g}/p{p}/{h}/obj_{i:05d}\n')
"
wc -l cmds.txt; head -1 cmds.txt; ls -l /dev/shm/src.bin; md5sum /dev/shm/src.bin
date -u +%FT%TZ > upload_start
./s5cmd --numworkers 1024 --retry-count 10 run cmds.txt > upload.out 2> upload.err
date -u +%FT%TZ > upload_end
cat upload_start upload_end; grep -c '^cp' upload.out; wc -l < upload.err
./s5cmd ls --all-versions "s3://$SRC/*" | wc -l
./s5cmd du "s3://$SRC/*"
