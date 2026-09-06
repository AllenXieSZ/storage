# fsxn-tp-latency-384to768

FSx for NetApp ONTAP (Gen2, SINGLE_AZ_2, single HA pair) — measuring NFSv3 IO latency
impact while upgrading throughput capacity **384 → 768 MBps/HA pair** (online, non-disruptive).

## TL;DR

- **Upgrade duration**: ~26 min (online, no NFS disruption).
- **One brief transient spike** ~3–4 min in: read p99 ≈ **20.4 ms**, write mean ≈ **8.9 ms** (single-sample glitch, likely the node reconfig/failover moment).
- **Steady state after**: read recovers near baseline (~180→255 us); **write stays elevated ~300→450 us (+~50%)**.

See [REPORT.md](REPORT.md) for full detail and [latency_curve_384to768.png](latency_curve_384to768.png) for the curve.

## Files

| File | Description |
|------|-------------|
| `REPORT.md` | Full experiment report (env, timing, stats, conclusion) |
| `latency_curve_384to768.png` | Two-panel latency curve (full-range + zoom), baseline / upgrade window / peaks annotated |
| `tp384_results.csv` | Raw fio samples: `elapsed_sec,op,lat_mean_us,lat_p99_us,timestamp,phase` |
| `scripts/latency_probe.sh` | On-instance fio probe loop (baseline/upgrade/post phases) |
| `scripts/fio_parse.py` | Parse fio 2.14 JSON → clat mean/p99 (usec) |
| `scripts/plot_latency.py` | Build the PNG from the CSV |
| `scripts/ssmrun.py` | Drive commands on the private jump host via SSM (base64-wrapped) |

## fio config (unchanged from sibling experiment)

`bs=16k ioengine=sync direct=1 numjobs=1 iodepth=1 runtime=8 -time_based`, randread + randwrite,
one sample each per round, ~18s cadence. clat mean + p99 recorded.

## Method

1. Dedicated isolated SG + fresh FSxN 384-tier + SVM + FlexVol; mount NFSv3 on jump host.
2. 5 baseline rounds.
3. Fire `update-file-system ThroughputCapacityPerHAPair=768`; probe every ~18s until
   `AdministrativeAction FILE_SYSTEM_UPDATE == COMPLETED`.
4. 5 post-upgrade tail rounds.
5. Plot + report; **all experiment resources deleted afterward** (volume→SVM→FS→SG).

Private network access via SSM + S3 relay. Throughput tiers verified against Terraform/AWS official docs
(SINGLE_AZ_2 single-HA valid tiers: 384/768/1536/3072/6144).
