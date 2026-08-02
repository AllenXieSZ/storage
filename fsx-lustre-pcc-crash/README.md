# FSx for Lustre + PCC 高压 IO 触发客户端内核崩溃（kdump 确诊）

**测试日期**：2026-08-02
**客户端**：EC2 i7i.4xlarge，Amazon Linux 2023，kernel **6.18.38-76.139.amzn2023.x86_64**，lustre-client 2.15.6
**文件系统**：FSx for Lustre PERSISTENT_2，4.8TiB（脱敏 FS-ID）
**PCC 缓存盘**：本地 NVMe（nvme1n1）ext4，挂 /mnt/pcc_nvme

---

## 结论速览（kdump vmcore 铁证，非推测）

- **可复现**：配置 Lustre PCC-RW 后，对 /fsx 高并发 direct IO（文件命中 PCC autocache → 重定向到本地 NVMe），**客户端内核崩溃（NULL 指针），机器硬重启**。共复现 3 次。
- **鉴别实验证明是 PCC 特有**：
  | 场景 | 结果 |
  |---|---|
  | 纯 Lustre 压测（20h，无 PCC） | ✅ 不崩 |
  | 纯本地 NVMe ext4 高并发 direct IO（无 PCC/Lustre） | ✅ 不崩（341K IOPS/45s） |
  | **PCC-RW + /fsx 高压 direct IO** | ❌ **崩（3/3 复现）** |
- **崩溃点（kdump 内核栈）**：`iomap_dio_bio_end_io → queue_work_on → __queue_work` 空指针，发生在 NVMe direct IO 完成中断路径。
- **判断**：PCC 把 Lustre 文件 IO 重定向到本地 NVMe（iomap direct IO）时，触发了 kernel 6.18 `iomap`/NVMe 中断完成路径的空指针 bug。**单独 Lustre 或单独 NVMe direct IO 都不崩，唯独 PCC 把两者交织时崩。**
- **生产建议**：**托管 FSx for Lustre 不建议启用 PCC**（AWS 官方文档无 PCC 章节，属未验证路径）；此 kernel 版本 + PCC + direct IO 组合有内核崩溃风险。

---

## kdump 捕获的内核崩溃栈（脱敏）

```
BUG: kernel NULL pointer dereference, address: 0000000000000100
Oops: 0000 [#1] SMP NOPTI
CPU: 11 UID: 0 PID: 0 Comm: swapper/11  Not tainted 6.18.38-76.139.amzn2023.x86_64
Hardware name: Amazon EC2 i7i.4xlarge
RIP: 0010:__queue_work+0x1c/0x3c0
Call Trace <IRQ>:
  queue_work_on+0x4a/0x60
  iomap_dio_bio_end_io+0x50/0x80        <-- direct IO 完成回调
  blk_mq_end_request_batch+0x10a/0x550
  nvme_irq+0x8b/0xa0                     <-- NVMe 中断
  __handle_irq_event_percpu+0x51/0x240
  handle_irq_event / handle_edge_irq / common_interrupt
Modules linked in: ... mgc lustre mdc fid lov osc lmv fld ksocklnd ptlrpc obdclass lnet ... libcfs ...
CR2: 0000000000000100
```

**解读**：CPU 在 idle（`swapper/11`）时被 NVMe 中断打断，在处理 direct IO 完成（`iomap_dio_bio_end_io`）时调用 `queue_work_on → __queue_work`，对空指针（address 0x100）解引用 → Oops → panic → kdump 捕获。

---

## 复现路径

前置：Lustre PCC-RW 配好（copytool + `lctl pcc add /fsx /mnt/pcc_nvme/cache --param "uid={0} rwid=1"`）。
触发（必崩）：
```bash
sudo bash -c '
  for i in $(seq 0 7); do dd if=/dev/zero of=/fsx/crash.$i bs=1M count=1024 oflag=direct & done; wait
  fio --name=x --directory=/fsx --rw=randwrite --bs=4k --size=1G --numjobs=8 --iodepth=32 --ioengine=libaio --direct=1 --time_based --runtime=60'
```
root 建的文件命中 PCC autocache（uid={0}）→ attach 进 NVMe 缓存 → direct IO 完成路径崩溃。

## kdump 配置（用于抓栈）
```bash
sudo dnf install -y kexec-tools
sudo grubby --update-kernel=ALL --args="crashkernel=2G-:512M"
sudo systemctl enable kdump
sudo reboot   # crashkernel 内存预留需重启生效
# 验证: cat /sys/kernel/kexec_crash_loaded 应为 1
# 崩溃后 vmcore + vmcore-dmesg.txt 存于 /var/crash/<ip>-<时间>/
```

---

## 稳定性教训

1. **PCC 在托管 FSx Lustre 上有内核崩溃风险**（此 kernel 版本），不建议启用；PCC 更适合可控 MDT 的自建 Lustre。
2. **崩溃在 iomap/NVMe direct IO 中断路径**，非 Lustre 上层逻辑——但由 PCC 的 IO 重定向触发。
3. **eviction 不是根因**：首次崩溃曾疑为 eviction 善后，但后续无 eviction 的纯 PCC 高压 IO 同样崩，kdump 栈坐实是 iomap direct IO 路径。
4. 测试机务必配 fstab（`_netdev nofail`）+ kdump，否则崩溃后需手动重挂且无栈可查。

*配合 24h 压测 + 网络故障注入（FIS）实验。相关：`fsx-lustre-fis-network-latency/`。*
