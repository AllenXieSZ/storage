source "$(dirname "$0")/common.sh"
echo "nosync file from s1, now (minutes later): $(st $LD/s1/f10m_nosync)"
remount; echo "nosync file after another remount: $(st $LD/s1/f10m_nosync)"
for X in 0 2 5 10 20 40; do
  F=$LD/s1/w_$X; rm -f $F
  dd if=/dev/urandom of=$F bs=1M count=10 status=none; sync; sleep $X; remount
  a=$(stat -c %b $F); sleep 10; remount; b=$(stat -c %b $F); sleep 60; remount; c=$(stat -c %b $F)
  echo "wait=${X}s remount->blocks=$a  (+10s remount)=$b  (+70s remount)=$c"
done
# does lfs data_version / ladvise / lctl set_param ldlm lru clear refresh without umount?
F=$LD/s1/lru; rm -f $F; dd if=/dev/urandom of=$F bs=1M count=10 status=none; sync; sleep 40
echo "lru test before: $(stat -c %b $F)"
lctl set_param -n ldlm.namespaces.*.lru_size=clear; echo "after ldlm lru clear: $(stat -c %b $F)"
remount; echo "after remount: $(stat -c %b $F)"
