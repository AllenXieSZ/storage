#!/bin/bash
# t7burst.sh <N> <tag> : 突发：并行(-P 32)建 N 个空文件 → sleep 15 → rm -rf 整个目录。打印各阶段时间
N=$1; T=$2; D=/mnt/lustre/work/t7/$T; mkdir -p $D
echo "$T create_start $(date -u +%s.%N)"
seq 1 $N | xargs -P 32 -n 500 sh -c 'cd '$D' && touch "$@"' _
echo "$T create_done $(date -u +%s.%N) files=$(ls $D | wc -l)"
sleep 15
echo "$T rm_start $(date -u +%s.%N)"
rm -rf $D
echo "$T rm_done $(date -u +%s.%N)"
