#!/usr/bin/env bash
# wrk 启动封装: 参数化 线程/连接/时长/脚本
# 用法: ./run_wrk.sh <threads> <connections> <duration> <lua脚本> [TARGET]
# 例:   TARGET=http://alb-dns ./run_wrk.sh 12 600 300s wrk_cart_add.lua
set -euo pipefail

T="${1:?线程数}"
C="${2:?连接数}"
D="${3:?时长 如 60s/5m}"
LUA="${4:?lua脚本路径}"
TARGET="${5:-${TARGET:?请设置 TARGET 环境变量或作为第5个参数传入}}"

command -v wrk >/dev/null 2>&1 || {
  echo "未安装 wrk，安装方式:"
  echo "  Amazon Linux: sudo dnf install -y git gcc openssl-devel && \\"
  echo "                git clone https://github.com/wg/wrk && cd wrk && make && sudo cp wrk /usr/local/bin/"
  echo "  Ubuntu:       sudo apt-get install -y wrk   (或同上源码编译)"
  exit 1
}

echo "=== wrk: t=$T c=$C d=$D script=$LUA target=$TARGET ==="
wrk -t"$T" -c"$C" -d"$D" --latency -s "$LUA" "$TARGET"
