#!/bin/bash
# usage: run_dist.sh <NNODES> <NPROC_PER_NODE> <LOGNAME> <script args...>
# runs torchrun on this node; node rank = line index of this host IP in /fsx/bench/hosts.txt (first NNODES lines)
NN=$1; NP=$2; LOG=$3; shift 3
MYIP=$(hostname -I | awk '{print $1}')
NR=$(grep -n -x "$MYIP" /fsx/bench/hosts.txt | cut -d: -f1); NR=$((NR-1))
if [ $NR -ge $NN ] || [ $NR -lt 0 ]; then echo "not in job"; exit 0; fi
MASTER=$(head -1 /fsx/bench/hosts.txt)
mkdir -p /fsx/bench/logs
export OMP_NUM_THREADS=1 GLOO_SOCKET_IFNAME=$(ip -br -4 a | awk '$3 ~ /^<VPC_CIDR_PREFIX>/ {print $1; exit}')
setsid nohup /opt/venv/bin/torchrun --nnodes=$NN --nproc-per-node=$NP --node-rank=$NR --master-addr=$MASTER --master-port=29511 \
  /fsx/bench/ckpt_bench.py "$@" > /fsx/bench/logs/$LOG.n$NR.log 2>&1 < /dev/null &
echo "launched node $NR"
