#!/bin/bash
# usage: brc_run.sh <tag> <rw> <numjobs> <iodepth> <stripe_count> <stripe_idx> <GiB_per_job> <runtime_s>
# writes to /fsx/brc/<host>/<tag>; samples every 5s; outputs /root/res/<tag>.txt ; prints summary
T=$1; RW=$2; NJ=$3; QD=$4; SC=$5; SI=$6; G=$7; RT=${8:-180}; RATE=${9:-}; [ -n "$RATE" ] && RATEOPT="--rate=$RATE" || RATEOPT=""
H=$(hostname -s); D=/fsx/brc/$H/$T; O=/root/res/$T; mkdir -p /root/res $O
rm -rf $D; mkdir -p $D
if [ "$SC" = multi ]; then FD=""; for k in ${SI//,/ }; do mkdir -p $D/o$k; lfs setstripe -c 1 -i $k $D/o$k; FD="$FD:$D/o$k"; done; FD=${FD#:}; else lfs setstripe -c $SC -i $SI $D; FD=$D; fi
cnt(){ for d in /sys/class/infiniband/efa_*; do n=$(basename $d); c=$d/ports/1/hw_counters; echo "$n retrans=$(cat $c/retrans_pkts) rto=$(cat $c/retrans_timeout_events) tx_GB=$(($(cat $c/tx_bytes)/1000000000)) rx_GB=$(($(cat $c/rx_bytes)/1000000000)) rdrd_resp_GB=$(($(cat $c/rdma_read_resp_bytes)/1000000000)) rdrd_GB=$(($(cat $c/rdma_read_bytes)/1000000000)) rdwr_GB=$(($(cat $c/rdma_write_bytes)/1000000000)) rdwr_recv_GB=$(($(cat $c/rdma_write_recv_bytes)/1000000000)) unresp=$(cat $c/unresponsive_remote_events) impaired=$(cat $c/impaired_remote_conn_events) rx_drops=$(cat $c/rx_drops)"; done; }
iob(){ lctl get_param -n osc.*.stats 2>/dev/null | awk '/^(ost_read|ost_write|read_bytes|write_bytes)/{s+=$7} END{print s+0}'; }
rm -rf $O; mkdir -p $O; dmesg -C; lctl clear
lnetctl net show | grep -q "@efa" || { echo "RESULT $T INVALID no_efa_ni"; exit 3; }
cnt > $O/efa_before.txt
lctl set_param osc.*.rpc_stats=0 >/dev/null 2>&1
CMD="fio --name=$T --directory=$FD --rw=$RW --bs=16M --size=${G}G --numjobs=$NJ --ioengine=libaio --iodepth=$QD --direct=1 --time_based --runtime=$RT --group_reporting --output-format=json --output=$O/fio.json $RATEOPT"
echo "$CMD" > $O/cmd.txt
if [ "$RW" = read ]; then sync; echo 3 > /proc/sys/vm/drop_caches; fi
T0=$(date +%s)
timeout $((RT+120)) $CMD & FP=$!
BROKE=0; FIRST=""; STALL=0; PTX=0
while kill -0 $FP 2>/dev/null && [ $BROKE = 0 ]; do
  if [ $(($(date +%s)-T0)) -lt 20 ]; then sleep 1; else sleep 5; fi; NOW=$(($(date +%s)-T0))
  ST=$(lctl get_param -n osc.*.import 2>/dev/null | awk '/state:/{print $2}' | sort | uniq -c | tr '\n' ' ')
  E=$(cnt | awk '{printf "%s %s %s %s %s %s %s %s %s; ",$1,$2,$3,$4,$5,$6,$7,$8,$9}'); E="io_GB=$(( $(iob)/1000000000 )) $E"
  L=$(dmesg | grep -cE 'lost|timed out|network error|force_cancel')
  echo "t=$NOW states=[$ST] dmesg_err=$L efa: $E" >> $O/timeline.txt
  TXS=$(cat /sys/class/infiniband/efa_*/ports/1/hw_counters/tx_bytes /sys/class/infiniband/efa_*/ports/1/hw_counters/rx_bytes | awk "{s+=\$1} END{print s}")
  BAD=$(echo "$ST" | grep -oE '[0-9]+ [A-Z_]+' | grep -vE ' (FULL|IDLE)$' | wc -l)
  if [ "$L" -gt 0 ] || [ "$BAD" -gt 0 ] ; then if [ -z "$FIRST" ]; then FIRST=$NOW; fi; fi
  if [ "$TXS" = "$PTX" ]; then STALL=$((STALL+ ($NOW<20?1:5) )); else STALL=0; fi; PTX=$TXS
  if [ -n "$FIRST" ] && [ "${ABORT:-1}" = 1 ] && [ $((NOW-FIRST)) -ge 20 ]; then echo "ABORT t=$NOW (err since $FIRST)" >> $O/timeline.txt; pkill -9 fio; BROKE=1; fi
  if [ "$RW" = write ] && [ $STALL -ge 25 ] && [ "${ABORT:-1}" = 1 ]; then echo "ABORT stall t=$NOW" >> $O/timeline.txt; [ -z "$FIRST" ] && FIRST=stall$NOW; pkill -9 fio; BROKE=1; fi
done
if [ $BROKE = 1 ]; then for k in $(seq 1 15); do kill -0 $FP 2>/dev/null || break; sleep 2; done; RC=137; else wait $FP; RC=$?; fi
cnt > $O/efa_after.txt
dmesg -T > $O/dmesg.txt
lctl get_param osc.*.import > $O/import.txt 2>&1
lctl get_param osc.*.rpc_stats > $O/rpc_stats.txt 2>&1
lnetctl stats show > $O/lnet_stats.txt 2>&1
lnetctl net show -v 4 > $O/net_show.txt 2>&1
lnetctl peer show -v > $O/peer_show.txt 2>&1
lctl get_param osc.*.stats > $O/osc_stats.txt 2>&1
(for f in $(find $D -type f | head -40); do echo "$f $(lfs getstripe -i $f)"; done) > $O/getstripe.txt 2>&1
BW=$(python3 -c "import json;j=json.load(open('$O/fio.json'))['jobs'][0]['$RW'];print('%.2f GB/s'%(j['bw_bytes']/1e9))" 2>/dev/null || echo FIO_FAILED)
NERR=$(grep -cE 'lost|timed out|network error|force_cancel' $O/dmesg.txt)
ST=$(awk '/state:/{print $2}' $O/import.txt | sort | uniq -c | tr '\n' ' ')
RETR=$(awk '{print $1,$2,$3}' $O/efa_after.txt | tr '\n' ' ')
SAMP=$(awk -v n=$NJ '/^t=/{print}' $O/timeline.txt | head -0); echo "RESULT $T rate=${RATE:-none} broke=$BROKE host=$H rw=$RW nj=$NJ qd=$QD sc=$SC si=$SI rc=$RC bw=$BW dmesg_err=$NERR first_err_t=${FIRST:-none} states=[$ST] efa_after: $RETR"
