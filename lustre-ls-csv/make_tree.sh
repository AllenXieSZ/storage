#!/bin/bash
# make_tree.sh — 在 Lustre 挂载点下建 4 层目录树
# 规则：每个目录下建 5 个子目录 + 10 个文件（1M~10M），共 4 层目录（含根为第1层）。
# 层级：L1(根下5) -> 每个再5 = L2(25) -> L3(125) -> L4(625)。
# 每个目录（包括根测试目录、L1/L2/L3/L4 所有目录）都放 10 个文件。
set -euo pipefail

ROOT="${1:-/mnt/lustre/tree}"
SUBDIRS=5
FILES_PER_DIR=10
MAX_DEPTH=4   # 目录层数（不含根 ROOT 本身之外，ROOT 记为第0层容器）

mkdir -p "$ROOT"

# 生成 10 个 1M~10M 文件到指定目录
make_files() {
    local dir="$1"
    for i in $(seq 1 $FILES_PER_DIR); do
        # 大小 1..10 MiB
        local mb=$(( (RANDOM % 10) + 1 ))
        dd if=/dev/urandom of="$dir/file_${i}_${mb}M.bin" bs=1M count=$mb status=none
    done
}

# 递归建目录树
build() {
    local parent="$1"
    local depth="$2"
    make_files "$parent"
    if [ "$depth" -ge "$MAX_DEPTH" ]; then
        return
    fi
    for s in $(seq 1 $SUBDIRS); do
        local child="$parent/d${depth}_${s}"
        mkdir -p "$child"
        build "$child" $((depth + 1))
    done
}

echo "Building tree under $ROOT (subdirs=$SUBDIRS, files/dir=$FILES_PER_DIR, depth=$MAX_DEPTH)..."
build "$ROOT" 1
echo "Done."
echo "Total dirs: $(find "$ROOT" -type d | wc -l)"
echo "Total files: $(find "$ROOT" -type f | wc -l)"
