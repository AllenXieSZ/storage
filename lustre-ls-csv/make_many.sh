#!/bin/bash
# make_many.sh — 在 Lustre 下建 5 层目录树 + 指定数量小文件（均匀撒到所有目录）
# 用法: make_many.sh <root> <total_files> [subdirs] [depth]
# 小文件：4KB~64KB 随机（真正的小文件，重点测元数据/列举性能，不是吞吐）
set -euo pipefail

ROOT="${1:-/mnt/lustre/many}"
TOTAL="${2:-100000}"
SUBDIRS="${3:-5}"
DEPTH="${4:-5}"

mkdir -p "$ROOT"

# 1) 先建 5 层目录骨架（每目录 SUBDIRS 个子目录）
build_dirs() {
    local parent="$1" d="$2"
    [ "$d" -ge "$DEPTH" ] && return
    for s in $(seq 1 $SUBDIRS); do
        local c="$parent/d${d}_${s}"
        mkdir -p "$c"
        build_dirs "$c" $((d+1))
    done
}
echo "[$(date +%T)] Building dir skeleton (subdirs=$SUBDIRS depth=$DEPTH)..."
build_dirs "$ROOT" 1

# 2) 收集所有目录（含中间层），把文件均匀撒进去
mapfile -t DIRS < <(find "$ROOT" -type d)
NDIRS=${#DIRS[@]}
echo "[$(date +%T)] Dirs=$NDIRS ; distributing $TOTAL files..."

# 每目录分多少文件
PER=$(( TOTAL / NDIRS ))
REM=$(( TOTAL % NDIRS ))

# 预生成一个随机源块（复用，避免每文件都读 urandom 太慢）
SRC="/tmp/_randsrc.bin"
dd if=/dev/urandom of="$SRC" bs=64k count=1 status=none

gen_in_dir() {
    local dir="$1" n="$2" startidx="$3"
    for ((i=0; i<n; i++)); do
        # 4KB~64KB 随机
        local kb=$(( (RANDOM % 61) + 4 ))
        head -c $((kb*1024)) "$SRC" > "$dir/f_$((startidx+i))_${kb}k.dat" 2>/dev/null || \
          head -c $((kb*1024)) /dev/urandom > "$dir/f_$((startidx+i))_${kb}k.dat"
    done
}

idx=0
di=0
for d in "${DIRS[@]}"; do
    n=$PER
    if [ $di -lt $REM ]; then n=$((n+1)); fi
    gen_in_dir "$d" "$n" "$idx" &
    idx=$((idx + n))
    di=$((di+1))
    # 控制并发，避免 fork 爆炸
    if [ $((di % 32)) -eq 0 ]; then wait; fi
done
wait

echo "[$(date +%T)] Done."
echo "Total dirs: $(find "$ROOT" -type d | wc -l)"
echo "Total files: $(find "$ROOT" -type f | wc -l)"
