# FSx ONTAP 缩容并发能力 + 对 IO 性能影响实测

在 AWS us-east-2 建 Gen-2 FSx ONTAP（2TB SSD）+ 2TB volume + 500GB 数据，用 fio 实测：
1. **文件系统 SSD 缩容进行中，能否同时做 volume 缩容？**
2. **缩容对 IO 性能（IOPS/吞吐/延迟）的影响**（基线 vs 缩容期间 vs 缩容后）

> ⚠️ 所有敏感值已用占位符。

---

## 实验环境

- Gen-2 FSx ONTAP，SSD 2048 GiB，`ThroughputCapacityPerHAPair=384`，`HAPairs=1`
- 2TB volume（NFS，UNIX，TieringPolicy=NONE），~500GB 数据（1×100GB from S3 + cp×4）
- fio 命令（三次完全一致）：
  ```bash
  fio --name=xxx --directory=/mnt/vol --rw=randrw --rwmixread=70 \
    --bs=64k --size=4G --numjobs=4 --iodepth=64 --direct=1 \
    --ioengine=libaio --runtime=600 --time_based --group_reporting
  ```

---

## 发现 1：SSD 缩容进行中，volume 缩容可以并发进行 ✅

- 发起文件系统 SSD 缩容（`update-file-system --storage-capacity 1536`），等它进入 `IN_PROGRESS`。
- 此时通过 ONTAP CLI 缩 volume：`volume modify -vserver <SVM> -volume <VOL> -size 1TB` → **"Volume modify successful"，立即完成**。
- 之后查：volume 已是 1TB（used 517GB），且 SSD 缩容仍 `IN_PROGRESS` 继续跑。
- **结论：两个操作互不阻塞、可并发**。原因：它们是不同层——SSD 缩容是**物理容量后台 rebalance**（慢，几十分钟），volume 缩容是**逻辑配额调整**（秒级）。

---

## 发现 2：缩容对 IO 性能的影响

| 阶段 | 读 IOPS / 吞吐 | 写 IOPS / 吞吐 | 合计 IOPS |
|---|---|---|---|
| **基线**（2TB SSD, IOPS 配额 6144）| 4187 / 268 MB/s | 1794 / 115 MB/s | 5981 |
| **缩容期间**（2TB→1.5TB 过程中）| 3988 / 255 MB/s | 1708 / 109 MB/s | 5696（**-4.8%**）|
| **缩容后**（1.5TB SSD, IOPS 配额 4608）| 2500 / 160 MB/s | 1072 / 69 MB/s | 3572（**-40%**）|

### 关键结论（要分清两种"影响"）

**① 缩容过程本身对性能影响很小（约 -5%）**
- 缩容期间 IO 只降 ~4.8%，几乎无感。印证 AWS 文档"缩容对性能影响最小"。
- 缩容是后台低优先级 rebalance，不抢占前台 IO 太多。

**② 缩容后性能大幅下降（-40%）—— 但这不是"缩容的后遗症"，是 SSD 容量变小导致 IOPS 配额同步下降**
- FSx ONTAP 的 SSD IOPS 按容量自动配比：**3 IOPS/GiB（AUTOMATIC 模式）**。
- SSD 2TB→1.5TB → provisioned IOPS **6144→4608（-25%）**。
- 实测合计 IOPS 降 40%（比配额降幅大，因高负载下更受配额天花板制约）。
- ⚠️ **这是缩容的"预期代价"而非缺陷**：缩 SSD 省钱的同时，性能上限（IOPS）也按比例降了。

### ⚠️ 缩容规划的重要提醒
- **缩 SSD = 同时缩了 IOPS 上限**（AUTOMATIC 模式下）。若业务对 IOPS 敏感，缩容前要评估缩后 IOPS 是否够用。
- 若想缩容量但保持高 IOPS，可用 `USER_PROVISIONED` 模式单独指定 IOPS（不随容量自动降），但会额外付费。

---

## 发现 3：fio 负载会拖慢缩容速度

- 缩容期间同时跑 fio：10 分钟 fio 结束时 SSD 缩容仅到 2%。
- fio 停止后缩容明显加速（每分钟 3-6%）。
- **结论：前台 IO 负载与后台 rebalance 抢资源，会显著拖慢缩容**。本次带 fio 干扰总耗时约 34 分钟（纯缩容参考约 24 分钟）。
- 规划缩容窗口应尽量避开高 IO 时段，或接受缩容变慢。

---

## 命令备忘

```bash
# SSD 缩容（FSx API）
aws fsx update-file-system --file-system-id <FSID> --storage-capacity 1536

# volume 缩容（必须 ONTAP CLI，FSx update-volume API 缩不了）
ssh fsxadmin@<MGMT_IP>
volume modify -vserver <SVM_NAME> -volume <VOL_NAME> -size 1TB

# 查缩容进度
aws fsx describe-file-systems --file-system-id <FSID> \
  --query 'FileSystems[0].AdministrativeActions[?AdministrativeActionType==`FILE_SYSTEM_UPDATE`]'

# 查缩容后 IOPS 配额
aws fsx describe-file-systems --file-system-id <FSID> \
  --query 'FileSystems[0].OntapConfiguration.DiskIopsConfiguration'
```
