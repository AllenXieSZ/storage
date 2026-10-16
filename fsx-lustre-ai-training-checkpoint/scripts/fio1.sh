#!/bin/bash
# usage: fio1.sh <dir> <write|read> <numjobs> <stripe_count> [size]
D=$1; RW=$2; NJ=$3; SC=$4; SZ=${5:-8G}
mkdir -p $D; [ "$RW" = write ] && lfs setstripe -c $SC $D
sync; echo 3 > /proc/sys/vm/drop_caches
fio --name=s --directory=$D --rw=$RW --bs=16M --size=$SZ --numjobs=$NJ --ioengine=libaio --iodepth=8 --direct=1 --group_reporting --output-format=json > /tmp/fio.json 2>/tmp/fio.err
python3 -c "import json;j=json.load(open('/tmp/fio.json'))['jobs'][0];k='$RW';b=j[k]['bw_bytes'];print('FIO $RW nj=$NJ sc=$SC', round(b/1e9,2),'GB/s', round(b*8/1e9,1),'Gbps')"
