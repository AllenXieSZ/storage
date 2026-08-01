#!/bin/bash
# throughput_change_watch.sh —— 监控 FSx Lustre 变配(125->250)过程的 IO 波动与报错
# 每 20s 采一次：变配进度(需AWS侧)由本地脚本无法查，这里专注客户端侧 IO/连接/报错
LOGDIR=/var/log/lustre_stress
OUT=$LOGDIR/throughput_change_watch.log
MNT=/fsx
ts(){ date -u +%Y-%m-%dT%H:%M:%SZ; }
echo "[$(ts)] ===== 变配监控启动 (125->250) =====" >>"$OUT"

# 记录 dmesg 基线行数
DBASE=$(dmesg 2>/dev/null | wc -l)

for i in $(seq 1 360); do   # 最多跑 2 小时 (360*20s)
  T=$(ts)
  # OST/MDT 连接状态
  OST=$(lctl get_param -n osc.*.ost_server_uuid 2>/dev/null | tr "\n" " ")
  # fio 是否在跑
  FIO=$(pgrep -c fio 2>/dev/null)
  # 简单探测：对挂载点做一次 stat + 小写测试是否报错
  IOERR=""
  if ! timeout 10 stat "$MNT" >/dev/null 2>&1; then IOERR="STAT_FAIL "; fi
  if ! timeout 10 bash -c "echo probe > $MNT/.iowatch_$$ && rm -f $MNT/.iowatch_$$" 2>/dev/null; then IOERR="${IOERR}RW_FAIL "; fi
  # dmesg 新增错误
  DERR=$(dmesg 2>/dev/null | tail -n +$((DBASE+1)) | grep -iE "LustreError|evict|Timed out|connection.*(lost|restored)|reconnect|-EIO|bulk.*timeout" | tail -5)

  echo "[$T] fio_procs=$FIO ost=[$OST] io_err=[${IOERR:-none}]" >>"$OUT"
  if [ -n "$DERR" ]; then
    echo "[$T] !!DMESG!! $DERR" >>"$OUT"
  fi
  if echo "$OST" | grep -qiE "DISCONN|CONNECTING|NEW"; then
    echo "[$T] !!OST状态异常!! $OST" >>"$OUT"
  fi
  sleep 20
done
echo "[$(ts)] ===== 变配监控结束 =====" >>"$OUT"
