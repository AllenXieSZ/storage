# Lustre 集群 RAID1 底层改造 + 容错实测报告

**日期：** 2026-07-18 (Ohio us-east-2a)
**改造目标：** 把 MDT + 全部 4 OST 的底层从裸 EBS 改为 **mdadm RAID1 (EBS+EBS)**
**方案：** 用户选定 —— (1) MDT 和 OST 全部改造；(2) 配对方式 (c) 纯 EBS+EBS RAID1（不用本地 NVMe，实例 stop 数据不丢，最稳）

---

## 改造后架构

| 角色 | RAID1 设备 | 组成盘（都是 gp3） | 有效容量 |
|---|---|---|---|
| MDS: MDT0000 | /dev/md0 | nvme1n1(50G,原) + nvme3n1(50G,新) | 50G |
| OSS1: OST0 | /dev/md0 | nvme1n1(100G,原) + nvme4n1(100G,新) | 100G |
| OSS1: OST1 | /dev/md1 | nvme2n1(100G,原) + nvme5n1(100G,新) | 100G |
| OSS2: OST2 | /dev/md0 | nvme1n1(100G,原) + nvme4n1(100G,新) | 100G |
| OSS2: OST3 | /dev/md1 | nvme2n1(100G,原) + nvme5n1(100G,新) | 100G |

- 新增 5 块 gp3 EBS（1×50G + 4×100G）做镜像半边
- 容量以小盘为准（两块同尺寸，RAID1 有效容量=单盘）
- mdadm metadata=1.2，`/etc/mdadm.conf` 已持久化，`/etc/fstab` 改为挂 `/dev/mdX`

## 改造流程（重建方式，非原地改）
1. 卸载 client → 卸载 4 OST → 卸载 MDT（空测试集群，数据清空 OK）
2. 三台装 mdadm，`mdadm --create --level=1` 建 5 个 RAID1 阵列
3. 在 `/dev/mdX` 上重新 `mkfs.lustre`（MDT --mgs --mdt index0；OST index 0-3）
4. 按序挂载 MDT→OST→client，4 OST 全部 ACTIVE，390G 总容量恢复
5. 更新 fstab + mdadm.conf 持久化

## RAID1 容错实测（核心验证）

**新增 EBS volume-id（便于清理）：**
`REDACTED`(MDT-m) `REDACTED`(OST0-m) `REDACTED`(OST1-m) `REDACTED`(OST2-m) `REDACTED`(OST3-m)

**测试步骤：**
1. 写 20×10MB 文件强制落 OST0（其 RAID1 = OSS1 md0），记录 md5
2. **在线拔盘**：`mdadm /dev/md0 --fail /dev/nvme4n1` → 阵列变 `[2/1] [U_]`（降级，一块盘挂）
3. 降级状态下测试 I/O：
   - **读回 20 文件 md5 校验：OK=20, FAILED=0** ✅ 数据完好
   - **降级状态下写新文件到 OST0：成功** ✅
   - OST0 **始终 ACTIVE**，文件系统完全无感知
4. **换盘恢复**：`--remove` → `--zero-superblock` → `--add` → RAID1 自动 rebuild（recovery ~137MB/s）→ 回到 `[UU]`

## 核心结论（实测支撑）

| 对比项 | 无 RAID（之前测试） | RAID1 改造后（本次） |
|---|---|---|
| 单盘/单介质故障 | OST 掉线，该 OST 上文件**不可访问** | **文件系统无感，读写不中断** ✅ |
| 数据是否可读 | OST 下线期间读不了 | **全程可读，md5 全过** ✅ |
| 新写入 | 需标 inactive 才绕开 | **降级状态直接照常写** ✅ |
| 恢复 | OST 恢复后才可读 | **换盘热重建，业务不停** ✅ |

**RAID1 把"单盘故障→数据不可用"变成了"单盘故障→业务无感知"。** 这是底层冗余相对 Lustre 单份数据的关键提升。

⚠️ **注意事项：**
- RAID1 只防**单盘故障**，不防整台 OSS 实例挂（那需要 OST failover / 共享盘）。
- 空间成本翻倍（每 OST 两块 EBS）。
- 选 (c) 纯 EBS 方案：实例 stop/start 数据不丢（未用本地 NVMe）；那块 1.7T 本地 NVMe 仍闲置。

## 成本提示
现在集群 EBS 从 5 块变 10 块（gp3）。不用时 stop 实例（EBS 数据保留）；彻底删除需 terminate 4 实例 + 删除新增的 5 块 mirror 卷。
