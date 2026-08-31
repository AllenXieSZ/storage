#!/bin/bash
FSID=fs-0f29a383fee84742e
T0=$(cat /home/ubuntu/.openclaw/workspace/lustre-expand-timing-v2/expand_t0.txt)
LOG=/home/ubuntu/.openclaw/workspace/lustre-expand-timing-v2/expand_poll.log
AVAIL_MARKED=0
> "$LOG"
for i in $(seq 1 200); do
  NOW=$(date -u +%s); REL=$((NOW-T0))
  J=$(aws fsx describe-file-systems --file-system-ids $FSID --region us-east-2 \
    --query 'FileSystems[0].{Life:Lifecycle,Cap:StorageCapacity,Actions:AdministrativeActions[].{T:AdministrativeActionType,S:Status,P:ProgressPercent}}' --output json 2>/dev/null)
  LIFE=$(echo "$J" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['Life'])" 2>/dev/null)
  CAP=$(echo "$J" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['Cap'])" 2>/dev/null)
  ACT=$(echo "$J" | python3 -c "import json,sys;d=json.load(sys.stdin);print(' | '.join('%s:%s:%s%%'%(a['T'],a['S'],a.get('P','-')) for a in (d['Actions'] or [])))" 2>/dev/null)
  echo "+${REL}s Life=$LIFE Cap=$CAP Act=[$ACT]" | tee -a "$LOG"
  # Check for STORAGE_OPTIMIZATION COMPLETED or actions cleared with cap=2400 available
  SO_DONE=$(echo "$J" | python3 -c "import json,sys;d=json.load(sys.stdin);acts=d['Actions'] or [];so=[a for a in acts if a['T']=='STORAGE_OPTIMIZATION'];print('DONE' if (so and so[0]['S']=='COMPLETED') else ('NONE' if (d['Cap']==2400 and d['Life']=='AVAILABLE' and not so) else 'WAIT'))" 2>/dev/null)
  if [[ "$SO_DONE" == "DONE" || "$SO_DONE" == "NONE" ]]; then
    echo "=== STORAGE_OPTIMIZATION finished (or gone) at +${REL}s ===" | tee -a "$LOG"
    break
  fi
  sleep 35
done
