source "$(dirname "$0")/common.sh"
mkdir -p $LD/s2 $XD/s2
# name:bs:count  (bytes total)
SIZES="1K:1024:1 10K:10240:1 100K:102400:1 512K:524288:1 1M:1048576:1 10M:1048576:10 100M:1048576:100 1G:1048576:1024 10G:1048576:10240 4097B:4097:1 1000001B:1000001:1"
for s in $SIZES; do IFS=: read n bs c <<< "$s"
  rm -f $LD/s2/f_$n $XD/s2/f_$n
  dd if=/dev/urandom of=$XD/s2/f_$n bs=$bs count=$c status=none
  cp $XD/s2/f_$n $LD/s2/f_$n
done
stable_remount; echo 3 > /proc/sys/vm/drop_caches
echo "name|fs|du_sm|du_sm_apparent|du_k|blocks|blksize|size|stripe"
for s in $SIZES; do IFS=: read n bs c <<< "$s"
 for fs in xfs lustre; do
  [ $fs = xfs ] && f=$XD/s2/f_$n || f=$LD/s2/f_$n
  sc=""; [ $fs = lustre ] && sc="$(lfs getstripe -c $f | tr '\n' ' ')/$(lfs getstripe -S $f | tr '\n' ' ')"
  echo "$n|$fs|$(du -sm $f|cut -f1)|$(du -sm --apparent-size $f|cut -f1)|$(du -sk $f|cut -f1)|$(stat -c '%b|%B|%s' $f)|$sc"
 done
done
sleep 60; echo "--- second remount check (+60s) ---"
remount
for s in $SIZES; do IFS=: read n bs c <<< "$s"; echo "$n $(st $LD/s2/f_$n)"; done
echo "--- md5 sanity 10M ---"; md5sum $XD/s2/f_10M $LD/s2/f_10M
