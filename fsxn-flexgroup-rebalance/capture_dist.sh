#!/bin/bash
# capture_dist.sh <label>  -- capture per-constituent used, compute aggr1/aggr2 data distribution
# FIO baseline = 49 GB on mfvol__0001 (aggr1), created pre-conversion. We subtract it.
LABEL="$1"
OUT=$(sshpass -p '<FSXADMIN_PW>' ssh -o StrictHostKeyChecking=no fsxadmin@<MGMT_IP> \
  "set -privilege diagnostic -confirmations off; volume show -vserver mfsvm -volume mfvol_* -fields aggregate,used" 2>&1)
echo "$OUT"
echo "$OUT" | awk -v label="$LABEL" '
function gb(s,   v,u){ v=s+0; if(index(s,"TB")) return v*1024; if(index(s,"MB")) return v/1024; if(index(s,"KB")) return v/1024/1024; return v }
/mfvol__/ {
  aggr=$3; used=gb($4);
  # subtract fio 49GB baseline from mfvol__0001
  if ($2=="mfvol__0001") used=used-49;
  if (aggr=="aggr1") a1+=used; else if (aggr=="aggr2") a2+=used;
}
END {
  tot=a1+a2;
  printf "LABEL=%s  aggr1=%.1fGB (%.1f%%)  aggr2=%.1fGB (%.1f%%)  total=%.1fGB  skew=%.1f:%.1f\n", label, a1, 100*a1/tot, a2, 100*a2/tot, tot, 100*a1/tot, 100*a2/tot;
}'
