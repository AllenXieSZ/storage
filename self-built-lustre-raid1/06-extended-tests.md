# Lustre RAID1 换盘扩展测试（换主盘 / 大盘容量scaling / systemd坑）

**日期：** 2026-07-18 (Ohio us-east-2a)，接续 RAID1_DISK_REPLACE_TEST.md

## ① 换主盘 nvme1n1（vs 换镜像盘）—— 结论：无区别

- 换 OSS1 md0 的**主盘** nvme1n1（旧 REDACTED...，真 detach+delete；新 REDACTED）
- fio randrw 全程持续，speed_limit_min 从头拉到 200000
- **重建 = 843 秒 (~14min)**，全程 ~124MB/s，fio 零错误
- **关键结论：RAID1 两个成员是对等 peer，无真正"主/从"之分**。拔 nvme1n1 后剩 nvme6n1 继续服务（阵列显 `[_U]`），新盘从存活盘重建，行为与换镜像盘完全一致。

## ② 换更大的盘（500G）—— 重建时间随容量线性增长

- 概念澄清（重要）：RAID1 是**块级镜像**，重建复制的是**整个阵列容量的块**，与盘上实际数据量无关；且阵列容量由**较小成员**决定。所以"往 100G 阵列塞 500G 盘"重建仍只同步 100G。
- 要测"容量→重建时间"必须建**真正的大阵列**：独立建了个 500G RAID1（2×500G gp3，不碰生产 OST）实测。
- **实测重建速度稳定 ~118MB/s**（预热后），与 100G 阵列的 ~124MB/s 基本一致 → **重建吞吐是常量（gp3 单盘 ~120MB/s 上限决定），总时间随容量线性增长**：
  - 100G 阵列 → ~14min（843s 实测）
  - 500G 阵列 → **~70min**（118MB/s 稳定速率外推，跑到 6.8% 验证速率后清理停费用）
- **坑：新建 EBS 首次访问慢（EBS first-touch/初始化）**。500G 盘重建头 1-2 分钟只有 4-8MB/s，逐渐爬到 118MB/s。这是全新 gp3 卷块首次读写的初始化惩罚，非 RAID 问题。

## ③ 【重要坑】systemd generated mount unit 绑定旧设备，导致 OST 反复自动 umount

**现象：** 换盘测试后，OST0 在 client 端 DISCONN，`lfs df` 卡住。OSS1 上 OST0 一 mount 就在 5 秒内 "Failing over → server umount complete" 无限循环，即使 reformat 也不行。

**排查弯路：** 先怀疑数据损坏(reformat无效)→ MMP → index 冲突(--replace 重格)→ 都不是。最后在 `systemctl status mnt-ost0.mount` 找到铁证：
```
mnt-ost0.mount: Unit is bound to inactive unit dev-nvme1n1.device. Stopping, too.
Unmounting /mnt/ost0...
```

**根因：** RAID1 改造时 fstab 已改成 `/dev/md0`，但**没 `systemctl daemon-reload`**，systemd 的 generated mount unit `mnt-ost0.mount` 仍绑定**旧设备 /dev/nvme1n1**。换盘测试把 nvme1n1 删了 → systemd 检测到 `dev-nvme1n1.device` inactive → **自动把 /mnt/ost0 卸载**。每次手动 mount 到 /mnt/ost0 都被 systemd 秒卸。

**验证：** mount 到**非 fstab 路径** /mnt/ost0_new → OST0 稳稳挂住不掉 → 坐实是 systemd 单元冲突，不是 Lustre/磁盘问题。

**修复：**
1. 确认 fstab 是 `/dev/md0`（改造时已改对）
2. `systemctl daemon-reload`（让 systemd 重读，单元绑定到 md0）
3. 重新 mount /mnt/ost0 → 稳定挂住 ✅
4. **三台服务器全部 daemon-reload**，防止其它 OST 重启后重演

**教训（写进运维铁律）：改 fstab 换设备后必须 `systemctl daemon-reload`**，否则 systemd generated mount unit 仍绑旧设备，旧设备一没就自动卸载挂载点。这在"换盘/换设备名"场景是隐形炸弹。

## 最终状态（已恢复健康）
- 5 个 RAID1 阵列全 `[UU]`；4 OST 全 ACTIVE；389.5G；client `lfs df` 正常；4 OST 实测 write+read 全 OK
- 500G 测试卷已删（停费用）；换盘产生的旧卷 vol-0319.../vol-0abd... 已删
- 当前 OSS1 md0 = nvme4n1 + nvme6n1（两块都是换盘后的新卷）
- 三台已 daemon-reload
