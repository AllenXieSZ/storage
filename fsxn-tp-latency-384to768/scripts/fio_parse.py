#!/usr/bin/env python3
# fio_parse.py <json-file> <read|write>  -> "mean_us p99_us"
import sys,json
j=json.load(open(sys.argv[1]))
job=j["jobs"][0][sys.argv[2]]
clat=job["clat"]   # fio 2.14 -> usec
print(f"{clat['mean']:.2f} {clat['percentile']['99.000000']:.2f}")
