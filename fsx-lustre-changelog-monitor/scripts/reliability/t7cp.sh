#!/bin/bash
# t7cp.sh <N> : 本地 /tmp 准备 N 个 4KB 文件，cp -r 到 Lustre（突发建 + 写），sleep 15 后 rm -rf
N=$1; S=/tmp/src$N; D=/mnt/lustre/work/t7/cp$N
rm -rf $S; mkdir -p $S; (cd $S; seq 1 $N | xargs -n 1000 sh -c 'for i; do head -c 4096 /dev/zero > s$i; done' _)
echo "cp$N cp_start $(date -u +%s.%N)"; cp -r $S $D; echo "cp$N cp_done $(date -u +%s.%N) files=$(ls $D | wc -l)"
sleep 15; echo "cp$N rm_start $(date -u +%s.%N)"; rm -rf $D; echo "cp$N rm_done $(date -u +%s.%N)"
