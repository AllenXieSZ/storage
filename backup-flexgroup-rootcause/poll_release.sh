#!/bin/bash
# Poll: after AWS backup delete, check when the copy-to-cloud/SnapMirror ref releases
# and the FlexVol->FlexGroup conversion becomes possible.
cd "$(dirname "$0")"
DEL_START=1788095214
LOG=logs/release_poll.txt
echo "=== poll start $(date -u) (backup delete API was at epoch $DEL_START) ===" | tee -a $LOG
for round in 1 2 3 4 5 6; do
  NOW=$(date +%s); EL=$(( (NOW-DEL_START)/60 ))
  echo "" | tee -a $LOG
  echo "----- ROUND $round  (~${EL} min after delete)  $(date -u) -----" | tee -a $LOG
  echo "## snapshot show + snapmirror" | tee -a $LOG
  ./ontap.sh 'set -privilege diagnostic -confirmations off; volume snapshot show -vserver bkpfgsvm -volume bkpvol -fields snapshot; snapmirror show; snapmirror list-destinations' 2>&1 | tee -a $LOG
  echo "## conversion check-only" | tee -a $LOG
  CHK=$(./ontap.sh 'set -privilege diagnostic -confirmations off; volume conversion start -vserver bkpfgsvm -volume bkpvol -check-only true' 2>&1)
  echo "$CHK" | tee -a $LOG
  if echo "$CHK" | grep -qi "can proceed with the following warnings\|Job succeeded"; then
    echo ">>> CONVERSION NOW ALLOWED (warning only) at ~${EL} min <<<" | tee -a $LOG
    break
  fi
  if ! echo "$CHK" | grep -qi "copy to cloud\|SnapMirror relationship"; then
    echo ">>> copy-to-cloud error GONE at ~${EL} min <<<" | tee -a $LOG
    break
  fi
  echo "(still blocked; sleeping 10 min)" | tee -a $LOG
  sleep 600
done
echo "=== poll end $(date -u) ===" | tee -a $LOG
