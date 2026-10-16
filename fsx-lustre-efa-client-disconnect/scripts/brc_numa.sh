#!/bin/bash
# usage: brc_numa.sh <tag> <nj_per_node> <rate_per_job|none> <RT> ; two fio jobs pinned to NUMA0/NUMA1 (cpu+mem bind), 16M direct, stripe -1
T=$1; NJ=$2; RATE=$3; RT=${4:-60}; H=$(hostname -s); D=/fsx/brc/$H/$T; O=/root/res/$T
rm -rf $O $D; mkdir -p $O $D/n0 $D/n1; lfs setstripe -c -1 $D/n0; lfs setstripe -c -1 $D/n1
R=""; [ "$RATE" != none ] && R="rate=$RATE"
cat > $O/job.fio <<EOJ
[global]
rw=write
bs=16M
size=8G
ioengine=libaio
iodepth=8
direct=1
time_based
runtime=$RT
group_reporting=0
$R
[n0]
directory=$D/n0
numjobs=$NJ
numa_cpu_nodes=0
numa_mem_policy=bind:0
[n1]
directory=$D/n1
numjobs=$NJ
numa_cpu_nodes=1
numa_mem_policy=bind:1
EOJ
dmesg -C
c(){ for e in efa_0 efa_1; do echo -n "$e tx_GB=$(($(cat /sys/class/infiniband/$e/ports/1/hw_counters/tx_bytes)/1000000000)) retrans=$(cat /sys/class/infiniband/$e/ports/1/hw_counters/retrans_pkts) "; done; }
c > $O/efa_before.txt
timeout $((RT+60)) fio --output-format=json --output=$O/fio.json $O/job.fio & FP=$!
T0=$(date +%s); STALL=0; P=0; BROKE=0
while kill -0 $FP 2>/dev/null; do sleep 2; N=$(($(date +%s)-T0)); X=$(c); S=$(cat /sys/class/infiniband/efa_*/ports/1/hw_counters/tx_bytes | awk '{s+=$1}END{print s}')
  ST=$(lctl get_param -n osc.*.import | awk '/state:/{print $2}' | sort | uniq -c | tr '\n' ' ')
  echo "t=$N [$ST] $X" >> $O/timeline.txt
  [ "$S" = "$P" ] && STALL=$((STALL+2)) || STALL=0; P=$S
  if [ $STALL -ge 20 ]; then echo "STALL t=$N" >> $O/timeline.txt; BROKE=1; pkill -9 fio; break; fi
done
sleep 3; c > $O/efa_after.txt; dmesg -T > $O/dmesg.txt; lctl get_param osc.*.import > $O/import.txt; lnetctl net show -v 4 > $O/net_show.txt; lnetctl peer show -v > $O/peer_show.txt; lnetctl stats show > $O/lnet_stats.txt
BW=$(python3 -c "
import json;j=json.load(open('$O/fio.json'))['jobs']
d={}
for x in j: d[x['jobname']]=d.get(x['jobname'],0)+x['write']['bw_bytes']
print(' '.join('%s=%.2f'%(k,v/1e9) for k,v in d.items()),'total=%.2f GB/s'%(sum(d.values())/1e9))" 2>/dev/null || echo FIO_FAILED)
echo "RESULT $T broke=$BROKE nj/node=$NJ rate=$RATE $BW dmesg_err=$(grep -cE 'lost|timed out|cancel' $O/dmesg.txt) before[$(cat $O/efa_before.txt)] after[$(cat $O/efa_after.txt)]"
