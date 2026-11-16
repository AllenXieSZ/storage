source "$(dirname "$0")/common.sh"
SC=$1; NBIG=$2; NSMALL=$3; SMALLFIX=$4   # SMALLFIX empty => random 1-100KB
for base in $XD $LD; do rm -rf $base/s3_$SC; done
G=$XD/s3_$SC; mkdir -p $G/blobs $G/snap
RANDOM=42
for i in $(seq 1 $NBIG); do dd if=/dev/urandom of=$G/blobs/big_$i bs=1M count=10240 status=none; done
for i in $(seq 1 $NSMALL); do
  if [ -n "$SMALLFIX" ]; then sz=$SMALLFIX; else sz=$(( (RANDOM % 100 + 1) * 1024 - (RANDOM % 1024) )); fi
  head -c $sz /dev/urandom > $G/snap/s_$i.json
done
# copy to lustre (identical content/sizes)
cp -a $G $LD/s3_$SC
stable_remount; echo 3 > /proc/sys/vm/drop_caches
echo "SCENARIO $SC files: xfs=$(find $XD/s3_$SC -type f|wc -l) lustre=$(find $LD/s3_$SC -type f|wc -l)"
for d in $XD/s3_$SC $LD/s3_$SC; do
  echo "$d du_sm=$(du -sm $d|cut -f1) du_sm_apparent=$(du -sm --apparent-size $d|cut -f1) du_k=$(du -sk $d|cut -f1) du_b_apparent=$(du -sb $d|cut -f1)"
  echo "  big:   du_k=$(du -sk $d/blobs|cut -f1) apparent_b=$(du -sb $d/blobs|cut -f1)"
  echo "  small: du_k=$(du -sk $d/snap|cut -f1) apparent_b=$(du -sb $d/snap|cut -f1)"
  echo "  dirs du -sk (dir inode only):"; for x in $d $d/blobs $d/snap; do echo "    $x $(stat -c 'blocks=%b size=%s' $x)"; done
  echo "  sum file st_blocks*512/1024 (KiB): $(find $d -type f -printf '%b\n' | awk '{s+=$1}END{print s/2}')"
done
echo "per-file small blocks histogram lustre (blocks:count):"; find $LD/s3_$SC/snap -type f -printf '%b\n' | sort -n | uniq -c | sort -rn | head -10
echo "per-file small blocks histogram xfs:"; find $XD/s3_$SC/snap -type f -printf '%b\n' | sort -n | uniq -c | sort -rn | head -10
echo "big file blocks lustre/xfs:"; for i in 1 2; do stat -c '%n %b %s' $LD/s3_$SC/blobs/big_$i $XD/s3_$SC/blobs/big_$i; done
sleep 60; remount; echo "second remount (+60s) du_k lustre: $(du -sk $LD/s3_$SC|cut -f1)"
echo "size distribution small files (bytes) min/max/avg: $(find $XD/s3_$SC/snap -type f -printf "%s\n" | sort -n | awk "NR==1{mi=\$1}{s+=\$1;ma=\$1}END{print mi,ma,s/NR}")"
rm -rf $XD/s3_$SC; date
