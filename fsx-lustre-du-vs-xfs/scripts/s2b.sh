source "$(dirname "$0")/common.sh"
stat -f $LMNT; stat -f /mnt/xfs | head -3
lctl get_param osc.*.import 2>/dev/null | grep -iE 'flags|connect_flags|target|ost_' | head -20
lctl get_param osc.*.max_pages_per_rpc osc.*.grant_shrink 2>/dev/null
mkdir -p $LD/s2b; rm -f $LD/s2b/*
for b in 0 1 512 4096 8192 16384 32768 65536 131072 131073 262144 262145 524289 1048575 1048577 2097152 2097153 3145728 4194304 8388608 16777216 33554432 67108864 104857601 209715200 524288000; do
  head -c $b /dev/urandom > $LD/s2b/b_$b
done
stable_remount
echo "bytes|blocks|KiB_alloc|KiB_overhead_vs_4Kround"
for b in 0 1 512 4096 8192 16384 32768 65536 131072 131073 262144 262145 524289 1048575 1048577 2097152 2097153 3145728 4194304 8388608 16777216 33554432 67108864 104857601 209715200 524288000; do
  bl=$(stat -c %b $LD/s2b/b_$b); r=$(( (b+4095)/4096*4 )); echo "$b|$bl|$(echo "scale=1;$bl/2"|bc)|$(echo "scale=1;$bl/2-$r"|bc)"
done
echo "--- empty file + lfs getstripe on b_0 and b_104857601"; lfs getstripe $LD/s2b/b_0 | grep -E 'lcme_flags|l_ost_idx'; lfs getstripe $LD/s2b/b_104857601 | grep -E 'lcme_flags|l_ost_idx'
echo "--- sparse file test: truncate 1G, write 1M at offset 0"
rm -f $LD/s2b/sparse; truncate -s 1G $LD/s2b/sparse; dd if=/dev/urandom of=$LD/s2b/sparse bs=1M count=1 conv=notrunc status=none
echo "--- rewrite test: overwrite a 10M file in place"; dd if=/dev/urandom of=$LD/s2b/b_8388608 bs=1M count=8 conv=notrunc status=none
echo "--- append test: 100x 100KB appends"; rm -f $LD/s2b/app; for i in $(seq 100); do head -c 102400 /dev/urandom >> $LD/s2b/app; done
stable_remount
echo "sparse: $(st $LD/s2b/sparse)"; echo "rewrite8M: $(st $LD/s2b/b_8388608)"; echo "append10000K: $(st $LD/s2b/app)"
