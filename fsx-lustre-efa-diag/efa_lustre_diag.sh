#!/usr/bin/env bash
#
# efa_lustre_diag.sh — EFA + FSx Lustre 一键诊断脚本
#
# 分四层自动诊断 EFA / LNet / Lustre / AWS 基础设施，输出结构化报告。
# 用于定位 "OST DISCONN / fio 卡在 Laying out IO file / CREATE_AH err -22" 类故障。
#
# 用法:
#   sudo ./efa_lustre_diag.sh                      # 全量诊断
#   sudo ./efa_lustre_diag.sh --fsid fs-xxxx --region us-east-2  # 带 AWS 侧检查
#   sudo ./efa_lustre_diag.sh --mount /fsx         # 指定挂载点
#
# 需要: root (读 dmesg/内核参数); 可选 aws cli (第4层 AWS 检查)
#
# 作者: openclaw 助手，基于伟伟 FSx Lustre EFA 实测经验沉淀
# 心法: 一次只改一个变量; OST 状态看 ost_server_uuid 不看 lnetctl peer state
#
set -uo pipefail

# ---------- 参数 ----------
FSID=""
REGION="${AWS_DEFAULT_REGION:-us-east-2}"
MOUNT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fsid)   FSID="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --mount)  MOUNT="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^#//'; exit 0 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done

# ---------- 颜色/工具 ----------
if [[ -t 1 ]]; then
  RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; BLU=$'\e[34m'; BOLD=$'\e[1m'; RST=$'\e[0m'
else
  RED=""; GRN=""; YEL=""; BLU=""; BOLD=""; RST=""
fi
PASS=0; WARN=0; FAIL=0
ok()   { echo "${GRN}[ OK ]${RST} $*"; PASS=$((PASS+1)); }
warn() { echo "${YEL}[WARN]${RST} $*"; WARN=$((WARN+1)); }
bad()  { echo "${RED}[FAIL]${RST} $*"; FAIL=$((FAIL+1)); }
info() { echo "       $*"; }
hdr()  { echo; echo "${BOLD}${BLU}===== $* =====${RST}"; }
has()  { command -v "$1" >/dev/null 2>&1; }

echo "${BOLD}EFA + FSx Lustre 诊断报告 — $(date '+%F %T %Z')${RST}"
echo "host=$(hostname) kernel=$(uname -r)"

# =====================================================================
hdr "第 0 层: 环境与身份"
# =====================================================================
if [[ $EUID -ne 0 ]]; then
  warn "非 root 运行，dmesg / 部分内核参数可能读不到，建议 sudo"
else
  ok "root 权限"
fi

# IMDS: 取本机 AZ / instance-type / instance-id (兼容 IMDSv2)
IMDS="http://169.254.169.254/latest"
TOKEN=$(curl -s -m 2 -X PUT "$IMDS/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300" 2>/dev/null || true)
imds() { curl -s -m 2 ${TOKEN:+-H "X-aws-ec2-metadata-token: $TOKEN"} "$IMDS/meta-data/$1" 2>/dev/null; }
MY_AZ=$(imds placement/availability-zone)
MY_TYPE=$(imds instance-type)
MY_ID=$(imds instance-id)
MY_SUBNET=$(imds "network/interfaces/macs/$(imds network/interfaces/macs/ | head -1)subnet-id" 2>/dev/null)
if [[ -n "$MY_AZ" ]]; then
  ok "本机 AZ=$MY_AZ  type=$MY_TYPE  id=$MY_ID  subnet=$MY_SUBNET"
else
  warn "无法读取 IMDS (非 EC2 或 IMDS 被禁)，跳过 AZ 自动检查"
fi

# =====================================================================
hdr "第 1 层: EFA 物理设备 / 内核模块"
# =====================================================================
if has lspci && lspci 2>/dev/null | grep -qi efa; then
  ok "lspci 检测到 EFA 设备:"
  lspci | grep -i efa | sed 's/^/       /'
else
  bad "lspci 未检测到 EFA 设备 (机型不支持 EFA 或未启用 EFA 接口)"
fi

for m in efa ib_core rdma_cm; do
  if lsmod 2>/dev/null | grep -qw "$m"; then ok "内核模块已加载: $m"; else warn "内核模块未加载: $m"; fi
done
if lsmod 2>/dev/null | grep -qw nvidia_fs; then
  ok "nvidia_fs 已加载 (GDS 场景)"
else
  info "nvidia_fs 未加载 (仅 GPUDirect Storage 需要，非 GDS 可忽略)"
fi

if has ibv_devinfo; then
  echo "       --- ibv_devinfo (fw_ver 0.0.0.0 / cap_flags 0x0 是 EFA 正常值，非故障) ---"
  ibv_devinfo 2>/dev/null | grep -iE "hca_id|fw_ver|state|link_layer" | sed 's/^/       /'
else
  warn "无 ibv_devinfo (rdma-core / libibverbs-utils 未装)"
fi

# =====================================================================
hdr "第 2 层: EFA 用户态栈 (libfabric)"
# =====================================================================
if [[ -f /opt/amazon/efa_installed_packages ]]; then
  ok "EFA installer 已安装:"
  grep -iE "efa-config|efa-profile|libfabric|version|installer" /opt/amazon/efa_installed_packages 2>/dev/null | head -8 | sed 's/^/       /'
else
  warn "未找到 /opt/amazon/efa_installed_packages (可能未用官方 EFA installer)"
fi

FI_INFO_BIN=""
for c in fi_info /opt/amazon/efa/bin/fi_info; do has "${c%% *}" 2>/dev/null && { FI_INFO_BIN=$c; break; }; [[ -x $c ]] && { FI_INFO_BIN=$c; break; }; done
if [[ -n "$FI_INFO_BIN" ]]; then
  if $FI_INFO_BIN -p efa >/dev/null 2>&1; then
    ok "fi_info -p efa 成功枚举到 EFA provider (用户态栈就绪)"
    $FI_INFO_BIN -p efa 2>/dev/null | grep -iE "provider|fabric|domain|type" | head -6 | sed 's/^/       /'
  else
    bad "fi_info -p efa 无法枚举 EFA provider — EFA 用户态栈异常"
  fi
else
  warn "未找到 fi_info，无法验证 libfabric EFA provider"
fi
info "提示: 隔离测试用 fi_pingpong — 一端 'fi_pingpong -p efa'，另一端 'fi_pingpong -p efa <server_ip>'"

# =====================================================================
hdr "第 3 层: LNet / Lustre"
# =====================================================================
# 3.1 lustre 模块
if lsmod 2>/dev/null | grep -qw lustre; then
  ok "lustre 内核模块已加载"
else
  bad "lustre 内核模块未加载 — 可能内核漂移 (AMI 克隆后自动升级内核)"
  info "修复: sudo /opt/aws/... install-fsx-lustre-client.sh --install-lustre (给当前内核 $(uname -r) 重装模块)"
fi

# 3.2 LNet 网络与 NID
if has lnetctl; then
  echo "       --- lnetctl net show ---"
  lnetctl net show 2>/dev/null | sed 's/^/       /'
  if lnetctl net show 2>/dev/null | grep -qi "net type: efa"; then
    ok "LNet 已配置 efa 网络"
  else
    warn "LNet 未见 efa 网络类型 (configure-efa 服务可能未生效)"
  fi
else
  warn "无 lnetctl (Lustre 客户端未装或版本过老)"
fi
if has lctl; then
  echo "       --- 本机 NID (lctl list_nids) ---"
  lctl list_nids 2>/dev/null | sed 's/^/       /'
fi

# 3.3 OST 连接状态 (权威判据!)
if has lctl; then
  echo "       --- OST 状态 (lctl get_param osc.*.ost_server_uuid) ---"
  OSC_OUT=$(lctl get_param osc.*.ost_server_uuid 2>/dev/null)
  if [[ -z "$OSC_OUT" ]]; then
    warn "无 osc 参数 — 文件系统可能未挂载"
  else
    TOTAL=$(echo "$OSC_OUT" | wc -l)
    NOTFULL=$(echo "$OSC_OUT" | grep -vE "FULL|IDLE" || true)
    if [[ -z "$NOTFULL" ]]; then
      ok "全部 $TOTAL 个 OST 均为 FULL/IDLE (已连接)"
    else
      bad "存在未连接的 OST (非 FULL/IDLE):"
      echo "$NOTFULL" | sed 's/^/       /'
      info "DISCONN 常见根因: 跨 AZ (CREATE_AH err-22) 或服务端 OST failover 恢复中"
    fi
  fi
fi

# 3.4 lfs df
if has lfs && [[ -n "$MOUNT" ]]; then
  echo "       --- lfs df -h $MOUNT ---"
  lfs df -h "$MOUNT" 2>/dev/null | sed 's/^/       /'
  lfs check servers 2>/dev/null | sed 's/^/       /' || true
elif has lfs; then
  MP=$(mount -t lustre 2>/dev/null | awk '{print $3}' | head -1)
  [[ -n "$MP" ]] && { echo "       --- lfs df -h $MP (自动探测挂载点) ---"; lfs df -h "$MP" 2>/dev/null | sed 's/^/       /'; }
fi

# =====================================================================
hdr "第 3.5 层: dmesg 关键错误 (决定性证据)"
# =====================================================================
if has dmesg; then
  DMESG=$(dmesg -T 2>/dev/null || dmesg 2>/dev/null)
  # CREATE_AH err -22 —— 跨 AZ 铁证
  if echo "$DMESG" | grep -qiE "create ah.*comp_status|kefalnd_init_conn_ah|CREATE_AH.*err"; then
    bad "检测到 EFA CREATE_AH 失败 —— 强烈指向【跨 AZ】或 SG 自引用规则缺失!"
    echo "$DMESG" | grep -iE "create ah|kefalnd|comp_status" | tail -6 | sed 's/^/       /'
  else
    ok "未见 CREATE_AH err-22 (EFA 数据面建 AH 无明显失败)"
  fi
  # LNet 错误
  if echo "$DMESG" | grep -qi "LNetError"; then
    warn "存在 LNetError:"
    echo "$DMESG" | grep -i "LNetError" | tail -4 | sed 's/^/       /'
  fi
  # evict / recovery
  if echo "$DMESG" | grep -qiE "evict|was lost|reconnect|recovery|Completing recovery"; then
    warn "存在 evict/recovery 事件 (服务端 OST 可能 failover 过):"
    echo "$DMESG" | grep -iE "evict|was lost|reconnect|Completing recovery|recovery" | tail -6 | sed 's/^/       /'
  else
    ok "未见 evict/recovery 事件"
  fi
  # osc_extent_wait timedout
  if echo "$DMESG" | grep -qi "osc_extent_wait"; then
    warn "存在 osc_extent_wait 超时 (写回等 OST 确认卡住，与 OST 不可用同源):"
    echo "$DMESG" | grep -i "osc_extent_wait" | tail -3 | sed 's/^/       /'
  fi
  # modprobe not found —— 内核漂移
  if echo "$DMESG" | grep -qiE "lnet.*Module not found|lustre.*No such device"; then
    bad "内核模块缺失 (内核漂移) — 需给当前内核重装 lustre-client-modules"
  fi
else
  warn "无法读取 dmesg (需要 root)"
fi

# =====================================================================
hdr "第 4 层: AWS 基础设施 (需 aws cli + --fsid)"
# =====================================================================
if ! has aws; then
  warn "未安装 aws cli，跳过 AWS 侧检查"
elif [[ -z "$FSID" ]]; then
  info "未提供 --fsid，跳过 AWS 侧检查。带上: --fsid fs-xxxx --region $REGION"
else
  echo "       查询 FSx $FSID (region=$REGION) ..."
  FSX_JSON=$(aws fsx describe-file-systems --file-system-ids "$FSID" --region "$REGION" 2>/dev/null)
  if [[ -z "$FSX_JSON" ]]; then
    bad "无法查询 FSx $FSID (权限/region/ID 有误?)"
  else
    FSX_SUBNETS=$(echo "$FSX_JSON" | grep -oE '"SubnetIds":\[[^]]*\]' | grep -oE 'subnet-[a-z0-9]+' | tr '\n' ' ')
    info "FSx subnets: $FSX_SUBNETS"
    # 取 FSx AZ
    FSX_AZ=""
    for sn in $FSX_SUBNETS; do
      az=$(aws ec2 describe-subnets --subnet-ids "$sn" --region "$REGION" \
           --query 'Subnets[0].AvailabilityZone' --output text 2>/dev/null)
      FSX_AZ="$FSX_AZ $az"
    done
    info "FSx AZ:$FSX_AZ    本机 AZ: ${MY_AZ:-未知}"
    # ★ 同 AZ 硬约束检查
    if [[ -n "$MY_AZ" ]]; then
      if echo "$FSX_AZ" | grep -qw "$MY_AZ"; then
        ok "客户端与 FSx 在同一 AZ ($MY_AZ) — 满足 EFA 硬约束"
      else
        bad "★★ 客户端 AZ ($MY_AZ) 与 FSx AZ ($FSX_AZ) 不一致 —— EFA 必跨 AZ 失败! 这是头号根因"
        info "解决: 在 FSx 所在 AZ ($FSX_AZ) 重新启动 EFA 客户端 (同 AZ + 同 /16 CIDR)"
      fi
    fi
    # 吞吐/元数据配置
    echo "$FSX_JSON" | grep -oE '"(PerUnitStorageThroughput|StorageCapacity|DeploymentType|EfaEnabled)":[^,]*' | sed 's/^/       /' || true
  fi
fi

# =====================================================================
hdr "诊断结论"
# =====================================================================
echo "  ${GRN}OK=$PASS${RST}  ${YEL}WARN=$WARN${RST}  ${RED}FAIL=$FAIL${RST}"
echo
echo "  排障心法 (伟伟实测沉淀):"
echo "   1. 一次只改一个变量 (机型/AZ/软件栈)"
echo "   2. OST 通不通看 'lctl get_param osc.*.ost_server_uuid' (FULL/IDLE=通), 别看 lnetctl peer state:NA"
echo "   3. CREATE_AH err-22 → 99% 跨 AZ; EFA 客户端必须与 FSx 同 AZ + 同 /16"
echo "   4. modprobe Module not found → 内核漂移, install-fsx-lustre-client.sh --install-lustre"
echo "   5. fw_ver 0.0.0.0 / cap_flags 0x0 是 EFA 正常值, 不是 bug"
echo
if [[ $FAIL -gt 0 ]]; then
  echo "  ${RED}存在 FAIL 项，优先处理上面标 ★ 的条目。${RST}"
  exit 1
elif [[ $WARN -gt 0 ]]; then
  echo "  ${YEL}无致命错误，但有 WARN 项建议核实。${RST}"
  exit 0
else
  echo "  ${GRN}各层检查通过。若仍有 I/O 卡顿，查服务端 OST failover / CloudWatch。${RST}"
  exit 0
fi
