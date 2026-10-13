#!/bin/bash
# t1ops.sh <tag> : 在 DRA 目录 /mnt/lustre/work/<tag> 下：建 5000×1MB、覆盖写 500、rename 200、删 200
# 输出 /root/t1_<tag>.meta（各阶段 UTC 时间）、/root/t1_<tag>.md5（覆盖写后文件 md5）
set -e
T=$1; D=/mnt/lustre/work/$T; mkdir -p $D; M=/root/t1_$T.meta
echo "start $(date -u +%s.%N)" > $M
seq -w 1 5000 | xargs -P 16 -I{} sh -c "head -c 1048576 /dev/urandom > $D/f{}"
echo "created $(date -u +%s.%N)" >> $M
seq -f %04g 1 500 | xargs -P 16 -I{} sh -c "head -c 1048576 /dev/urandom > $D/f{}"      # 覆盖写 f0001-f0500
echo "overwritten $(date -u +%s.%N)" >> $M
for i in $(seq -w 1001 1200); do mv $D/f$i $D/r$i; done                               # rename 200
for i in $(seq -w 2001 2200); do rm -f $D/f$i; done                                   # 删 200
echo "done $(date -u +%s.%N)" >> $M
(cd $D; md5sum f0001 f0050 f0100 f0200 f0300 f0400 f0500 f0600 f3000 f4999 r1001 r1100 r1200) > /root/t1_$T.md5
ls $D | wc -l >> $M
