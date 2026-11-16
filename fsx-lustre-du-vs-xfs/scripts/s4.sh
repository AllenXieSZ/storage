source "$(dirname "$0")/common.sh"
for base in $XD $LD; do rm -rf $base/s4; mkdir -p $base/s4/blobs $base/s4/snap; head -c 102400 /dev/urandom > $base/s4/blobs/x
 for i in $(seq 1000); do ln -s ../blobs/x$(printf %060d $i) $base/s4/snap/l_$i; done; done
stable_remount
for base in $XD $LD; do echo "$base snap(1000 symlinks, 69B target) du_k=$(du -sk $base/s4/snap|cut -f1) du_sm=$(du -sm $base/s4/snap|cut -f1) per-link blocks: $(stat -c %b $base/s4/snap/l_1) dir blocks=$(stat -c %b $base/s4/snap)"; done
lctl get_param -n osc.*.import | grep -iE 'ocd|brw|grant|cksum' | head; lctl get_param osc.*.cur_grant_bytes osc.*.max_dirty_mb 2>/dev/null
rm -rf $LD/dutest /mnt/xfs/dutest; df -h /mnt/lustre
