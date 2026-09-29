#!/bin/bash
# EFS write test across different mount wsize values.
# For each wsize: mount EFS (NFS4.1, no TLS so we can control wsize), verify actual
# negotiated wsize, then run the 200MiB write bench with FIXED app pwrite size = 1MiB.
set -e
EFSID="$1"
REGION="us-east-2"
EFS_DNS="${EFSID}.efs.${REGION}.amazonaws.com"
MNT=/mnt/efs
WSIZES="65536 262144 524288 1048576"   # 64K 256K 512K 1M
APP_IO=1048576                          # fixed app pwrite = 1 MiB
FILE_SIZE=$((200*1024*1024))
ROUNDS=3

sudo mkdir -p $MNT
echo "=== wsize sweep on $EFS_DNS ==="
for WS in $WSIZES; do
  sudo umount $MNT 2>/dev/null || true
  # direct NFS4.1 mount with explicit rsize/wsize (per AWS non-helper mount option doc)
  sudo mount -t nfs4 -o nfsvers=4.1,rsize=$WS,wsize=$WS,hard,timeo=600,retrans=2,noresvport \
    $EFS_DNS:/ $MNT
  sudo chown ec2-user:ec2-user $MNT
  ACTUAL=$(nfsstat -m | grep -A1 "$MNT" | grep -o 'wsize=[0-9]*' | head -1)
  echo "### requested wsize=$WS  -> mounted $ACTUAL"
  python3 /tmp/efs_wsize_bench.py $MNT $APP_IO $WS $FILE_SIZE $ROUNDS
done
sudo umount $MNT 2>/dev/null || true
