#!/bin/bash
# t2ops.sh : 后台每 0.1s 执行 lfs changelog_clear <MDT> cl1 0，同时在 /mnt/lustre/work/T2 建 1000×1MB + 删 100，统计 clear 成功次数
M=sxbrbb4v-MDT0000; D=/mnt/lustre/work/T2; mkdir -p $D
( ok=0; n=0; end=$(( $(date +%s) + 120 )); while [ $(date +%s) -lt $end ]; do lfs changelog_clear $M cl1 0 2>/dev/null && ok=$((ok+1)); n=$((n+1)); sleep 0.1; done; echo "clear tries=$n ok=$ok" > /root/t2_clear.txt ) &
sleep 2; echo "ops_start $(date -u +%s.%N)"
seq -f %04g 1 1000 | xargs -P 16 -I{} sh -c "head -c 1048576 /dev/urandom > $D/f{}"
for i in $(seq -f %04g 1 100); do rm -f $D/f$i; done
echo "ops_done $(date -u +%s.%N)"
wait; cat /root/t2_clear.txt
