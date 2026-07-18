# Lustre OST 故障容错测试报告

**日期：** 2026-07-18 (Ohio us-east-2a)
**集群：** 自建 Lustre 2.15.8，1 MDS + 2 OSS(各2 OST) + 1 Client，4 OST 全 gp3
**测试目的：** 写 100×10MB 文件分散到各 OST → 模拟一个 OST 坏掉 → 验证 Lustre 是否正常运行、数据能否正常读写

---

## 测试步骤与结果

### 1. 写入 100 个 10MB 文件，均匀分散到 4 个 OST
- 用 `lfs setstripe -c 1 -i <ost>` 强制 round-robin，每文件落单个 OST
- **实测分布：OST0=25, OST1=25, OST2=25, OST3=25**（完美均衡，共 800MB）
- 保存全部 100 个文件 md5 供后续完整性比对
- ⚠️ 坑：`lfs getstripe -m` 返回的是 **MDT index（恒为0）**，不是 OST！查文件在哪个 OST 要解析 `obdidx` 行（`lfs getstripe <f> | awk '/obdidx/{f=1;next} f&&NF{print $1;exit}'`）。一开始误用 -m 以为全压 OST0，其实早就均衡了。

### 2. 模拟 OST0 故障（在 OSS1 上 umount OST0）
- OST0 物理在 OSS1，`umount /mnt/ost0` 模拟设备/服务挂掉
- 客户端立即感知：`lfs osts` 里 OST0 → **DISCONN**（disconnected）
- MDT 侧：OST0 `prealloc_status=-19`(ENODEV)，但 `active=1`（默认进入**recovery 等待**，期待 OST 回来）

### 3. 【关键发现】OST 刚掉、未标 inactive 时：写操作会 D 状态挂死
- 默认行为下，写新文件若分配到掉线的 OST0 → 进程进**不可中断睡眠(D state)**，`timeout` 都 kill 不掉，一直等 OST 恢复。
- 这是 Lustre 默认设计：OST 掉线先当"临时故障"等恢复，不立即报错。
- **正确运维动作**：确认 OST 永久故障后，手动标记 inactive：
  ```
  # MDS 上（停止在该 OST 分配）
  lctl set_param osp.lustrefs-OST0000-osc-MDT0000.active=0
  # 客户端上（读该 OST 快速失败而非挂起）
  lctl set_param osc.lustrefs-OST0000-*.active=0
  ```

### 4. OST0 标记 INACTIVE 后的完整测试矩阵
| 操作 | 结果 | 说明 |
|---|---|---|
| 读健康 OST2 的 25 文件 | **OK=25 / FAIL=0** | 不受影响，正常读 ✅ |
| 读故障 OST0 的 25 文件 | **OK=0 / FAIL=25** | 快速失败(I/O error)，不再挂死 ✅ 符合预期 |
| 写 10 个新文件 | **全部成功**，落 OST1=3/OST2=4/OST3=3 | **Lustre 自动绕开死掉的 OST0** ✅ |
| `lfs df` / 文件系统 | 正常 | FS 整体在线，用 3 个健康 OST 继续服务 ✅ |

### 5. OST0 恢复（remount + reactivate）后数据完整性
- OSS1 重新 `mount -t lustre /dev/nvme1n1 /mnt/ost0` → OST0 回 ACTIVE
- MDS/客户端 `active=1` 重新激活
- **完整性校验：`md5sum -c` 100 个文件 → PASSED=100, FAILED=0**（bit-for-bit 全部完好）
- （刚 reactivate 瞬间有 3 个文件读失败，是客户端到 OST0 的连接还在重连中的竞态；稍后权威 md5 校验 100/100 全过）

---

## 核心结论（均有实测支撑）

1. **单 OST 故障不会导致整个文件系统宕机** —— Lustre 用剩余健康 OST 继续正常读写。✅
2. **不在故障 OST 上的文件完全不受影响**，正常读写。✅
3. **落在故障 OST 上的文件在 OST 下线期间不可访问**（无副本机制——Lustre 本身不做数据冗余，冗余靠底层 RAID/EBS）。OST 恢复后数据**完好无损**。✅
4. **新写入自动绕开故障 OST**（前提：把故障 OST 标 inactive）。✅
5. **⚠️ 运维要点**：OST 掉线后必须手动标 `active=0`，否则命中该 OST 的 I/O 会 D 状态挂死等恢复；标 inactive 后读故障文件才会快速报错、写才会绕开。
6. **数据可靠性依赖底层存储**：Lustre 无内建副本，OST0 的数据靠 EBS gp3 的持久性保证；OST"回来"数据就在。真要防单点，需 OST 层做 failover（共享盘 + servicenode）或底层 RAID。

**测试文件已清理，集群恢复到 4 OST 全 ACTIVE 健康状态。**
