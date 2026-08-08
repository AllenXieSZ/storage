#!/usr/bin/env python3
import boto3, time, csv, sys
from datetime import datetime, timedelta, timezone

REGION = "us-east-2"
FSID = "<YOUR_FSX_LUSTRE_FS_ID>"
OUT = "/home/ubuntu/.openclaw/workspace/dra_autoexport_age.csv"
INTERVAL = 10        # seconds between samples
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 3600  # total seconds to run

cw = boto3.client("cloudwatch", region_name=REGION)

def sample():
    # AgeOfOldestQueuedMessage, dim FileSystemId + Publisher=AutoImport
    now = datetime.now(timezone.utc)
    resp = cw.get_metric_statistics(
        Namespace="AWS/FSx",
        MetricName="AgeOfOldestQueuedMessage",
        Dimensions=[{"Name": "FileSystemId", "Value": FSID},
                    {"Name": "Publisher", "Value": "AutoExport"}],
        StartTime=now - timedelta(seconds=120),
        EndTime=now,
        Period=60,
        Statistics=["Maximum"],
    )
    dps = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
    if dps:
        return dps[-1]["Maximum"], dps[-1]["Timestamp"].strftime("%H:%M:%S")
    return None, None

def main():
    t0 = time.time()
    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["wallclock_utc", "elapsed_s", "metric_ts", "age_seconds"])
        while time.time() - t0 < DURATION:
            val, mts = sample()
            el = int(time.time() - t0)
            wc = datetime.now(timezone.utc).strftime("%H:%M:%S")
            w.writerow([wc, el, mts or "", "" if val is None else val])
            fh.flush()
            print(f"[{wc}] elapsed={el}s metric_ts={mts} age={val}", flush=True)
            time.sleep(INTERVAL)
    print("collector done", flush=True)

if __name__ == "__main__":
    main()
