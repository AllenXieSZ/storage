#!/bin/bash
# usage: bigdir.sh create|ls|open <MODE big|split> <node_idx> <nnodes>
# big: one dir /fsx/bigdir/one with 200K files (each node creates 200K/nnodes); split: /fsx/bigdir/split/dNN 20 dirs x 10K
ACT=$1; M=$2; I=$3; N=$4; TOT=200000
if [ $ACT = create ]; then
  per=$((TOT/N)); s=$((I*per))
  if [ $M = big ]; then D=/fsx/bigdir/one; mkdir -p $D; T0=$(date +%s.%N); python3 -c "
import os;[open(f'$D/f{i:07d}','w').close() for i in range($s,$s+$per)]"; else T0=$(date +%s.%N); python3 -c "
import os
for i in range($s,$s+$per):
  d=f'/fsx/bigdir/split/d{i//10000:02d}'; os.makedirs(d,exist_ok=True); open(f'{d}/f{i:07d}','w').close()"; fi
  echo CREATE $M $(echo "$(date +%s.%N)-$T0" | bc)
elif [ $ACT = ls ]; then
  sync; echo 3 > /proc/sys/vm/drop_caches; lctl set_param -n ldlm.namespaces.*.lru_size=clear >/dev/null
  T0=$(date +%s.%N); if [ $M = big ]; then ls -l /fsx/bigdir/one | wc -l; else ls -l /fsx/bigdir/split/d$(printf %02d $I) | wc -l; fi; echo LS $M $(echo "$(date +%s.%N)-$T0" | bc)
fi
