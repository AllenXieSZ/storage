# Grafana Dashboards

## disk-characteristics-ebsnvme.json — "Disk Characteristics"

一个查看磁盘性能、利用率、饱和度的 Grafana dashboard（基于 Prometheus + node_exporter），
**集成了本仓库 `node-exporter-ebsnvme` collector 暴露的 EBS NVMe 详细性能指标**（`node_ebs_*`）。

### 面板内容
- 基础磁盘指标（来自 node_exporter 标准 diskstats）：IOPS、吞吐、利用率、队列深度、延迟等
- **EBS NVMe 专属指标**（来自 ebsnvme collector）：
  - 读写 IOPS / 吞吐 / 延迟
  - `node_ebs_exceeded_iops_seconds_total` / `node_ebs_exceeded_tp_seconds_total` — 卷因达到 IOPS/吞吐上限被限流的时间（排查"是不是被 EBS 卷配置卡住"的关键面板）

### 导入方法
1. Grafana → Dashboards → Import → Upload JSON file，选本文件
2. 选择你的 Prometheus 数据源
3. 前提：目标节点已运行打了 ebsnvme 补丁的 node_exporter 且启用 `--collector.ebsnvme`

### 脱敏说明
本 JSON 从生产 Grafana 导出后已脱敏：内网 IP、实例 ID、卷 ID 均替换为 `REDACTED_*` 占位；
移除了实例绑定字段（id/uid/iteration）。导入后按你自己的环境重新绑定数据源即可。
gnetId 9852 为其社区来源基底。
