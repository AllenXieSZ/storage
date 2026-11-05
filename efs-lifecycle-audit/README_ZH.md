# EFS 生命周期分层审计工具

## 背景

EFS 支持 Standard / IA / Archive 三级存储自动沉降，但**没有提供按文件查询存储层的 API**——只能通过 `DescribeFileSystems` 拿到各层的总字节数。

本工具通过读取文件的 POSIX `atime`（最后访问时间），结合 EFS 生命周期策略的天数阈值，**推断每个文件所在的存储层**，输出分层文件清单（CSV），并与 EFS API 的各层总量交叉验证。

## 原理

- EFS 默认 NFS 挂载选项为 `relatime`，atime 在文件被读取时按天粒度更新。
- EFS 生命周期管理也是基于"文件在 Standard 层最后被访问的时间"来决定是否沉降。
- 两者语义一致，因此 atime 可以可靠地推断文件的存储层。
- 脚本只调用 `os.lstat()`（读 inode 元数据），**不读文件内容**，因此：
  - ❌ 不产生 IA/Archive 访问费
  - ❌ 不触发 atime 更新
  - ❌ 不触发 TransitionToPrimaryStorageClass 回迁

## 并行架构

主线程通过 `os.walk()` 遍历目录树，每遇到一个目录，将其文件列表按 5,000 个一批分发给 32 个 worker 线程并发执行 `lstat()`。这样不管目录结构是均匀分布还是高度不均衡（比如单个目录 10 万文件），都能充分利用多线程重叠 NFS 元数据请求的往返延迟。

## 实测结果

### 测试环境

- EC2 跳板机：通用型实例（us-east-2a），NFS4.1 挂载
- Workers：32 线程

### 测试 1：小规模 EFS（189 GiB）

| 参数 | 值 |
|---|---|
| 文件系统 | `fs-0e77227a1ecaac809`（Bursting 吞吐） |
| 总容量 | 189 GiB |
| 文件数 | 560,054 |
| 目录数 | 760 |
| 目录结构 | 均匀（100 个顶层子目录，每个 ~5,600 文件） |
| 沉降策略 | TransitionToIA = 1 天 |
| **扫描耗时** | **52 秒** |
| **扫描速度** | **10,788 files/s** |

**分层准确度：**

| 层级 | 脚本推算 | EFS API | 偏差 |
|---|---|---|---|
| Standard | 1.07 GiB | 1.09 GiB | **−1.56%** |
| IA | 187.99 GiB | 187.99 GiB | **+0.00%** |
| Archive | 0 | 0 | — |
| **Total** | **189.06 GiB** | **189.08 GiB** | **−0.01%** |

Standard 层的 1.56% 偏差来自目录 inode 大小估算（脚本按固定 6 KiB/目录近似，实际大小随目录条目数变化）。IA 层精确命中。

**扫描期间 CloudWatch 指标：**

| 指标 | 值 |
|---|---|
| MetadataIOBytes | 峰值 ~25 MB/s，IOPS ~6,142/s |
| PermittedThroughput | 100 MB/s |
| **PercentIOLimit** | **峰值 17.5%** |

→ **EFS 服务端元数据吞吐远未打满**（仅用了不到 1/5），瓶颈在 NFS 客户端的 `lstat` 往返延迟，不在 EFS 侧。

### 测试 2：大规模 EFS（2.33 TiB）

| 参数 | 值 |
|---|---|
| 文件系统 | `fs-027ff9a3e720a5a4e`（Bursting 吞吐） |
| 总容量 | 2.33 TiB |
| 文件数 | 12,407,207 |
| 目录数 | 34,731 |
| 目录结构 | 高度不均衡（10 个子目录 × 10 个子目录 × 10 万文件/叶子目录） |
| 沉降策略 | TransitionToIA = 14 天（曾设过 Archive 策略后删除） |
| **扫描耗时** | **5.5 小时（328 分钟）** |
| **扫描速度** | **631 files/s**（全程稳定） |

**分层准确度：**

| 层级 | 脚本推算 | EFS API | 偏差 | 说明 |
|---|---|---|---|---|
| Standard | 23.86 GiB | 24.44 GiB | **−2.34%** | 目录 inode 近似 |
| IA | 2.31 TiB | 324.27 GiB | — | 见下方说明 |
| Archive | 0 | 1.99 TiB | — | 见下方说明 |
| **Total** | **2.33 TiB** | **2.33 TiB** | **+0.07%** | ✅ |
| **IA + Archive 合计** | **2.31 TiB** | **2.31 TiB** | **+0.00%** | ✅ |

> **IA/Archive 分层说明**：该文件系统之前设过 Archive 策略，后来被删除。已经沉到 Archive 的 1.99 TiB 数据不会自动回迁。由于当前策略没有 Archive 规则，脚本将所有老文件归为 IA。但 **IA + Archive 合计精确吻合**，证明 atime 推断是正确的。如果需要准确的 IA/Archive 分层，传入 `--archive-days` 匹配原始策略即可。

**扫描期间 CloudWatch 指标：**

| 指标 | 值 |
|---|---|
| MetadataIOBytes | 峰值 ~6 MB/s |
| **PercentIOLimit** | **峰值 6.8%** |

→ 大 FS 同样远未打满 EFS 元数据吞吐上限。速度低于小 FS 的原因是该 FS 有大量 10 万文件的扁平叶子目录，`os.walk` 的 `getdents`（列目录）操作是单线程的，成为瓶颈。

## 两组测试对比

| | 小 FS (189 GiB) | 大 FS (2.33 TiB) |
|---|---|---|
| 文件数 | 56 万 | 1,240 万 |
| 目录结构 | 均匀（100 子目录） | 不均衡（10万文件/叶子目录） |
| 扫描速度 | **10,788 files/s** | **631 files/s** |
| 耗时 | 52 秒 | 5.5 小时 |
| Standard 偏差 | −1.56% | −2.34% |
| Total 偏差 | −0.01% | +0.07% |
| PercentIOLimit | 17.5% | 6.8% |
| **EFS 侧是否打满** | **否** | **否** |

**速度差异的根因**：不是 EFS 服务端限制，而是客户端 NFS 协议层面：
- 均匀目录树：32 线程并发 `lstat` 重叠 NFS RTT → 接近线速
- 扁平大目录：`os.walk` 调用 `getdents` 列 10 万条目录项是单线程同步操作 → 成为瓶颈

## 用法

```bash
python3 efs_tier_audit.py \
  --mount /mnt/efs \
  --fs-id fs-0123456789abcdef0 \
  --region us-east-2 \
  --ia-days 30 \
  --archive-days 90 \
  --workers 32
```

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--mount` | EFS 挂载路径 | （必填） |
| `--fs-id` | EFS 文件系统 ID（用于 API 对比） | （必填） |
| `--region` | AWS 区域 | us-east-2 |
| `--ia-days` | TransitionToIA 策略天数 | （必填） |
| `--archive-days` | TransitionToArchive 策略天数（0=无） | 0 |
| `--workers` | 线程池大小 | 32 |
| `--output-dir` | 输出目录 | /tmp/efs-audit |

**输出文件：**

- `standard_files.csv` — Standard 层文件清单
- `ia_files.csv` — IA 层文件清单
- `archive_files.csv` — Archive 层文件清单
- `summary.txt` — 分层统计 + API 对比报告

每个 CSV 包含：`path, size_bytes, atime, age_days`

**依赖**：Python 3.6+，`boto3`（可选，用于拉取 API 对比数据）

## 前提条件

- EFS 挂载时**没有使用 `noatime` 选项**（默认 `relatime` 即可）。验证：`mount | grep efs`
- 如果挂载了 `noatime`，atime 不会被更新，本方法不适用

## 代码

- GitHub: [AllenXieSZ/storage/efs-lifecycle-audit](https://github.com/AllenXieSZ/storage/tree/main/efs-lifecycle-audit)
