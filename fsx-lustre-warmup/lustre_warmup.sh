#!/bin/bash

# Configuration
LOG_DIR="."
LOG_FILE="${LOG_DIR}/lustre_warmup_$(date +%Y%m%d_%H%M%S).log"
PARALLEL_JOBS=32  # Number of parallel restore jobs
BACKGROUND=false
BATCH_SIZE=10000  # Process files in batches for progress reporting
HSM_RESTORE_BATCH=5  # Number of files to process in each hsm_restore command
FIRST_RUN=true  # CHANGE: first_run=true skips identify phase and restores ALL files directly (default)

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to format time
format_time() {
    local seconds=$1
    local hours=$((seconds / 3600))
    local minutes=$(( (seconds % 3600) / 60 ))
    local remaining_seconds=$((seconds % 60))
    printf "%02d:%02d:%02d" $hours $minutes $remaining_seconds
}

# Function to show usage
usage() {
    echo "Usage: $0 [-b] [-j JOBS] [-s BATCH_SIZE] [-n HSM_BATCH] -d DIRECTORY"
    echo "  -b           Run in background mode (nohup)"
    echo "  -j JOBS      Number of parallel jobs (default: 32)"
    echo "  -s SIZE      Batch size for progress reporting (default: 10000)"
    echo "  -n SIZE      Number of files to process in each hsm_restore command (default: 5)"
    echo "  -f true|false  CHANGE: first_run; true skips identify and restores ALL files (default true)"
    echo "  -d DIR       Directory to process (required)"
    exit 1
}

# Parse command line arguments
DIRECTORY=""
while getopts "bd:j:s:n:f:h" opt; do
    case $opt in
        b) BACKGROUND=true ;;
        d) DIRECTORY=$OPTARG ;;
        j) PARALLEL_JOBS=$OPTARG ;;
        s) BATCH_SIZE=$OPTARG ;;
        n) HSM_RESTORE_BATCH=$OPTARG ;;
        f) FIRST_RUN=$OPTARG ;;  # CHANGE: first_run flag
        h) usage ;;
        *) usage ;;
    esac
done

# Check if directory is provided
if [ -z "$DIRECTORY" ]; then
    usage
fi

# If background mode is enabled, restart the script with nohup
if [ "$BACKGROUND" = true ] && [ -z "$NOHUP_ACTIVE" ]; then
    log "Restarting in background mode..."
    export NOHUP_ACTIVE=1
    nohup "$0" "$@" > "${LOG_FILE}_nohup" 2>&1 &
    echo "Process started in background with PID $!"
    echo "You can monitor progress with: tail -f ${LOG_FILE}_nohup"
    echo "Or check the log file: $LOG_FILE"
    exit 0
fi

# Main process
log "Starting Lustre warmup process for directory: $DIRECTORY"
log "Using $PARALLEL_JOBS parallel jobs"
log "Using batch size of $HSM_RESTORE_BATCH files per hsm_restore command"
START_TIME=$(date +%s)

# Create temporary directory for processing
TEMP_DIR=$(mktemp -d)
TEMP_ALL_FILES="$TEMP_DIR/all_files.txt"
TEMP_RELEASED_FILES="$TEMP_DIR/released_files.txt"
TEMP_SUCCESS="$TEMP_DIR/success.txt"
TEMP_FAILED="$TEMP_DIR/failed.txt"
PROGRESS_FILE="$TEMP_DIR/progress.txt"

# Create empty files
touch "$TEMP_ALL_FILES" "$TEMP_RELEASED_FILES" "$TEMP_SUCCESS" "$TEMP_FAILED"
echo "0" > "$PROGRESS_FILE"

log "Scanning for files..."
# CHANGE: one-shot find (write list directly) is far faster than the per-file bash while-loop
# for millions of files; report start and completion so the user sees progress.
find "$DIRECTORY" -type f > "$TEMP_ALL_FILES"
TOTAL_FILES=$(wc -l < "$TEMP_ALL_FILES")
log "Found total $TOTAL_FILES files"

# CHANGE: when first_run=true, skip identify and treat ALL files as needing restore
#         (already-restored files become a harmless no-op on hsm_restore).
if [ "$FIRST_RUN" = true ]; then
    log "first_run=true -> skip identify phase, restore ALL files directly"
    cp "$TEMP_ALL_FILES" "$TEMP_RELEASED_FILES"
else
# Find files that need release - using parallel processing
log "Identifying release files in parallel..."
log "Identifying may take a while for millions of files..."

# Create a named pipe for collecting results
FIFO_IDENTIFY="$TEMP_DIR/identify_fifo"
mkfifo "$FIFO_IDENTIFY"

# Start background process to collect results
(
    processed=0
    while IFS= read -r file; do
        if [[ -n "$file" ]]; then
            echo "$file" >> "$TEMP_RELEASED_FILES"
        fi
        
        ((processed++))
        if [ $((processed % BATCH_SIZE)) -eq 0 ]; then
            log "Checking files: $processed/$TOTAL_FILES ($(( processed * 100 / TOTAL_FILES ))%)"
        fi
    done < "$FIFO_IDENTIFY"
) &
COLLECTOR_PID=$!

# Process files in parallel to identify which need release
cat "$TEMP_ALL_FILES" | xargs -P "$PARALLEL_JOBS" -I{} bash -c '
    file="$1"
    if lfs hsm_state "$file" 2>/dev/null | grep -q "released exists archived"; then
        echo "$file"
    fi
' -- {} > "$FIFO_IDENTIFY"

# Wait for collector to finish
wait $COLLECTOR_PID
fi  # CHANGE: end of first_run if/else

RELEASED_FILES=$(wc -l < "$TEMP_RELEASED_FILES")
log "Found $RELEASED_FILES files that need warming up"

if [ "$RELEASED_FILES" -eq 0 ]; then
    log "No files need warming up. Exiting."
    rm -rf "$TEMP_DIR"
    exit 0
fi

# Process files in parallel using xargs
log "Starting warmup process with $PARALLEL_JOBS parallel jobs"
log "Processing $HSM_RESTORE_BATCH files per hsm_restore command"

# CHANGE (bugfix): mark when the *restore* phase actually begins, so the reported
# rate reflects restore throughput only — NOT the whole script runtime (which
# includes scan + identify and made the rate look ~7x too low, e.g. 51/s vs real 361/s).
RESTORE_START_TIME=$(date +%s)
export RESTORE_START_TIME

# Create a named pipe for real-time progress monitoring
PROGRESS_PIPE="$TEMP_DIR/progress_pipe"
mkfifo "$PROGRESS_PIPE"

# Start background process to monitor progress
(
    # CHANGE: in-memory counters instead of "wc -l" on growing files (avoids O(n^2) slowdown)
    SUCCESS=0
    FAILED=0
    # CHANGE (bugfix): track previous report point to compute an *interval* (instantaneous)
    # rate over the last reporting window — the most useful signal for "is it speeding up?".
    PREV_TIME=$RESTORE_START_TIME
    PREV_PROCESSED=0
    while IFS= read -r line; do
        if [[ $line == SUCCESS* ]]; then
            echo "${line#SUCCESS }" >> "$TEMP_SUCCESS"
            ((SUCCESS++))
        elif [[ $line == FAILED* ]]; then
            echo "${line#FAILED }" >> "$TEMP_FAILED"
            ((FAILED++))
        fi

        # Calculate current progress
        PROCESSED=$((SUCCESS + FAILED))

        if [ $((PROCESSED % 1000)) -eq 0 ] || [ "$PROCESSED" -eq "$RELEASED_FILES" ]; then
            CURRENT_TIME=$(date +%s)
            # CHANGE (bugfix): average rate measured from RESTORE_START_TIME, not script START_TIME.
            RESTORE_ELAPSED=$((CURRENT_TIME - RESTORE_START_TIME))
            if [ $RESTORE_ELAPSED -gt 0 ]; then
                AVG_RATE=$(bc <<< "scale=2; $PROCESSED / $RESTORE_ELAPSED")
            else
                AVG_RATE="N/A"
            fi

            # CHANGE (bugfix): interval rate over the last window (files since last report / seconds since last report).
            INTERVAL_TIME=$((CURRENT_TIME - PREV_TIME))
            INTERVAL_FILES=$((PROCESSED - PREV_PROCESSED))
            if [ $INTERVAL_TIME -gt 0 ]; then
                INST_RATE=$(bc <<< "scale=2; $INTERVAL_FILES / $INTERVAL_TIME")
            else
                INST_RATE="$AVG_RATE"
            fi
            PREV_TIME=$CURRENT_TIME
            PREV_PROCESSED=$PROCESSED

            PROGRESS=$((PROCESSED * 100 / RELEASED_FILES))
            # AvgRate = restore-only average; InstRate = throughput over the last window.
            log "Progress: $PROGRESS% ($PROCESSED/$RELEASED_FILES) - AvgRate: $AVG_RATE files/sec - InstRate: $INST_RATE files/sec - Success: $SUCCESS - Failed: $FAILED"
        fi
    done < "$PROGRESS_PIPE"
) &
MONITOR_PID=$!

# Process files and send output to the pipe
# Use split processing for very large file lists to avoid command line length limits
if [ "$RELEASED_FILES" -gt 100000 ]; then
    log "Large file count detected, processing in batches..."
    
    # Split the file list into smaller chunks
    split -l 10000 "$TEMP_RELEASED_FILES" "$TEMP_DIR/batch_"
    
    # Process each batch
    for batch_file in "$TEMP_DIR"/batch_*; do
        cat "$batch_file" | xargs -P "$PARALLEL_JOBS" -n "$HSM_RESTORE_BATCH" bash -c '
            files=("$@")
            if lfs hsm_restore "${files[@]}" 2>/dev/null; then
                for file in "${files[@]}"; do
                    echo "SUCCESS $file"
                done
            else
                for file in "${files[@]}"; do
                    echo "FAILED $file"
                done
            fi
        ' bash >> "$PROGRESS_PIPE"
    done
else
    # Process all files at once for smaller lists
    cat "$TEMP_RELEASED_FILES" | xargs -P "$PARALLEL_JOBS" -n "$HSM_RESTORE_BATCH" bash -c '
        files=("$@")
        if lfs hsm_restore "${files[@]}" 2>/dev/null; then
            for file in "${files[@]}"; do
                echo "SUCCESS $file"
            done
        else
            for file in "${files[@]}"; do
                echo "FAILED $file"
            done
        fi
    ' bash > "$PROGRESS_PIPE"
fi

# Close the pipe to signal the monitor that we're done
exec {PROGRESS_PIPE}>&-

# Wait for monitor process to finish
wait $MONITOR_PID

# Calculate final statistics
END_TIME=$(date +%s)
TOTAL_TIME=$((END_TIME - START_TIME))
FORMATTED_TIME=$(format_time $TOTAL_TIME)
# CHANGE (bugfix): also report restore-only time/rate so the headline number isn't
# diluted by the scan + identify phases.
RESTORE_TIME=$((END_TIME - RESTORE_START_TIME))
FORMATTED_RESTORE_TIME=$(format_time $RESTORE_TIME)

# Get final counts
FINAL_SUCCESS=$(wc -l < "$TEMP_SUCCESS")
FINAL_FAILED=$(wc -l < "$TEMP_FAILED")
FINAL_PROCESSED=$((FINAL_SUCCESS + FINAL_FAILED))
if [ $RESTORE_TIME -gt 0 ]; then
    FINAL_RESTORE_RATE=$(bc <<< "scale=2; $FINAL_PROCESSED / $RESTORE_TIME")
else
    FINAL_RESTORE_RATE="N/A"
fi

# Final report
log "Warmup process completed"
log "----------------------------------------"
log "Total time (incl. scan+identify): $FORMATTED_TIME"
log "Restore-only time: $FORMATTED_RESTORE_TIME"
log "Restore-only average rate: $FINAL_RESTORE_RATE files/sec"
log "Total files processed: $FINAL_PROCESSED"
log "Successfully warmup: $FINAL_SUCCESS"
log "Failed to warmup: $FINAL_FAILED"

# Copy results to permanent log files
if [ $FINAL_FAILED -gt 0 ]; then
    cp "$TEMP_FAILED" "${LOG_FILE}_failed"
    log "Failed files are listed in: ${LOG_FILE}_failed"
fi
if [ $FINAL_SUCCESS -gt 0 ]; then
    cp "$TEMP_SUCCESS" "${LOG_FILE}_success"
    log "Successful files are listed in: ${LOG_FILE}_success"
fi
log "----------------------------------------"

# Cleanup
rm -rf "$TEMP_DIR"

# Create completion marker if running in background
if [ "$BACKGROUND" = true ]; then
    touch "${LOG_FILE}.completed"
    log "Background job completed. Marker file created: ${LOG_FILE}.completed"
fi


