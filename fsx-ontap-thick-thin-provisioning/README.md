# FSx for NetApp ONTAP — Thick vs Thin Provisioning 超额分配实测

在一个 **1024 GB** 的 FSx ONTAP 文件系统上验证 volume 的 thick / thin provisioning 行为：
- 创建 3 个 400 GB 的 **thick** volume，观察第 3 个是否因 aggregate 空间不足而失败（记录报错原文）；
- 第 3 个改用 **thin** provisioning、容量 **1 TB**，验证 thin 能否超额分配（overcommit）成功。

> 环境标识（文件系统 ID / SVM / subnet / SG / 实例 ID / IP）已脱敏为 `REDACTED`。

## 背景：ONTAP 的 thick / thin provisioning

官方文档：
- Configure volume provisioning options (NetApp)
  https://docs.netapp.com/us-en/ontap/san-admin/configure-volume-provisioning-options-task.html
- Managing FSx for ONTAP volumes (AWS)
  https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-volumes.html

- **Thin provisioning** = `-space-guarantee none`：创建时不预留空间，随数据写入按需向 aggregate 申请。
  允许 **overcommit（超额分配）**——所有 volume 的名义容量之和可以超过 aggregate 物理容量，
  代价是 aggregate 写满时 volume 可能写失败，需监控。**FSx ONTAP 的 volume 默认就是 thin。**
- **Thick provisioning** = `-space-guarantee volume`（或 `-space-slo thick`）：
  创建时就在 aggregate 中把整卷空间预分配掉，保证写入不会因 aggregate 空间不足失败；
  代价是不能超配，且更占空间。

## 环境

| 项 | 值 |
|---|---|
| 服务 | FSx for NetApp ONTAP, SINGLE_AZ_1 |
| 文件系统容量 | 1024 GiB SSD, ThroughputCapacity 128 MBps |
| 数据 aggregate | `aggr1`，总 861 GB，初始可用 ~860 GB（扣系统预留 + 5% snapshot reserve）|
| 客户端 | 同 AZ/子网的 EC2（跳板机），走 ONTAP CLI（fsxadmin）|

## ⚠️ 关键发现 1：FSx ONTAP 上 `-space-guarantee volume` 被直接拒绝

直接用 `-space-guarantee volume` 创建 thick volume，立即报错：

```
Error: command failed: Aggregates with attached object stores cannot contain
       volumes with a guarantee other than "none".
```

**原因**：FSx ONTAP 的 aggregate 默认启用 **FabricPool**（附加了一个 object store
`FSxFabricpoolObjectStore` 用于容量分层 / tiering）。FabricPool aggregate **不允许**
guarantee 为 `volume` 的 volume。

## ⚠️ 关键发现 2：thick 要用 `-space-slo thick`

改用 `-space-slo thick` 成功创建 thick volume。`space-slo=thick` 会把 volume 标记为
thick（内部 space-guarantee 显示为 volume），但走的是 Service Level Objective 路径，
被 FabricPool aggregate 接受。

```bash
# ✅ FSx ONTAP 上正确的 thick 建卷方式
volume create -vserver <svm> -volume thickvol1 -aggregate aggr1 \
  -size 400GB -space-slo thick -junction-path /thickvol1 -security-style unix

# ❌ 这个会被 FabricPool aggregate 拒绝
volume create ... -space-guarantee volume     # Error: ... guarantee other than "none"
```

## 操作步骤

```bash
# 建文件系统（1024 GB）/ SVM（略，见 AWS CLI create-file-system / create-storage-virtual-machine）

# 连 ONTAP CLI（fsxadmin@<文件系统 Management endpoint IP>）
# 查数据 aggregate 空间
storage aggregate show-space
df -A -h aggr1

# thick vol1 / vol2（各 400GB，space-slo thick）
volume create -vserver <svm> -volume thickvol1 -aggregate aggr1 -size 400GB -space-slo thick -junction-path /thickvol1 -security-style unix
volume create -vserver <svm> -volume thickvol2 -aggregate aggr1 -size 400GB -space-slo thick -junction-path /thickvol2 -security-style unix

# thick vol3（第 3 个，预期空间不足失败）
volume create -vserver <svm> -volume thickvol3 -aggregate aggr1 -size 400GB -space-slo thick -junction-path /thickvol3 -security-style unix

# 改 thin，1TB（-space-guarantee none）
volume create -vserver <svm> -volume thinvol3 -aggregate aggr1 -size 1TB -space-guarantee none -junction-path /thinvol3 -security-style unix
```

## 测试结果

### thick volume 逐个创建

| Vol | 大小 | 方式 | 结果 | 创建后 aggr1 已用 |
|---|---|---|---|---|
| thickvol1 | 400GB | `-space-slo thick` | ✅ 成功 | ~406 GB |
| thickvol2 | 400GB | `-space-slo thick` | ✅ 成功 | 806 GB（剩 55 GB）|
| thickvol3 | 400GB | `-space-slo thick` | ❌ **失败**（空间不足）| — |

### 第 3 个 thick 的报错原文

```
Error: command failed: [Job 49] Job failed: Failed to create the volume on node
       "REDACTED-01". Reason: Request to create volume
       "thickvol3" failed because there is not enough space in aggregate
       "aggr1". Either create 347GB of free space in the aggregate or select a
       size of at most 54.9GB for the new volume.
```

### 第 3 个改 thin（1TB）

```
volume create ... -volume thinvol3 -size 1TB -space-guarantee none
[Job 50] Job succeeded: Successful
```

✅ **thin 1TB 成功**——即使 aggregate 只剩 ~55 GB，仍能创建名义 1 TB 的 thin volume。

### 最终 volume 列表

| Volume | Size | Available | space-slo | space-guarantee |
|---|---|---|---|---|
| thickvol1 | 400GB | 380GB | thick | volume |
| thickvol2 | 400GB | 380GB | thick | volume |
| thinvol3 | **1TB** | **55.24GB** | none | none |

注意 thinvol3 名义 1 TB，但 `available` 只有 55 GB（= aggregate 真实剩余空间）——
这就是 thin 超额分配的本质：名义容量可超配，实际可写入量受 aggregate 物理剩余限制。

## 结论

1. **FSx ONTAP 的 aggregate 默认是 FabricPool（带 object store 分层）**，所以标准的
   `-space-guarantee volume` 会被拒绝；在 FSx 上做 thick provisioning 必须用 `-space-slo thick`。

2. **Thick 预分配整卷空间、不能超配**：1024 GB 文件系统（数据可用 ~860 GB）上，
   前 2 个 400 GB thick 成功（累计 800 GB），第 3 个（累计 1200 GB）因超出 aggregate
   剩余空间而失败，报错明确给出"需释放 347 GB 或把新卷大小降到 ≤54.9 GB"。

3. **Thin 允许超额分配（overcommit）**：即使 aggregate 仅剩 55 GB，仍能创建名义 1 TB 的
   thin volume；实际可写入量受 aggregate 真实剩余空间限制（available=55 GB）。

4. **生产启示**：
   - thin 省空间、可超配，但 aggregate 写满时会写失败，**必须监控 aggregate 使用率 + 配 autosize**；
   - thick 保证空间不会被别的 volume 抢占，但会占满预分配，且 FSx 上受 FabricPool 限制需用 `space-slo thick`。

## 注意事项

- ONTAP CLI 用 `fsxadmin` 登录连的是**文件系统 Management endpoint IP**，不是 SVM 的 NFS/mgmt IP。
- FSx ONTAP volume 默认 thin；控制台/CLI/API 创建的 volume 都是 thin，thick 需 ONTAP CLI 显式设。
- 1024 GB 文件系统实际数据可用约 860 GB（系统预留 + 5% snapshot reserve 会吃掉一部分）。
