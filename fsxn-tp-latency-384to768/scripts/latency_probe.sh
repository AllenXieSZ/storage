#!/bin/bash
# FSxN 384->768 throughput upgrade latency probe (fio 2.14, usec clat)
# Usage: latency_probe.sh <phase> <t0_epoch> <count>
set -u
MNT=/mnt/fsx384
CSV=/root/tp384_results.csv
RFILE=$MNT/fio_readfile
WFILE=$MNT/fio_writefile
PARSER=/root/fio_parse.py
PHASE="$1"; T0="$2"; COUNT="$3"

if [ ! -f "$CSV" ]; then
  echo "elapsed_sec,op,lat_mean_us,lat_p99_us,timestamp,phase" > "$CSV"
fi

run_fio() {
  local op="$1" fn="$2"
  fio --name=probe --rw=$op --bs=16k --ioengine=sync \
      --direct=1 --numjobs=1 --iodepth=1 --runtime=8 --time_based \
      --size=1G --filename=$fn --output-format=json 2>/dev/null
}

for i in $(seq 1 $COUNT); do
  NOW=$(date +%s); ELAPSED=$((NOW - T0)); TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  run_fio randread $RFILE > /tmp/_r.json
  RSTATS=$(python3 $PARSER /tmp/_r.json read)
  RMEAN=${RSTATS%% *}; RP99=${RSTATS##* }
  echo "$ELAPSED,read,$RMEAN,$RP99,$TS,$PHASE" >> "$CSV"
  WNOW=$(date +%s); WELAPSED=$((WNOW - T0)); WTS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  run_fio randwrite $WFILE > /tmp/_w.json
  WSTATS=$(python3 $PARSER /tmp/_w.json write)
  WMEAN=${WSTATS%% *}; WP99=${WSTATS##* }
  echo "$WELAPSED,write,$WMEAN,$WP99,$WTS,$PHASE" >> "$CSV"
  echo "round $i/$COUNT elapsed=${ELAPSED}s read_mean=${RMEAN} read_p99=${RP99} write_mean=${WMEAN} write_p99=${WP99} (us)"
  sleep 1
done
