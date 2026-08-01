# AWS FSx for Lustre vs GCP Managed Lustre 对比（含对象存储数据流转机制查实）

**整理日期**：2026-08-01
**数据来源**（均为官方文档，2026-08）：
- AWS：FSx for Lustre User Guide（performance / ssd-storage / managing-throughput-capacity / DRA-HSM 相关页）
- GCP：Google Cloud Managed Lustre docs（overview / performance-tiers / performance / transfer-data）
- DDN：ddn.com 官网 + press releases

> 说明：GCP Managed Lustre 由 **DDN**（DataDirect Networks，Lustre 商业化头号厂商 EXAScaler 的东家）合作开发；AWS FSx for Lustre 为 AWS 自研、基于开源 Lustre 封装。

---

## 0. 最本质差异（TL;DR）

| 维度 | AWS FSx for Lustre | GCP Managed Lustre (DDN) |
|---|---|---|
| 技术来源 | AWS 自研 + 开源 Lustre | DDN EXAScaler 商业 Lustre |
| 吞吐性质 | **burst/baseline 双档**（credit 机制，会衰减） | **sustained 恒定吞吐**（官方定位，无衰减） |
| 对象存储集成 | **HSM 惰性加载**（DRA，released/restore） | **批量全量传输**（import-data/export-data） |
| 元数据 IOPS | **可独立预置**（1500~192000） | 随容量+吞吐自动伸缩，不可独立调 |
| 单FS上限 | 多 TBps | **10 TBps / 80.1 PiB** |

---

## 1. 对象存储数据流转机制（核心差异，已查实）★

**这是两家最本质的分水岭。**

### AWS FSx —— DRA + HSM 惰性加载（lazy load）
- **DRA（Data Repository Association）** 持久关联 S3：
  - **import**：只导入**元数据**（文件名/大小/权限），文件在 Lustre 标记 `released`（占位，数据仍在 S3）。实测 2000万文件 import ≈ 2762 files/s。
  - **按需 restore**：客户端首次读文件时，才从 S3 惰性拉取实际数据（HSM restore）。
  - **preload/warmup**：可主动 `lfs hsm_restore` 预拉热数据。
  - **release**：数据写回 S3 后可 `lfs hsm_release` 释放本地空间，只留占位。
  - **export**：AutoExportPolicy 自动/手动写回 S3。
- **特点**：PB 级 S3 数据集，Lustre 只需放热数据；元数据秒级挂载，按需取用，可释放空间。
- **代价**：首次访问有 restore 延迟（冷启动慢，需 warmup 预热）。

### GCP Managed Lustre —— 批量全量传输（bulk copy）
- 官方命令：`gcloud lustre instances import-data` / `export-data`。
- **增量传输**："only copy files that don't already exist or have changed"（类 rsync）。
- **无 HSM / released / 惰性加载概念**：import 就是**把数据真实搬进 Lustre**（占容量），不是占位。
- **无 release**：不能"元数据留着、数据放回 GCS 省空间"。
- 传输性能：>32MB 文件最高 **100 GBps**（受实例吞吐上限限制）；GCS **hierarchical namespace (HNS)** bucket 更快。
- **非持久关联**：手动触发 import/export，非实时自动同步。
- **代价**：Lustre 容量必须 ≥ 数据集；import 要等全量拷完。好处：拷完后本地访问零延迟、无 restore 抖动。

### 实操对照

| 操作 | AWS FSx | GCP Managed Lustre |
|---|---|---|
| 关联对象存储 | 建 DRA（持久，可 auto import/export） | 无持久关联，手动 import-data/export-data |
| 导入千万级文件 | 仅导元数据（released 占位），秒级建树 | 全量拷数据进来（占容量，受吞吐限制） |
| 首次读文件 | 从 S3 惰性 restore（有延迟） | 已在本地（import 时已拷），无延迟 |
| 预热 preload | `lfs hsm_restore` 主动预拉 | 不需要（import 即全拉） |
| 释放空间 | `lfs hsm_release`（留占位，数据回 S3） | 无此能力 |
| 自动同步 | AutoImport/AutoExport Policy | 手动增量 import/export |

**选型启示**：
- 数据集 >> 计算集群容量 / 要省钱 → **AWS DRA/HSM**（6PB 在 S3，Lustre 只开 TB 级放热数据）。
- 数据集能全装进 Lustre / 要训练零抖动 → **GCP 批量传输**（先 import 全量，训练全程本地读，但 Lustre 得开够大）。

---

## 2. 吞吐机制

| | AWS FSx | GCP Managed Lustre |
|---|---|---|
| 档位 | 125/250/500/1000 MBps/TiB（PERSISTENT_2） | 125/250/500/1000 + Dynamic(25) MBps/TiB |
| 吞吐性质 | **burst/baseline 双档**（network I/O credit，攒→用→耗尽回落基线） | **sustained, predictable, consistently delivered**（恒定，官方定位无衰减） |
| 实测（AWS） | PERSISTENT-125 @4.8TiB：burst 1600+ MB/s → 耗尽落基线 ~600 MB/s（=125×4.8）| 未实测 |
| 单FS最大吞吐 | 多 TBps | 10 TBps |
| 最大容量 | PB 级 | 80.1 PiB |

⚠️ **对持续满载 AI 训练**：AWS 有 burst 衰减（稳态须按 baseline 规划，已实测证实）；GCP 官方强调恒定吞吐无衰减（设计上更友好，但本文未对 GCP 做实测验证）。

---

## 3. 扩容与变配

| | AWS FSx | GCP Managed Lustre |
|---|---|---|
| 在线改吞吐 | 支持，但换文件服务器→**OST 断连 ~100s**（已实测）+ **6h 最小间隔** + 最长 1h 不可用 | 增容量即提升吞吐/IOPS |
| 扩容后性能 | — | **写吞吐立即提升，读吞吐随数据重分布逐渐提升** |
| 扩容限制 | 24h 内有限次数 | **step size 门槛**：首次建在小 step 范围则不能超阈值扩 |
| 90% 容量 | — | **利用率 ≥90% 性能下降**（官方警告） |

（AWS 变配 IO 影响详见同仓库 `fsx-lustre-throughput-change/`。）

---

## 4. 元数据性能

| | AWS FSx | GCP Managed Lustre |
|---|---|---|
| 元数据 IOPS | PERSISTENT_2 **可独立预置** 1500~192000 | 随容量+吞吐**自动伸缩**，不可独立调 |
| 折算 | 每 1 IOPS：create/open 2、delete 1、dir create 0.1、dir delete 0.2 | 每 72GBps 吞吐：41万 stat/s、11.5万 create/s、9.5万 delete/s，最高 22×base |

海量小文件场景（如千万级）：**AWS 可单独砸钱堆元数据 IOPS 更灵活**；GCP 元数据绑吞吐容量，粒度粗但省心。

---

## 5. 性能上限 / 规格

| 指标 | AWS FSx | GCP Managed Lustre |
|---|---|---|
| 读 IOPS | network IOPS/TiB（数万 baseline，数十万 burst） | 5,800 read IOPS/TiB |
| 写 IOPS | 同上 | 5,600 write IOPS/TiB |
| 单文件最大 | — | 0.5 PiB |
| 客户端优化 | EFA + Lustre（同 AZ 硬约束，见 fsx-lustre-efa-diag/） | MTU 8896 提升~10%、multi-NIC multi-rail、C3+Tier_1 200Gbps |

---

## 6. 应用场景总结（面向 6PB AI 预训练）

**选 AWS FSx for Lustre：**
- 数据在 S3、要 HSM 惰性加载（数据集 >> 集群容量，省钱）
- 海量小文件、需独立堆元数据 IOPS
- 需要 scratch 临时集群
- 接受 burst 衰减（按 baseline 规划）+ 变配 ~100s IO 中断

**选 GCP Managed Lustre (DDN)：**
- 数据在 GCS
- 持续满载 AI 训练（恒定吞吐设计，无衰减）
- 超大规模（80PiB/10TBps 上限更高）
- 数据集能全装进 Lustre（import 后本地零抖动）
- 接受：元数据不能独立调、容量 step 门槛、90% 降速

---

## 7. 仍未实测/待验证（诚实标注）

1. GCP 是否**真的完全无吞吐限流**——官方称 sustained，但未做 GCP 侧实测（AWS burst 衰减已实测）。
2. 两家**实际价格**（未查 pricing）。
3. GCP 变配/维护对在线 IO 的影响（AWS 已实测 ~100s OST 断连，GCP 未测）。

---

*配合 24h Lustre 压测与吞吐变配实验整理。相关：`fsx-lustre-throughput-change/`、`fsx-lustre-efa-diag/`、`fsx-lustre-warmup/`。*
