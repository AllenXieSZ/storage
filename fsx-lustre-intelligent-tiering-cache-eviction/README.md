# FSx for Lustre Intelligent-Tiering SSD Read Cache 淘汰算法实测

通过实验推断 Amazon FSx for Lustre **Intelligent-Tiering** 存储类的 **SSD read cache 淘汰算法**。

> ⚠️ AWS 官方文档**未公开**该淘汰算法。本结论为**实测推断**，非官方声明。

## 结论：近似 LRU（Least Recently Used），不是 FIFO

反复访问可以让"最早写入"的数据**免于被淘汰**——去留由**访问新近度/频率**决定，与写入（进入 cache）顺序无关。这是 LRU 的定义特征；FIFO 不会因为数据被频繁读取而保护它。

## 测试环境

| 项目 | 配置 |
|---|---|
| 文件系统 | FSx for Lustre，Intelligent-Tiering，4000 MBps，PERSISTENT_2 |
| SSD read cache | **32 GiB**（USER_PROVISIONED，最小值） |
| metadata IOPS | 6000（USER_PROVISIONED） |
| 客户端 | AL2023 c5n.4xlarge，lustre-client 2.15.6 |
| 数据集 | 60 个 1 GiB 文件（file01–file60），远超 32 GiB cache |

## 判读原理

- 官方文档：cache 命中 = sub-millisecond；未命中（回落 Intelligent-Tiering 存储）= 数十毫秒。
- 实测中命中 ≈ **480 μs**，未命中（被淘汰）≈ **700 μs**（单块 4k 冷读延迟差约 1.5×，稳定可分辨）。
- 用"是否还在 cache（快） vs 已被淘汰（慢）"反推淘汰策略。

## 关键实验数据

**实验 A（反复读 file01/02，即最早写入的文件，各 12 遍；再读 file10–60 挤爆 cache）：**

| 文件组 | 说明 | 中位冷读延迟 | 是否在 cache |
|---|---|---|---|
| file01 / file02 | 最早写入 + 反复读 12 遍 | 479 / 515 μs | ✅ 在（快） |
| file05 / file06 | 早期写入，未反复读 | 706 / 717 μs | ❌ 已淘汰（慢） |
| file59 / file60 | 最新读过 | 708 / 703 μs | ❌ 已淘汰（慢） |

延迟分布完全不重叠（快组 p75 < 慢组 p25），统计显著（每文件 50 次采样）。

**实验 B（交叉验证：改为反复读 file30/31，即中间写入的文件）：**

| 文件组 | 说明 | 中位冷读延迟 |
|---|---|---|
| file30 / file31 | 本轮反复读 12 遍 | 482 / 484 μs（快） |
| file10 / file11 | 从未反复读 | 699 / 707 μs（慢） |

→ 换一个反复读的目标，变快的就是被反复读的那个。**去留由访问频率决定，与写入顺序无关 → LRU。**

## 判读逻辑

- **若为 FIFO**：file01/02 是最早进 cache 的，应最先被淘汰（变慢）。但反复读后它们最快 → 排除 FIFO。
- **若为 LRU**：频繁访问的数据被保留，不常访问的被淘汰。实验 A、B 均符合 → 支持 LRU（或近似 LRU，如 LRU-K / CLOCK）。

## 测量方法学（踩坑记录，供复现）

前 5 轮方法失败，最终有效方法如下：

1. ❌ **fio 持续 randread 测不出差异**：fio 的持续随机读会触发预取/内部命中，把所有文件的延迟拉平（实测全部 ≈ 1676 μs），完全分辨不出 cache 命中与否。
2. ❌ **客户端 `lctl get_param osc.*.stats`（read_bytes）无效**：客户端只能看到"从 OST 读"，无法区分服务端是命中 SSD cache 还是回落到 IT 存储，两者对客户端都是一次 OST 读。
3. ❌ **CloudWatch `DiskReadBytes` / `DiskReadOperations` 对 Intelligent-Tiering 无数据**（返回 None），只有 `DataReadBytes` 有值 → 无法用它判断后端实际读取。
4. ✅ **有效方法 = 单块冷读延迟 + 大样本统计**：
   - `dd if=<file> of=/dev/null bs=4k count=1 skip=<随机偏移> iflag=direct`
   - 每次读前 `sync; echo 3 > /proc/sys/vm/drop_caches`（清客户端 page cache）
   - 每个文件采样 40–50 次，取中位数/分位数压噪声
   - cache 命中 ≈ 480 μs vs 淘汰 ≈ 700 μs，差异稳定可判读。

## 复现步骤

1. 建 FSx Lustre Intelligent-Tiering（4000 MBps，SSD read cache 32 GiB USER_PROVISIONED）。
2. 写 60 个 1 GiB 文件。
3. 顺序读 file01–60 填充 cache。
4. 反复读目标文件（如 file01/02）各 12 遍，使其"最近频繁访问"。
5. 读其余文件挤爆 32 GiB cache（不碰目标文件）。
6. 对各组文件做单块 4k 冷读延迟采样（40–50 次），对比中位数。
7. 交叉验证：换一个反复读目标，重复步骤 3–6。

---
测试日期：2026-08-20 | 方法：单块 dd 冷读延迟 + 大样本统计 | 结论性质：实测推断
