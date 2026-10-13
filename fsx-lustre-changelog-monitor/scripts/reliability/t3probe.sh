#!/bin/bash
# t3probe.sh <MDT> <N> <tag> : 每次 touch 一个唯一文件，然后每 0.2s 跑 lfs changelog <MDT>（非 follow）
# 记录：首次看到该 CREAT 的时间、最后一次看到的时间 → 存活时长 = 最后看到 - 操作时间
M=$1; N=$2; TAG=$3; D=/mnt/lustre/work/t3; mkdir -p $D
for k in $(seq 1 $N); do
  f=t3_${TAG}_${k}_$RANDOM; t0=$(date +%s.%N); touch $D/$f
  first=""; last=""
  for j in $(seq 1 600); do                 # 最多 120s
    now=$(date +%s.%N)
    if lfs changelog $M 2>/dev/null | grep -q " $f\$\| $f "; then [ -z "$first" ] && first=$now; last=$now
    elif [ -n "$first" ]; then break; fi
    sleep 0.2
  done
  echo "$k $f op=$t0 first=$first last=$last gone=$now" | awk '{split($3,a,"=");split($4,b,"=");split($5,c,"=");split($6,d,"="); printf "%s %s seen_after=%.2f alive=%.2f gone_after=%.2f\n",$1,$2,(b[2]?b[2]-a[2]:-1),(c[2]?c[2]-a[2]:-1),d[2]-a[2]}'
  sleep 1
done
