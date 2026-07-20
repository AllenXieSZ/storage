# node_exporter `ebsnvme` collector

给 Prometheus [node_exporter](https://github.com/prometheus/node_exporter) 新增的一个 Linux collector，采集 **Amazon EBS NVMe 详细性能统计**（Nitro 实例通过 EBS NVMe 设备 log page `0xD0` 暴露的指标）。

## 背景
Nitro 实例上的 EBS 卷会通过 NVMe device log page 暴露一批[详细性能统计](https://docs.aws.amazon.com/ebs/latest/userguide/nvme-detailed-performance-stats.html)（读写 IOPS/吞吐/延迟直方图、以及因 IOPS/吞吐达到卷上限而被限流的时间）。这些数据 CloudWatch 有一定延迟且粒度有限，直接从 NVMe log page 读能拿到实例本地、秒级的第一手数据。本 collector 把它们接入 node_exporter。

## 暴露的指标（namespace=`node`, subsystem=`ebs`）
- `node_ebs_read_ops_total` / `node_ebs_write_ops_total` — 读/写操作数
- `node_ebs_read_bytes_total` / `node_ebs_write_bytes_total` — 读/写字节数
- `node_ebs_read_seconds_total` / `node_ebs_write_seconds_total` — 读/写总耗时
- `node_ebs_exceeded_iops_seconds_total` — 因达到卷 IOPS 上限被限流的时间
- `node_ebs_exceeded_tp_seconds_total` — 因达到卷吞吐上限被限流的时间
- 读写延迟直方图（`node_ebs_read_io_latency_seconds_bucket` 等）

> `exceeded_iops` / `exceeded_tp` 特别有用：能直接看到卷是不是被自身配置的 IOPS/吞吐上限卡住，是 EBS 性能排查的关键信号。

## 文件
- `ebsnvme_linux.go` — collector 实现（对应 node_exporter v1.11.1）
- `ebsnvme_linux_test.go` — 单元测试（测试里的 vol-ID 已用示例值脱敏）
- `ebsnvme-collector.patch` — 完整补丁，可直接 apply 到 node_exporter 源码树
- `PR.md` — 给上游 node_exporter 提 PR 的说明

## 使用
```bash
# 打补丁到 node_exporter 源码
cd node_exporter
patch -p1 < /path/to/ebsnvme-collector.patch
make build
# 启用 collector（默认 disabled）
./node_exporter --collector.ebsnvme
```

配套 Grafana dashboard 见仓库 `grafana-dashboards/disk-characteristics-ebsnvme.json`。

> 注：collector 默认 disabled，需显式 `--collector.ebsnvme` 开启。读 NVMe log page 需要对应设备权限。

## 上游 node_exporter README 中的 collector 描述行（提交版）
```
197:ebsnvme | Exposes [Amazon EBS detailed performance statistics](https://docs.aws.amazon.com/ebs/latest/userguide/nvme-detailed-performance-stats.html) read from the EBS NVMe device log page (IOPS, throughput, latency histograms, queue length), labelled by `volume_id`, `device`, and `mount_path`. Requires running on a Nitro-based EC2 instance with `CAP_SYS_ADMIN` (typically as root) to issue the NVMe admin ioctl. | Linux
```
