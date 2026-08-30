# 为什么快慢差这么多：元数据操作 vs 物理资源操作

> FSxN ONTAP 几类扩容/转换操作的耗时差异原理。基于 NetApp/AWS 官方文档 + 实测。
> ⚠️ 官方原文见文末来源；实测数据来自本仓库实验（2026-08-28~29）。

## 一句话原理
- **改元数据（贴标签/改指针）→ 秒级**：FlexVol→FlexGroup 转换、volume expand 加成员。
- **动物理资源（起服务器/换实例/搬数据）→ 分钟~小时级**：升 throughput、加 HA pair、volume move。

## 对比总表

| 操作 | 底层动作 | 是否搬数据 | 实测耗时 | 测试次数 |
|---|---|---|---|---|
| FlexVol→FlexGroup 转换 | 改卷类型元数据（FlexGroup=多FlexVol成员的逻辑命名空间，FlexVol≈单成员）| ❌ 不搬 | **< 1 min** | 2 次(干净卷,均成功) |
| volume expand 加 constituent | 在别的 aggregate 挂新空成员卷（元数据）| ❌ 不搬(老数据不回迁) | **< 1 min** | 多次 |
| 升 throughput (384→1536) | 后台换更大规格文件服务器实例(无缝切换) | ❌ 数据不动/换实例 | **~36–44 min** | 2 次 |
| 加 HA pair (1→2) | 真起一对新物理文件服务器 + 新 aggregate | ❌ 数据不动/起真硬件 | **~10–26 min**(官方称"几分钟") | 2 次 |
| volume move (用上新HA) | 真搬整卷物理数据到新 aggregate | ✅ 真搬 | **1h54m49s**(1TB热卷,fio活跃时前22min仅4%,停fio后剩余~1h32m) | **1 次** |

## 原理详解

### 为什么转 FlexGroup / expand 秒成
- FlexGroup 本质 = 多个 FlexVol(constituent 成员卷)拼成一个逻辑命名空间；一个 FlexVol ≈ 只有 1 个成员的 FlexGroup。
- 转换只是把该 FlexVol 在 ONTAP 元数据里重新登记为"单成员 FlexGroup"——WAFL 物理数据块原地不动、一个不搬。
- NetApp 官方：ONTAP 9.7+ 支持 in-place conversion，**不需复制数据、不需额外磁盘空间**。
- expand 加成员 = 在别的 aggregate 建空成员卷挂进来，新数据才按文件名 hash 往里落，老数据不回迁 → 也秒级。

### 为什么加 HA / 升吞吐慢
- 加 HA pair = AWS 后台真 provision 一对新物理文件服务器(active/passive HA) + 新 SSD aggregate + 接入集群 → 起真实硬件,天然慢几个量级。
- 384MB/s 的 1HA 不能直接扩 2HA(2HA 最低 1536)→ **必须先升 throughput 384→1536**(换更大实例, ~40min, 是耗时大头), 再扩 HA。
- ⚠️ 官方称加 HA "typically takes only a few minutes";实测 10–26min,差异属 AWS 后台资源编排(实例可用性/负载),无法精确预测。
- **⭐ 加完 HA,老数据不自动迁到新 HA pair**;官方明确"需手动 volume move 卷到新 HA pair 才能用上新性能"。

### 为什么 volume move 最慢(小时级)
- volume move = 真把整卷物理数据从一个 aggregate 搬到另一个(100:0→0:100),不是均衡分布,只是换存放位置。
- 让位客户 I/O:热卷(fio 活跃)时严重限速,实测前 22min 仅完成 4%;停 fio 后剩余 96% 用 ~1h32m。
- 只测过 1 次,无"平均值"。

## 来源
- FlexVol→FlexGroup 原地转换不搬数据: NetApp docs.netapp.com/us-en/ontap/flexgroup/convert-flexvol-concept.html
- 加 HA=新建文件服务器+aggregate、老数据需手动迁移、官方称"几分钟": AWS docs.aws.amazon.com/fsx/latest/ONTAPGuide/adding-HA-pairs.html
- 实测耗时: 本仓库实验(commit e83567a / b4ad096 / fb9c235)
