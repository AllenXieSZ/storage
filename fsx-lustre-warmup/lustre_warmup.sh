#!/bin/bash
# lustre_warmup.sh (改自 tzhu0704/s3warmup) — 增加 -f first_run 参数
#   -f true  : 跳过 identify（lfs hsm_state 逐个判断）阶段，直接对全部文件 hsm_restore
#              已 restore 的文件 hsm_restore 自动 no-op（AWS官方），适合"首次全量预热"。默认。
#   -f false : 原版逻辑，先 identify 出 released 文件再 restore（适合大部分文件已在本地、只想补少量时）。

LOG_DIR="."
LOG_FILE="${LOG_DIR}/lustre_warmup_$(date +%Y%m%d_%H%M%S).log"
PARALLEL_JOBS=32
BACKGROUND=false
BATCH_SIZE=10000
HSM_RESTORE_BATCH=5
FIRST_RUN=true          # 默认走 fast 逻辑（首次全量预热）

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
format_time() {
    local s=$1; printf "%02d:%02d:%02d" $((s/3600)) $(((s%3600)/60)) $((s%60))
}
usage() {
    echo "Usage: $0 [-b] [-j JOBS] [-s BATCH_SIZE] [-n HSM_BATCH] [-f true|false] -d DIRECTORY"
    echo "  -b           Run in background mode (nohup)"
    echo "  -j JOBS      Number of parallel jobs (default: 32)"
    echo "  -s SIZE      Batch size for progress reporting (default: 10000)"
    echo "  -n SIZE      Files per hsm_restore command (default: 5)"
    echo "  -f true|false  first_run: true=skip identify, restore ALL directly (default true)"
    echo "  -d DIR       Directory to process (required)"
    exit 1
}

DIRECTORY=""
while getopts "bd:j:s:n:f:h" opt; do
    case $opt in
        b) BACKGROUND=true ;;
        d) DIRECTORY=$OPTARG ;;
        j) PARALLEL_JOBS=$OPTARG ;;
        s) BATCH_SIZE=$OPTARG ;;
        n) HSM_RESTORE_BATCH=$OPTARG ;;
        f) FIRST_RUN=$OPTARG ;;
        h) usage ;;
        *) usage ;;
    esac
done
[ -z "$DIRECTORY" ] && usage

if [ "$BACKGROUND" = true ] && [ -z "$NOHUP_ACTIVE" ]; then
    log "Restarting in background mode..."
    export NOHUP_ACTIVE=1
    nohup "$0" "$@" > "${LOG_FILE}_nohup" 2>&1 &
    echo "Process started in background with PID $!"
    echo "Monitor: tail -f ${LOG_FILE}_nohup  (or $LOG_FILE)"
    exit 0
fi

log "Starting Lustre warmup for: $DIRECTORY"
log "Parallel jobs=$PARALLEL_JOBS, hsm_restore batch=$HSM_RESTORE_BATCH, first_run=$FIRST_RUN"
START_TIME=$(date +%s)

TEMP_DIR=$(mktemp -d)
TEMP_ALL_FILES="$TEMP_DIR/all_files.txt"
TEMP_RELEASED_FILES="$TEMP_DIR/released_files.txt"
TEMP_SUCCESS="$TEMP_DIR/success.txt"
TEMP_FAILED="$TEMP_DIR/failed.txt"
touch "$TEMP_ALL_FILES" "$TEMP_RELEASED_FILES" "$TEMP_SUCCESS" "$TEMP_FAILED"

log "Scanning for files..."
find "$DIRECTORY" -type f > "$TEMP_ALL_FILES"
TOTAL_FILES=$(wc -l < "$TEMP_ALL_FILES")
log "Found total $TOTAL_FILES files"

if [ "$FIRST_RUN" = true ]; then
    # ---- FAST 路径：跳过 identify，全部文件即待 restore 列表 ----
    log "first_run=true → SKIP identify phase, restoring ALL files directly (already-restored will no-op)"
    cp "$TEMP_ALL_FILES" "$TEMP_RELEASED_FILES"
else
    # ---- 原版 identify：逐个 lfs hsm_state 找 released ----
    log "first_run=false → identifying released files via lfs hsm_state..."
    FIFO_IDENTIFY="$TEMP_DIR/identify_fifo"; mkfifo "$FIFO_IDENTIFY"
    (
        processed=0
        while IFS= read -r file; do
            [[ -n "$file" ]] && echo "$file" >> "$TEMP_RELEASED_FILES"
            ((processed++))
            if [ $((processed % BATCH_SIZE)) -eq 0 ]; then
                log "Checking files: $processed/$TOTAL_FILES ($(( processed * 100 / TOTAL_FILES ))%)"
            fi
        done < "$FIFO_IDENTIFY"
    ) &
    COLLECTOR_PID=$!
    cat "$TEMP_ALL_FILES" | xargs -P "$PARALLEL_JOBS" -I{} bash -c '
        file="$1"
        if lfs hsm_state "$file" 2>/dev/null | grep -q "released"; then
            echo "$file"
        fi
    ' -- {} > "$FIFO_IDENTIFY"
    wait $COLLECTOR_PID
fi

RELEASED_FILES=$(wc -l < "$TEMP_RELEASED_FILES")
log "Files to warm up: $RELEASED_FILES"
if [ "$RELEASED_FILES" -eq 0 ]; then
    log "Nothing to warm up. Exiting."; rm -rf "$TEMP_DIR"; exit 0
fi

log "Starting restore: $PARALLEL_JOBS parallel jobs, $HSM_RESTORE_BATCH files/cmd"
PROGRESS_PIPE="$TEMP_DIR/progress_pipe"; mkfifo "$PROGRESS_PIPE"
(
    while IFS= read -r line; do
        if   [[ $line == SUCCESS* ]]; then echo "${line#SUCCESS }" >> "$TEMP_SUCCESS"
        elif [[ $line == FAILED*  ]]; then echo "${line#FAILED }"  >> "$TEMP_FAILED"; fi
        SUCCESS=$(wc -l < "$TEMP_SUCCESS"); FAILED=$(wc -l < "$TEMP_FAILED")
        PROCESSED=$((SUCCESS + FAILED))
        if [ $((PROCESSED % 1000)) -eq 0 ] || [ "$PROCESSED" -eq "$RELEASED_FILES" ]; then
            NOW=$(date +%s); EL=$((NOW - START_TIME))
            RATE=$([ $EL -gt 0 ] && bc <<< "scale=2; $PROCESSED / $EL" || echo "N/A")
            log "Progress: $((PROCESSED*100/RELEASED_FILES))% ($PROCESSED/$RELEASED_FILES) - Rate: $RATE files/sec - Success: $SUCCESS - Failed: $FAILED"
        fi
    done < "$PROGRESS_PIPE"
) &
MONITOR_PID=$!

run_batch() {
    cat "$1" | xargs -P "$PARALLEL_JOBS" -n "$HSM_RESTORE_BATCH" bash -c '
        files=("$@")
        if lfs hsm_restore "${files[@]}" 2>/dev/null; then
            for f in "${files[@]}"; do echo "SUCCESS $f"; done
        else
            for f in "${files[@]}"; do echo "FAILED $f"; done
        fi
    ' bash
}

if [ "$RELEASED_FILES" -gt 100000 ]; then
    log "Large file count, processing in batches of 10000..."
    split -l 10000 "$TEMP_RELEASED_FILES" "$TEMP_DIR/batch_"
    for bf in "$TEMP_DIR"/batch_*; do run_batch "$bf" >> "$PROGRESS_PIPE"; done
else
    run_batch "$TEMP_RELEASED_FILES" > "$PROGRESS_PIPE"
fi

exec {PROGRESS_PIPE}>&-
wait $MONITOR_PID

END_TIME=$(date +%s); TOTAL_TIME=$((END_TIME - START_TIME))
FINAL_SUCCESS=$(wc -l < "$TEMP_SUCCESS"); FINAL_FAILED=$(wc -l < "$TEMP_FAILED")
log "----------------------------------------"
log "Warmup completed (first_run=$FIRST_RUN)"
log "Total time: $(format_time $TOTAL_TIME)"
log "Processed: $((FINAL_SUCCESS+FINAL_FAILED))  Success: $FINAL_SUCCESS  Failed: $FINAL_FAILED"
log "----------------------------------------"
[ $FINAL_FAILED  -gt 0 ] && cp "$TEMP_FAILED"  "${LOG_FILE}_failed"
[ $FINAL_SUCCESS -gt 0 ] && cp "$TEMP_SUCCESS" "${LOG_FILE}_success"
rm -rf "$TEMP_DIR"
