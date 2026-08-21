#!/usr/bin/env bash
# ab (ApacheBench) 单 URL 冒烟压测模板
# 用法: ./ab_smoke.sh <URL> [总请求数] [并发数]
# 建议: 在 app 机上直连 localhost 测单机后端极限(排除 ALB/网络干扰):
#        ./ab_smoke.sh http://localhost/ 10000 100
set -euo pipefail

URL="${1:?用法: ./ab_smoke.sh <URL> [总请求数] [并发数]}"
N="${2:-10000}"    # 总请求数
C="${3:-100}"      # 并发

command -v ab >/dev/null 2>&1 || {
  echo "未安装 ab，请先安装:"
  echo "  Amazon Linux/RHEL: sudo dnf install -y httpd-tools"
  echo "  Ubuntu/Debian:     sudo apt-get install -y apache2-utils"
  exit 1
}

echo "=== ab 冒烟: $URL  (n=$N c=$C, keep-alive) ==="
# -k 开 keep-alive(更贴近真实), -l 允许响应长度波动(动态页必开，否则大量 Length 计为失败)
ab -k -l -n "$N" -c "$C" "$URL"
