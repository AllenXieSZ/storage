# FSx for Lustre Intelligent-Tiering：不同 SSD cache 下的 OSS/MDS 拓扑实测

**实验日期**：2026-08-20（us-east-2）

> ⚠️ **本文是实验观测 + 推测**：AWS 官方文档**未公开** Intelligent-Tiering 的后台 OSS/MDS 数量与内部拓扑。本文结论是通过实际挂载 4 个不同配置的文件系统、用 `lfs df` 观察得出的**经验规律与推测**，不代表 AWS 官方保证，未来版本可能变化。
> 所有敏感值（账号、资源 ID、IP）已脱敏。

---

## 背景

FSx Lustre Intelligent-Tiering（IT）是弹性、跨 AZ 复制、吞吐与容量解耦的存储类，带三层缓存（file server in-memory cache → 可选 SSD read cache → IT 底层区域存储）。官方文档说明了缓存/性能特征，但**没有暴露后台有几个 OSS(OST) / MDS(MDT)**。本实验测：**SSD cache 大小是否影响后台文件服务器数量**。

## 实验设计

建 4 个 IT 文件系统，只变 SSD read cache（和配套吞吐档），挂到同一 EC2（lustre-client 2.15.6），用 `lfs df` 看 MDT/OST 数：

| 组 | SSD read cache | 配套吞吐档 | metadata IOPS |
|---|---|---|---|
| g1 | 32 GiB | 4000 MBps | 6000 |
| g2 | 1 TiB (1024 GiB) | 4000 MBps | 6000 |
| g3 | 8 TiB (8192 GiB) | 8000 MBps | 6000 |
| g4 | 16 TiB (16384 GiB) | 12000 MBps | 6000 |

> 注：IT 文件系统的 `MetadataConfiguration.Mode` 必须为 `USER_PROVISIONED`（不接受 AUTOMATIC），需显式给 metadata IOPS。

## 实测结果

| 组 | SSD cache | 吞吐档 (MBps) | MDT 数 | **OST 数** | 单 OST 名义容量 |
|---|---|---|---|---|---|
| g1 | 32 GiB | 4000 | 1 | **1** | ~508 TiB |
| g2 | 1 TiB | 4000 | 1 | **1** | ~508 TiB |
| g3 | 8 TiB | 8000 | 1 | **2** | ~508 TiB |
| g4 | 16 TiB | 12000 | 1 | **3** | ~508 TiB |

（`lfs df` 每个 OST 名义容量都显示 ~508 TiB，是弹性存储的虚拟上限展示值，非实际预置。）

## 分析与推测

1. **OST 数量 ≈ 吞吐档 ÷ 4000**（4000→1, 8000→2, 12000→3）。**与 SSD cache 大小无关**——g1(32GiB) 和 g2(1TiB) 同为 4000 吞吐档，都是 1 个 OST。这与官方性能文档"每 4000 MBps 为一个性能档"的说法一致，**推测每 4000 MBps 吞吐对应后台 1 个 OST/文件服务器**。
2. **MDT 恒为 1**——4 组 metadata IOPS 都配 6000（同一档），都是单 MDT。**推测 MDT 数由 metadata IOPS 档位决定**，与 cache/吞吐无关（本实验未变 metadata IOPS，未验证多 MDT 情形）。
3. **SSD read cache 是独立的缓存层，不影响后台 OSS/MDS 拓扑**——它只决定多少热数据能亚毫秒命中，与文件服务器数量解耦。

## 结论（推测性）

> **在 Intelligent-Tiering 上，后台 OST 数量主要由预置吞吐档（每 4000 MBps 一个）决定，MDT 数量由 metadata IOPS 档决定，SSD read cache 大小不影响后台文件服务器拓扑。**

这是基于 4 组实测的经验推测，AWS 未官方公开此机制，仅供架构理解参考。要精确/权威答案建议咨询 AWS Support。

## 复现命令

```bash
# 建 IT 文件系统(metadata 必须 USER_PROVISIONED)
aws fsx create-file-system --file-system-type LUSTRE --storage-type INTELLIGENT_TIERING \
  --subnet-ids <SUBNET> --security-group-ids <SG> \
  --lustre-configuration '{"DeploymentType":"PERSISTENT_2","ThroughputCapacity":4000,
    "DataReadCacheConfiguration":{"SizingMode":"USER_PROVISIONED","SizeGiB":32},
    "MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":6000}}'
# 挂载后看拓扑
mount -t lustre -o relatime,flock <DNS>@tcp:/<mountname> /mnt/fs
lfs df /mnt/fs      # 看 MDT / OST 条目数
```
