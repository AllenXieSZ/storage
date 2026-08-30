#!/bin/bash
# Capture full diag-level snapmirror + snapshot state for a volume
# Usage: ./capture_state.sh <label>  (prints combined output)
cd "$(dirname "$0")"
SVM=bkpfgsvm
LABEL="$1"
echo "########## STATE CAPTURE: $LABEL ##########"
for VOL in bkpvol cleanvol; do
  echo "===== VOL=$VOL ====="
  ./ontap.sh "set -privilege diagnostic -confirmations off; snapmirror show -destination-volume $VOL"
  echo "--- snapmirror list-destinations (source=$VOL) ---"
  ./ontap.sh "set -privilege diagnostic -confirmations off; snapmirror list-destinations -source-volume $VOL"
  echo "--- snapmirror show-history ---"
  ./ontap.sh "set -privilege diagnostic -confirmations off; snapmirror show-history -destination-volume $VOL"
  echo "--- volume snapshot show ---"
  ./ontap.sh "set -privilege diagnostic -confirmations off; volume snapshot show -vserver $SVM -volume $VOL"
  echo "--- snapshot-count (volume show) ---"
  ./ontap.sh "set -privilege diagnostic -confirmations off; volume show -vserver $SVM -volume $VOL -fields snapshot-count,snapshot-policy"
done
