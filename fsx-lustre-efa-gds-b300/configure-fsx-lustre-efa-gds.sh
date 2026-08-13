#!/usr/bin/env bash
###############################################################################
# configure-fsx-lustre-efa-gds.sh
#
# 用途：在 EC2 上按 AWS 官方 User Guide《Configuring EFA clients》逐步配置
#       FSx for Lustre 的 EFA 访问，并可选启用 NVIDIA GPUDirect Storage(GDS)。
#       本脚本是「操作指导 + 可重复执行」二合一：每一步都对应官方文档的一个
#       Step，并附中文注释说明"这一步在干什么、为什么"。
#
# 官方依据（务必对照）：
#   https://docs.aws.amazon.com/fsx/latest/LustreGuide/configure-efa-clients.html
#   Step 1 安全组 / Step 2 装驱动 / Step 3 配 EFA / Step 4 EFA 接口
#
# 【前置硬要求·实测2026-08-13血泪】EFA 网卡必须在实例上真实存在，脚本才配得到：
#   ★ p6-b300.48xlarge 支持 17 张网卡 / 16 个 EFA 接口，但 run-instances 若只用默认
#     单网卡(--associate-public-ip-address)，实例内只会看到 card0 的 2 个 IB 设备，
#     setup.sh 只能找到很少的 EFA。要拿到全部 EFA，必须在 launch 时用
#     --network-interfaces 指定多张 EFA 网卡(InterfaceType=efa, 每张一个 NetworkCardIndex)，
#     或【实例 stopped 状态下】aws ec2 attach-network-interface --interface-type efa
#     --network-card-index N（EFA 网卡只能在 stopped 时挂）。
#   ★ 本次实测：card0 留作管理(普通 interface 走 SSH/TCP)，另挂 15 张 EFA 到 card1~15，
#     setup.sh 成功配了 15 个 @efa NI（card0 的 EFA 未纳入池，走 TCP）。
#   ★ Capacity Block 实例 run-instances 必须加 --instance-market-options 'MarketType=capacity-block'，
#     否则报 "The market type (purchasing) option is not valid"。
#
# 相对官方流程的改动（仅一处，且可选）：
#   ★ p6-b300.48xlarge 目前不在 AWS configure 脚本的 GDS 白名单里
#     (GDS_SUPPORTED_INSTANNCES)。仅当 --gds 且机型为 b300 时，本脚本用 sed
#     幂等地把它加进白名单。除此之外完全调用 AWS 原生 setup.sh，不改其逻辑。
#     普通 EFA（不加 --gds）对 b300 是官方原生支持的，零改动。
#
# 支持的客户端 OS（官方）：AL2023 / RHEL9.5+ / Ubuntu22.04+ (kernel 6.8+)
# EFA 支持机型：支持 EFA 的 Nitro v4+ 实例（trn2 除外）
#
# 用法：
#   # 普通 EFA（无 GDS）
#   sudo FSX_DNS=fs-xxxx.fsx.us-west-2.amazonaws.com FSX_MOUNTNAME=abcd1234 \
#        bash configure-fsx-lustre-efa-gds.sh
#
#   # 启用 GDS（GPU 实例，如 p5/p5e/p5en/p6-b200/p6-b300）
#   sudo FSX_DNS=... FSX_MOUNTNAME=... bash configure-fsx-lustre-efa-gds.sh --gds
#
#   环境变量：
#     FSX_DNS       (必填) 文件系统 DNS 名，如 fs-xxx.fsx.<region>.amazonaws.com
#     FSX_MOUNTNAME (必填) Lustre mount name（控制台/CLI describe 可查）
#     MNT           (可选) 挂载点，默认 /fsx
#   开关：
#     --gds         启用 GPUDirect Storage（装 nvidia-fs + setup.sh --optimized-for-gds）
#     --skip-driver 跳过 Step 2 装驱动（DLAMI 已预装 Lustre/EFA/GDS 驱动时用）
###############################################################################
set -euo pipefail

GDS=0
SKIP_DRIVER=0
for a in "$@"; do
  case "$a" in
    --gds) GDS=1 ;;
    --skip-driver) SKIP_DRIVER=1 ;;
    *) echo "未知参数: $a"; exit 1 ;;
  esac
done

: "${FSX_DNS:?必填：FSX_DNS，如 fs-xxxx.fsx.us-west-2.amazonaws.com}"
: "${FSX_MOUNTNAME:?必填：FSX_MOUNTNAME（Lustre mount name）}"
MNT="${MNT:-/fsx}"

log(){ echo -e "\n\033[1;36m########## $* ##########\033[0m"; }
die(){ echo -e "\033[1;31mFATAL: $*\033[0m" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "请用 root/sudo 运行"

# 探测机型（决定要不要改白名单、EFA 接口数）
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds:21600")
ITYPE=$(curl -s -H "X-aws-ec2-metadata-token:$TOKEN" http://169.254.169.254/latest/meta-data/instance-type)
echo "检测到实例类型: $ITYPE ; GDS=$GDS ; 挂载点=$MNT"

###############################################################################
log "Step 1: 确认 EFA 安全组（提示，本步骤在 AWS 控制台/CLI 做，脚本只检查连通性）"
###############################################################################
# 官方要求：文件系统和客户端所在的安全组必须【互相放行全部 EFA 流量】——
# 即安全组需有一条“自引用”规则(允许来自本安全组自身的所有协议/端口)。
# 这一步无法在实例内部完成，需在建 SG 时配好。此处仅打印当前实例的 EFA 网卡，
# 若后续 lnetctl 配不上，多半是安全组自引用没开或客户端与 FSx 不在同一 AZ。
echo "提示：请确认客户端 SG 与 FSx SG 均有【自引用全放行】规则，且客户端与 FSx 同 AZ。"

###############################################################################
if [ "$SKIP_DRIVER" = 0 ]; then
log "Step 2: 安装 Lustre 客户端 + EFA 驱动（DLAMI 已预装可加 --skip-driver 跳过）"
###############################################################################
# 官方“快速安装”：下载 install-fsx-lustre-client.zip，跑 install 脚本，
# 它会自动装 Lustre client + EFA driver 并验证。
  cd /tmp
  curl -sO https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/install-fsx-lustre-client.zip
  rm -rf install-fsx-lustre-client && unzip -oq install-fsx-lustre-client.zip
  cd install-fsx-lustre-client
  sudo ./bin/install-fsx-lustre-client.sh --install-lustre --install-efa
else
  log "Step 2: 跳过装驱动（--skip-driver）——假定 DLAMI 已预装 Lustre/EFA/GDS 驱动"
fi

###############################################################################
if [ "$GDS" = 1 ]; then
log "Step 2b(可选): 安装 NVIDIA GPUDirect Storage(GDS) 驱动 nvidia-fs"
###############################################################################
# 官方要求（GDS 节）：仅当要用 GDS 时做。要求 NVIDIA GDS driver >= 2.24.2。
# DLAMI 通常已预装；若 lsmod 无 nvidia_fs 则按官方命令从源码编。
  if lsmod | grep -q nvidia_fs; then
    modinfo nvidia_fs | awk '/^version:/{print "已加载 nvidia_fs version="$2}'
  else
    echo "未加载 nvidia_fs，按官方步骤从源码编译..."
    cd /tmp; rm -rf gds-nvidia-fs
    git clone https://github.com/NVIDIA/gds-nvidia-fs.git
    cd gds-nvidia-fs/src/
    export NVFS_MAX_PEER_DEVS=128
    export NVFS_MAX_PCI_DEPTH=16
    sudo -E make
    sudo insmod nvidia-fs.ko
    lsmod | grep nvidia_fs || die "nvidia_fs 未加载"
  fi
fi

###############################################################################
log "Step 3: 下载 AWS 配置脚本 configure-efa-fsx-lustre-client"
###############################################################################
# 官方“快速配置”：下载 configure-efa-fsx-lustre-client.zip，跑 setup.sh。
# 它会：导入 Lustre 模块 → 配 TCP+EFA 接口 → 建 systemd 服务(重启自动重配)。
cd /tmp
curl -sO https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/configure-efa-fsx-lustre-client.zip
rm -rf configure-efa-fsx-lustre-client && unzip -oq configure-efa-fsx-lustre-client.zip
cd configure-efa-fsx-lustre-client
PY=bin/configure-efa-fsx-lustre-client.py

###############################################################################
if [ "$GDS" = 1 ] && [ "$ITYPE" = "p6-b300.48xlarge" ]; then
log "Step 3b(唯一改动): 把 p6-b300.48xlarge 加进 GDS 白名单（幂等）"
###############################################################################
# 【为什么】AWS 脚本里 GDS_SUPPORTED_INSTANNCES(注意 AWS 把 INSTANCES 拼成
#   INSTANNCES) 目前只含 p5/p5e/p5en/p6-b200，不含 b300。走 --optimized-for-gds
#   时 filter_efa_gds() 会对不在名单的机型直接 raise 拒绝。故此处把 b300 补进去。
# 【实测修正 2026-08-13】原来用 `grep -q '"p6-b300.48xlarge"' "$PY"` 判幂等是错的：
#   b300 这个字符串在 .py 别处也出现(如注释/其它配置段)，导致 grep 误判"已加"而跳过
#   sed，白名单里其实没加 → setup.sh 仍报 "does not support Lustre GDS"。
#   【修复】幂等判断必须精确匹配"白名单数组行"，即行首 4 空格 + "p6-b300..." + 逗号。
#   sed 也用锚定行首/行尾($)的精确模式，只改数组里那一行。
  if grep -qE '^    "p6-b300\.48xlarge",$' "$PY"; then
    echo "白名单已含 p6-b300.48xlarge（精确匹配数组行），跳过"
  else
    sed -i 's/^    "p6-b200.48xlarge",$/    "p6-b200.48xlarge",\n    "p6-b300.48xlarge",/' "$PY"
    grep -qE '^    "p6-b300\.48xlarge",$' "$PY" || die "白名单注入失败"
    echo "已把 p6-b300.48xlarge 加进 GDS_SUPPORTED_INSTANNCES:"
    sed -n '/GDS_SUPPORTED_INSTANNCES/,/\]/p' "$PY"
  fi
fi

###############################################################################
log "Step 3c: 运行 setup.sh 配置 EFA（GDS 加 --optimized-for-gds）"
###############################################################################
# 官方命令：普通 IO → sudo ./setup.sh ；GDS IO → sudo ./setup.sh --optimized-for-gds
# setup.sh 默认还会建 systemd 服务，重启后自动重新配置 EFA。
if [ "$GDS" = 1 ]; then
  sudo ./setup.sh --optimized-for-gds
else
  sudo ./setup.sh
fi

# 验证 systemd 服务与已配的 EFA 接口
echo "--- systemd 服务状态 ---"
systemctl status configure-efa-fsx-lustre-client.service --no-pager -l | head -12 || true

###############################################################################
log "Step 4: 查看已配置的 EFA 接口"
###############################################################################
# 官方：setup 脚本按机型自动配 EFA 接口数（b300=16 / p6-b200/p5系列=8 / 双网卡=2 / 单网卡=1）。
# 每个 EFA 接口占用 FSx 的 1 个 EFA 连接（单文件系统上限 1024 连接）。
echo "--- 可用 EFA 网卡 ---"
for interface in /sys/class/infiniband/*; do
    [ -e "$interface/device/driver" ] || continue
    [ "$(basename "$(readlink -f "$interface/device/driver")")" = "efa" ] || continue
    echo "  $(basename "$interface")"
done
echo "--- 当前 Lustre 已配的网络接口（含 @efa 数量）---"
sudo lnetctl net show || true
echo "已配 EFA NI 数 = $(sudo lnetctl net show 2>/dev/null | grep -c '@efa')"

###############################################################################
log "Step 5(附): 挂载 FSx for Lustre"
###############################################################################
# 官方挂载语法（EFA 与普通挂载一致，前置 EFA 服务已把 LNet 配到 efa）：
mkdir -p "$MNT"
if mountpoint -q "$MNT"; then
  echo "$MNT 已挂载"
else
  sudo mount -t lustre -o relatime,flock "${FSX_DNS}@tcp:/${FSX_MOUNTNAME}" "$MNT"
fi
echo "--- OST 状态（FULL/IDLE=连通；DISCONN=断，多半跨AZ或SG自引用没开）---"
lctl get_param -n osc.*.ost_server_uuid || true
lfs df -h "$MNT" || true

###############################################################################
log "Step 6: 跑 FIO + 验证 EFA 真有收发包（lnetctl net show -v 4 的 send/recv_count 前后对比）"
###############################################################################
# 【核心验证方法】用 LNet 自己的统计，最直接证明"Lustre 数据面在 EFA NI 上收发"：
#   lnetctl net show --net efa -v 4  →  每个 efa NI 的 statistics:{send_count,recv_count,drop_count}
#   (-v 4 是 Lustre/Whamcloud 官方 troubleshooting 的最详细级别)
# 在跑 FIO【前】【后】各采一次，对比 send_count/recv_count 增量。大量读写后若这两个
# 计数器显著增长 → 铁证数据走 EFA。/sys hw_counters(rx_pkts/tx_pkts) 作硬件层辅证。
command -v fio >/dev/null 2>&1 || { echo "装 fio..."; (apt-get install -y fio || yum install -y fio) >/dev/null 2>&1 || true; }

# 采集函数：LNet efa NI 的 send/recv/drop_count（主）+ /sys hw_counters（辅）
snap_efa_counters(){
  local tag="$1"; echo "=== EFA 收发计数快照 [$tag] ==="
  echo "  [LNet] lnetctl net show --net efa -v 4 的 statistics:"
  sudo lnetctl net show --net efa -v 4 2>/dev/null \
    | grep -E "nid:|send_count:|recv_count:|drop_count:" | sed 's/^/    /' || echo "    (无 efa NI?)"
  echo "  [硬件] /sys hw_counters:"
  for dev in /sys/class/infiniband/*; do
    [ -e "$dev/device/driver" ] || continue
    [ "$(basename "$(readlink -f "$dev/device/driver")")" = "efa" ] || continue
    local n; n=$(basename "$dev")
    echo "    $n: rx_pkts=$(cat "$dev/ports/1/hw_counters/rx_pkts" 2>/dev/null||echo NA)" \
         "tx_pkts=$(cat "$dev/ports/1/hw_counters/tx_pkts" 2>/dev/null||echo NA)" \
         "rdma_read_bytes=$(cat "$dev/ports/1/hw_counters/rdma_read_bytes" 2>/dev/null||echo NA)" \
         "rdma_write_bytes=$(cat "$dev/ports/1/hw_counters/rdma_write_bytes" 2>/dev/null||echo NA)"
  done
}

snap_efa_counters "FIO 前"
echo "--- 跑 FIO（direct, libaio, 顺写/顺读/随机读，落在 $MNT）---"
sudo mkdir -p "$MNT/fiotest"
sudo fio --name=seqwrite --directory="$MNT/fiotest" --rw=write --bs=1M --size=8G \
  --numjobs=8 --ioengine=libaio --direct=1 --iodepth=32 --group_reporting || echo "WARN: seqwrite 失败"
sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
sudo fio --name=seqread --directory="$MNT/fiotest" --rw=read --bs=1M --size=8G \
  --numjobs=8 --ioengine=libaio --direct=1 --iodepth=32 --group_reporting || echo "WARN: seqread 失败"
sudo fio --name=randread --directory="$MNT/fiotest" --rw=randread --bs=64k --size=4G \
  --numjobs=4 --ioengine=libaio --direct=1 --iodepth=16 --group_reporting || echo "WARN: randread 失败"
snap_efa_counters "FIO 后"
echo ">>> 对比上面两次快照：LNet 的 send_count/recv_count 明显增长 = Lustre 数据确实走 EFA ✅"
echo ">>> （若各 efa NI 的 send/recv_count 都在涨，说明 16 个 EFA 都在分担流量）"

###############################################################################
if [ "$GDS" = 1 ]; then
log "Step 7(GDS): gdscheck 自检 + gdsio 验证 IO 正常运行"
###############################################################################
  GDSCHECK=$(command -v gdscheck || echo /usr/local/cuda/gds/tools/gdscheck)
  echo "--- gdscheck -p（必须出现 'Platform verification succeeded' + GPU supports GDS）---"
  sudo "$GDSCHECK" -p 2>&1 | tee /tmp/gdscheck.out || echo "WARN: gdscheck 未通过"
  grep -q "Platform verification succeeded" /tmp/gdscheck.out \
    && echo "✅ GDS 平台验证通过" || echo "⚠️ GDS 平台验证未通过，见上方输出"

  GDSIO=$(command -v gdsio || echo /usr/local/cuda/gds/tools/gdsio)
  sudo mkdir -p "$MNT/gdstest"
  echo "--- gdsio：-x0=GPUDirect(存储直达显存) vs -x1=CPUONLY，先写-I1后读-I0 ---"
  echo "    XferType=GPUD 且吞吐正常 = GDS IO 正常运行 ✅"
  for x in 0 1; do
    LBL=$([ "$x" = 0 ] && echo "GPUDirect" || echo "CPUONLY")
    echo "### -x $x ($LBL) 写 ###"
    sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
    sudo "$GDSIO" -D "$MNT/gdstest" -d 0 -w 8 -s 4G -i 1M -x "$x" -I 1 || echo "WARN: 写测失败 x=$x"
    echo "### -x $x ($LBL) 读 ###"
    sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
    sudo "$GDSIO" -D "$MNT/gdstest" -d 0 -w 8 -s 4G -i 1M -x "$x" -I 0 || echo "WARN: 读测失败 x=$x"
  done
fi

log "完成。要开机自动挂载，可按官方在 /etc/fstab 加（依赖 EFA 服务先起）："
cat <<FSTAB
${FSX_DNS}@tcp:/${FSX_MOUNTNAME} ${MNT} lustre defaults,relatime,flock,_netdev,x-systemd.automount,x-systemd.requires=configure-efa-fsx-lustre-client.service,x-systemd.after=configure-efa-fsx-lustre-client.service 0 0
FSTAB
