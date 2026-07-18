# Lustre RAID1 —— 情况2 真实在线换盘 + fio 持续负载 + 重建计时报告

**日期：** 2026-07-18 (Ohio us-east-2a)
**场景：** 情况2（真实换盘）—— 创建全新 EBS 卷替换故障盘，全程 fio 持续 I/O，测量重建耗时到 healthy

---

## 测试对象
- 换 **OSS1 的 OST0**（/dev/md0 = nvme1n1[主] + nvme4n1[镜像]）的**镜像半边**
- 被换旧盘：`REDACTED`（真实 detach+delete，模拟盘彻底坏掉）
- 新替换盘：`REDACTED`（全新 create 的 100G gp3）→ 挂载后 = /dev/nvme6n1

## 操作流程（全程 fio randrw 打在 OST0 上）
1. **启动 fio**：4 jobs randrw 50/50，64k，direct，iodepth16，time_based 1200s，数据全 pin 在 OST0
2. **create 新 EBS** `vol-02d1...`（100G gp3）→ attach 到 OSS1 /dev/sdh → /dev/nvme6n1
3. **拔旧镜像盘**：`mdadm --fail nvme4n1` + `--remove` → 阵列降级 `[2/1] [U_]`，**fio 不中断继续跑**
4. **真删旧盘**：`aws ec2 detach-volume` + `delete-volume`（旧盘物理消失）
5. **加新盘**：`mdadm /dev/md0 --add /dev/nvme6n1` → 触发 rebuild，**开始计时**
6. 监控 `/proc/mdstat` 到 `[UU]`

## 重建耗时实测（核心数据）

| 阶段 | rebuild 速度 | 说明 |
|---|---|---|
| **默认限速下（前 ~8min）** | **~17-18 MB/s** | `speed_limit_min=1000`(KB/s)，mdadm 把带宽让给 fio 应用 I/O，重建被压到极慢，ETA 一度显示 ~95min |
| **提高 speed_limit_min 后** | **~124 MB/s** | `echo 200000 > /proc/sys/dev/raid/speed_limit_min` 让重建优先，速度飙 7 倍，ETA 降到 ~12min |
| **总耗时（add→healthy）** | **1210 秒 (~20min)** | 含前段慢 + 后段快；100GB 镜像盘 |

**关键结论：**
- **重建速度默认会让位给应用 I/O**（`speed_limit_min` 默认仅 1000 KB/s）。有负载时重建极慢（17MB/s，100GB 要 ~95min）。
- **调 `speed_limit_min` 可强制优先重建**：拉到 200000 后达 124MB/s（接近 gp3 单盘吞吐上限），~12min 重建完 100GB。
- 纯空闲重建（上次无负载测试）也是 ~137MB/s——说明**瓶颈是 gp3 单盘吞吐(~125MB/s)，不是 RAID 本身**。
- **权衡**：重建快 = 抢应用带宽（fio 延迟飙升，p95 从常态几十ms 飙到 592ms）；重建慢 = 应用流畅但降级窗口长（风险期长）。生产需按业务容忍度调 speed_limit。

## fio 全程表现（贯穿降级+重建+恢复，1200s）
- **读 418,838 次 / 写 419,065 次，dropped=0，零 I/O 错误** ✅
- 累计读 27.4GB + 写 27.5GB，全程 **无中断、无报错**
- 带宽被重建挤压：稳态本应 ~500MB/s（4×gp3），实测降到 **~22MB/s**（重建抢盘 + 降级期单盘服务）
- 延迟受影响：p50=36ms，p95=592ms，max=2675ms（重建高优先级时应用 I/O 排队）
- **但业务全程可用,一个 I/O 都没失败** —— 这是 RAID1 在线换盘的核心价值

## 情况2 vs 情况1 区别（回答伟伟的问题）
- **情况1（上次）**：`--fail` 人为标坏 → `--zero-superblock` → `--add` **同一块盘**，不建新 EBS，纯验证重建链路。
- **情况2（本次）**：**真 create 新 EBS** → attach → 加入阵列，旧盘真 detach+delete。这是生产环境真换坏盘的完整流程。

## 最终状态
- md0 = nvme1n1 + **nvme6n1(新盘)** → `[UU]` healthy ✅
- 5 个阵列全部 `[UU]`，集群 4 OST ACTIVE
- speed_limit_min 已复位为 1000，mdadm.conf 已刷新
- 旧盘 vol-0f60... 已删除；当前 OST0 镜像盘 = REDACTED
