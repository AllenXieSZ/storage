source "$(dirname "$0")/common.sh"
mkdir -p $LD/s1; F=$LD/s1/f10m
rm -f $F
for rep in 1 2; do
F=$LD/s1/f10m_$rep; rm -f $F
echo "=== rep $rep ==="
dd if=/dev/urandom of=$F bs=1M count=10 status=none
echo "T0 immediate: $(st $F)"
sync; echo "after sync: $(st $F)"
echo 3 > /proc/sys/vm/drop_caches; echo "sync+drop_caches: $(st $F)"
t=0; for w in 5 10 30 60 120 300; do sleep $((w-t)); t=$w; echo "t=${w}s: $(st $F)"; done
remount; echo "after umount+remount: $(st $F)"
done
# variant: write with no sync at all then remount immediately
F=$LD/s1/f10m_nosync; rm -f $F
dd if=/dev/urandom of=$F bs=1M count=10 status=none; echo "nosync T0: $(st $F)"
remount; echo "nosync remount: $(st $F)"
remount; echo "nosync remount2: $(st $F)"
# a 1GB file too
F=$LD/s1/f1g; rm -f $F
dd if=/dev/urandom of=$F bs=1M count=1024 status=none; echo "1G T0: $(st $F)"
sync; echo "1G sync: $(st $F)"
echo 3 > /proc/sys/vm/drop_caches; echo "1G drop: $(st $F)"
sleep 30; echo "1G 30s: $(st $F)"
remount; echo "1G remount: $(st $F)"
remount; echo "1G remount2: $(st $F)"
lfs getstripe $F | head -30
