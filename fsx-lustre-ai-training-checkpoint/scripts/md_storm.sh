#!/bin/bash
# usage: md_storm.sh <VENV> <DATADIR> <NPROC> <OUT>  ; start NPROC processes at the same wall-clock second (GO time passed via env GO)
VENV=$1; DATA=$2; N=$3; OUT=$4
mkdir -p $(dirname $OUT)
while [ $(date +%s) -lt $GO ]; do sleep 0.05; done
for i in $(seq 1 $N); do $VENV/bin/python /fsx/bench/md_worker.py $DATA >> $OUT.$(hostname -s) 2>>$OUT.$(hostname -s).err & done
wait
