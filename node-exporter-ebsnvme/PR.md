# PR: add `ebsnvme` collector for Amazon EBS NVMe performance statistics

Target: https://github.com/prometheus/node_exporter  (branch `feat/ebsnvme-collector`)

---

## PR Title

```
collector: add ebsnvme collector for Amazon EBS NVMe performance stats
```

## PR Description (paste into GitHub)

This adds a new **disabled-by-default** Linux collector, `ebsnvme`, that exposes the
[Amazon EBS detailed performance statistics](https://docs.aws.amazon.com/ebs/latest/userguide/nvme-detailed-performance-stats.html)
that Nitro-based EC2 instances vend through the EBS NVMe device log page (log page `0xD0`).

### What it does
For every EBS-backed NVMe device, the collector:
1. Maps NVMe devices to EBS volume IDs and mount paths via `lsblk -nd --json -o NAME,SERIAL,MOUNTPOINT`.
2. Reads EBS statistics log page `0xD0` via an NVMe admin ioctl (`NVME_IOCTL_ADMIN_CMD`).
3. Parses the binary EBS statistics structure (validated by its magic number `0x3C23B510`).
4. Exposes the values as Prometheus metrics labelled by `volume_id`, `device`, `mount_path`.

### Metrics (namespace `node_ebs_*`)
- `node_ebs_read_ops_total`, `node_ebs_write_ops_total`
- `node_ebs_read_bytes_total`, `node_ebs_write_bytes_total`
- `node_ebs_read_seconds_total`, `node_ebs_write_seconds_total`
- `node_ebs_exceeded_iops_seconds_total`, `node_ebs_exceeded_tp_seconds_total`
- `node_ebs_ec2_exceeded_iops_seconds_total`, `node_ebs_ec2_exceeded_tp_seconds_total`
- `node_ebs_volume_queue_length`
- `node_ebs_read_io_latency_seconds`, `node_ebs_write_io_latency_seconds` (histograms)

Each metric Help string references the corresponding official EBS statistic name
(e.g. `total_read_ops`, `ebs_volume_performance_exceeded_iops`,
`read_io_latency_histogram`) from the EBS User Guide.

### Why disabled by default
- Linux + Nitro-EC2 + EBS NVMe specific; meaningless elsewhere.
- Issues an NVMe admin ioctl per device. Enable with `--collector.ebsnvme`.

### Attribution / licensing
The EBS log-page parsing logic is derived from the **Amazon EBS CSI Driver**
(`pkg/metrics/nvme.go`, Apache-2.0, Copyright The Kubernetes Authors). This is noted
in the file header alongside the standard Prometheus Apache-2.0 header.

### Testing
- `gofmt` clean.
- `go build` OK (linux/amd64).
- Unit tests pass: `TestParseEBSLogPageInvalidMagic`, `TestParseEBSLogPageValid`, `TestConvertEBSHistogram`.
- Validated live on a MySQL EC2 (us-east-2) with 6 EBS NVMe volumes: single Prometheus
  scraper, scrape duration steady 24–47 ms, target up 100% over 30+ min. Grafana panels
  (latency, P99, throughput, size, IOPS, exceeded, queue length) render per-volume with
  `mount_path` labels — see screenshots.

### Notes
- Commit is DCO signed-off.
- `mount_path` is `NotMounted` for devices with no direct mount point (e.g. a disk mounted
  only through one of its partitions).

---

## Files changed
- `collector/ebsnvme_linux.go`  (new)
- `collector/ebsnvme_linux_test.go`  (new)
- `README.md`  (one line in the "Disabled by default" table)

## Screenshots for the PR (in S3)
- `s3://<BUCKET>/node_exporter/sample/sample1.png`
- `s3://<BUCKET>/node_exporter/sample/sample2.png`
- `s3://<BUCKET>/node_exporter/sample/sample3.png`

---

## How to push (auth note)

The box's only GitHub credential is the deploy key bound to `AllenXieSZ/storage`, so the
fork + push must be done by you. Two options:

### Option A — apply the patch on a fresh fork (recommended)
```bash
# 1. On github.com: Fork prometheus/node_exporter into AllenXieSZ/node_exporter
git clone git@github.com:AllenXieSZ/node_exporter.git
cd node_exporter
git checkout -b feat/ebsnvme-collector
git am /path/to/ebsnvme-collector.patch     # preserves author + DCO sign-off
git push -u origin feat/ebsnvme-collector
# 2. Open PR from AllenXieSZ:feat/ebsnvme-collector -> prometheus:master
```

### Option B — copy the 3 files
Copy `collector/ebsnvme_linux.go`, `collector/ebsnvme_linux_test.go`, and the README line
into a fresh fork, then commit with `git commit -s` (DCO sign-off required).

Patch file: `/home/ubuntu/.openclaw/workspace/ebsnvme-collector.patch`
