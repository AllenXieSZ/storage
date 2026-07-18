#!/bin/bash
# Lustre 2.15.8 self-built cluster performance benchmark
# Run ON the client node. 4 OST (each 1x gp3 100G, baseline 125MB/s), MDT on gp3.
set -u
M=/mnt/lustre
B=$M/bench
sudo mkdir -p $B && sudo chmod 777 $B
cd $B

echo "############ ENV ############"
uname -r; nproc; free -g | head -2
lfs df -h $M
echo "default stripe:"; lfs getstripe -d $M

# helper
run_fio () {
  local name="$1"; shift
  echo "===FIO $name==="
  fio --group_reporting --output-format=terse "$@" 2>/dev/null | awk -F';' '{print}'
}

######################################################################
echo ""
echo "############ 1. SINGLE-STREAM SEQUENTIAL (stripe_count=1) ############"
lfs setstripe -c 1 -S 1M $B
rm -f seq1.dat
fio --name=seqwrite1 --filename=$B/seq1.dat --rw=write --bs=1M --size=8G \
    --ioengine=libaio --direct=1 --iodepth=16 --numjobs=1 --group_reporting 2>/dev/null \
    | grep -E 'WRITE:|write:' | head -2
sync
fio --name=seqread1 --filename=$B/seq1.dat --rw=read --bs=1M --size=8G \
    --ioengine=libaio --direct=1 --iodepth=16 --numjobs=1 --group_reporting 2>/dev/null \
    | grep -E 'READ:|read:' | head -2
rm -f $B/seq1.dat

######################################################################
echo ""
echo "############ 2. WIDE-STRIPE SEQUENTIAL (stripe_count=4, all OST) ############"
mkdir -p $B/wide; lfs setstripe -c 4 -S 1M $B/wide
rm -f $B/wide/*.dat
echo "--- write, 4 jobs each own file, striped across 4 OST ---"
fio --name=seqw4 --directory=$B/wide --rw=write --bs=1M --size=8G --nrfiles=1 \
    --ioengine=libaio --direct=1 --iodepth=16 --numjobs=4 --group_reporting 2>/dev/null \
    | grep -E 'WRITE:' | head -2
sync; sudo bash -c 'echo 3 > /proc/sys/vm/drop_caches'
echo "--- read ---"
fio --name=seqr4 --directory=$B/wide --rw=read --bs=1M --size=8G --nrfiles=1 \
    --ioengine=libaio --direct=1 --iodepth=16 --numjobs=4 --group_reporting 2>/dev/null \
    | grep -E 'READ:' | head -2
rm -f $B/wide/*.dat

######################################################################
echo ""
echo "############ 3. RANDOM IOPS 4K (stripe_count=4) ############"
mkdir -p $B/rand; lfs setstripe -c 4 -S 1M $B/rand
echo "--- randwrite 4k ---"
fio --name=rw4k --directory=$B/rand --rw=randwrite --bs=4k --size=2G --nrfiles=1 \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=8 --group_reporting 2>/dev/null \
    | grep -E 'write: IOPS' | head -1
echo "--- randread 4k ---"
fio --name=rr4k --directory=$B/rand --rw=randread --bs=4k --size=2G --nrfiles=1 \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=8 --group_reporting 2>/dev/null \
    | grep -E 'read: IOPS' | head -1
rm -f $B/rand/*

######################################################################
echo ""
echo "############ 4. METADATA (file create/stat/unlink) ############"
mkdir -p $B/meta; lfs setstripe -c 1 $B/meta
echo "--- create 20000 empty files (single thread) ---"
cd $B/meta
t0=$(date +%s.%N)
for i in $(seq 1 20000); do : > f$i; done
t1=$(date +%s.%N)
echo "create 20000: $(echo "$t1-$t0"|bc)s -> $(echo "20000/($t1-$t0)"|bc) files/s"
t0=$(date +%s.%N); ls -f | wc -l >/dev/null; t1=$(date +%s.%N)
echo "stat(ls) 20000: $(echo "$t1-$t0"|bc)s"
t0=$(date +%s.%N); rm -f f*; t1=$(date +%s.%N)
echo "unlink 20000: $(echo "$t1-$t0"|bc)s"
cd $B

echo ""
echo "############ DONE ############"
rm -rf $B
