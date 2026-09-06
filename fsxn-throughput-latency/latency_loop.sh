#!/bin/bash
# Runs on jumpbox. Every 10s runs one read fio + one write fio (bs=16k, sync, direct=1,
# numjobs=1, iodepth=1, runtime=8 time_based) and appends clat mean + p99 to CSV.
# Loop stops when /root/tp_stop exists.
set -u
MNT=/mnt/fsxtp
CSV=/root/tp_results.csv
T0=$(date +%s)
echo "T0_epoch=$T0" > /root/tp_t0.txt
# CSV already has header + baseline rows written by baseline.sh; append here.

run_fio() {
  local op=$1 fname=$2
  # randread/randwrite, bs=16k, sync, direct=1, numjobs=1, iodepth=1, 8s time_based
  fio --name=lat --filename="$fname" --size=1G \
      --rw="$op" --bs=16k --ioengine=sync --direct=1 --numjobs=1 --iodepth=1 \
      --runtime=8 --time_based --group_reporting --output-format=json 2>/dev/null
}

parse() {
  # $1 json, $2 = read|write : print "mean_us,p99_us"
  # fio-2.14 uses "clat" already in microseconds (not clat_ns)
  python3 - "$1" "$2" <<'PY'
import json,sys
j=json.load(open(sys.argv[1])); side=sys.argv[2]
job=j["jobs"][0][side]
if "clat_ns" in job:      # newer fio (ns)
    c=job["clat_ns"]; div=1000.0
elif "clat" in job:       # fio 2.x (us)
    c=job["clat"]; div=1.0
else:
    c={}; div=1.0
mean=c.get("mean",0)/div
p99=c.get("percentile",{}).get("99.000000",0)/div
print(f"{mean:.1f},{p99:.1f}")
PY
}

while [ ! -f /root/tp_stop ]; do
  loop_start=$(date +%s)
  el=$((loop_start - T0))
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  # read (target file on NFS mount; pre-created by prep)
  run_fio randread "$MNT/lat_rd.dat" 2>/dev/null > /root/fio_rd.json
  # write (target file on NFS mount)
  run_fio randwrite "$MNT/lat_wr.dat" 2>/dev/null > /root/fio_wr.json
  rd=$(parse /root/fio_rd.json read 2>/dev/null || echo "0,0")
  wr=$(parse /root/fio_wr.json write 2>/dev/null || echo "0,0")
  echo "${el},read,${rd},${ts},upgrade" >> "$CSV"
  echo "${el},write,${wr},${ts},upgrade" >> "$CSV"
  echo "elapsed=${el}s read=${rd} write=${wr}"
  # sleep to next 10s boundary
  now=$(date +%s)
  spent=$((now - loop_start))
  sl=$((10 - spent))
  [ $sl -gt 0 ] && sleep $sl
done
echo "LOOP STOPPED"
