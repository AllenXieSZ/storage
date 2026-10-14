#!/bin/bash
# Export CloudWatch TimeSinceLastSync (60s, Maximum) + source DataWriteIOBytes/MeteredIOBytes (60s, Sum)
# usage: SRC=fs-xxxx DST=fs-yyyy cw_export.sh <start ISO> <end ISO> <out dir>
S=$1; E=$2; O=$3; mkdir -p $O
aws cloudwatch get-metric-statistics --region ap-northeast-1 --namespace AWS/EFS --metric-name TimeSinceLastSync \
  --dimensions Name=FileSystemId,Value=$SRC Name=DestinationFileSystemId,Value=$DST \
  --start-time $S --end-time $E --period 60 --statistics Maximum Average --output json \
  | python3 -c 'import json,sys;d=sorted(json.load(sys.stdin)["Datapoints"],key=lambda x:x["Timestamp"]);print("ts,max_s,avg_s");[print(x["Timestamp"],x["Maximum"],x["Average"],sep=",") for x in d]' > $O/time_since_last_sync.csv
for M in DataWriteIOBytes MeteredIOBytes; do
aws cloudwatch get-metric-statistics --region ap-northeast-1 --namespace AWS/EFS --metric-name $M \
  --dimensions Name=FileSystemId,Value=$SRC --start-time $S --end-time $E --period 60 --statistics Sum SampleCount --output json \
  | python3 -c 'import json,sys;d=sorted(json.load(sys.stdin)["Datapoints"],key=lambda x:x["Timestamp"]);print("ts,sum_bytes,ops");[print(x["Timestamp"],int(x["Sum"]),int(x["SampleCount"]),sep=",") for x in d]' > $O/src_${M}.csv
done
wc -l $O/*.csv
