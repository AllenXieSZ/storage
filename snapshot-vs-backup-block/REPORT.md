# FlexVol→FlexGroup 转换阻塞：snapshot 隔离验证报告

**日期**: 2026-09-01
**区域**: AWS us-east-2 (us-east-2c)
**ONTAP**: NetApp Release 9.18.1P5 (FSx for ONTAP, Gen2)
**执行**: 后台子 agent（继承 workspace）
**发起**: 伟伟

---

## 一、实验定位

本实验是「FlexVol→FlexGroup 就地转换阻塞根因」系列的收尾隔离实验。

**已坐实的前置结论（前几次实验）**：
- FSx 原生 **Backup**（底层 = SnapMirror-to-Cloud）会让卷存在隐藏的 copy-to-cloud 关系，导致就地转 FlexGroup 被**硬阻塞**（`Error: copy to cloud relationship`）。
- 删掉 backup 后等后台异步释放（≤1min）→ 又能转 → backup 是**可解除软阻塞**。
- 参见 GitHub `storage/backup-flexgroup-rootcause`、`datasync-snapmirror-rootcause`。

**本次专门要隔离验证的假设 H**：
> **H：只有 snapshot、从不 backup 的 FlexVol，即使带多个手动 snapshot 也能成功就地转 FlexGroup —— 即 snapshot 本身不阻塞转换。**

即：把 backup 变量彻底拿掉，只留 snapshot 变量，看是否还阻塞。若成功，则反证「阻塞来自 backup（SnapMirror-to-Cloud），而不是 snapshot」。

---

## 二、结论（TL;DR）

✅ **假设 H 成立，且是实测坐实（非推理）**：

1. **带 4 个内容各异的手动 snapshot 的干净 FlexVol，`volume conversion start` check-only 只报 3 条 warning、无任何 error**；实转 `[Job 65] Job succeeded: success`。
2. 转换后 `volume-style-extended` 从 `flexvol` 变为 **`flexgroup`**（单 constituent `snapvol__0001`），数据完整（3.6G 4 个文件都在）。
3. 转换后**所有原 snapshot 状态被置为 `pre-conversion`**，与 NetApp 官方文档描述完全一致。
4. 全程**没有做任何 backup**，转换零阻塞 → 反证：之前那些实验的阻塞**确实来自 backup / SnapMirror-to-Cloud，而不是 snapshot 的存在**。

一句话：**snapshot 不阻塞转换；阻塞的是 FSx 原生 Backup 底层的 copy-to-cloud（SnapMirror-to-Cloud）关系。**

---

## 三、snapshot vs backup 对照表

| 维度 | 手动 snapshot（本次实验） | FSx 原生 Backup（前次实验坐实） |
|------|--------------------------|-------------------------------|
| 底层机制 | 卷本地的 WAFL 只读时间点 | SnapMirror-to-Cloud（copy-to-cloud 关系，导出到 S3） |
| 是否留隐藏 SM 关系 | ❌ 无 | ✅ 有隐藏 copy-to-cloud 关系（`snapmirror show` 连 diag 都看不到，FSx 后台托管） |
| conversion check-only | ✅ 仅 warning，可 proceed | ❌ 报 Error（copy to cloud relationship / not FlexVol） |
| 实转结果 | ✅ Job succeeded → flexgroup | ❌ 硬阻塞失败 |
| 官方文档中的定位 | 仅有「数量上限 1023」+「转换后置 pre-conversion」，**不阻塞** | 属于「卷是 SnapMirror source 且 dest 未转换 / 处于 active SnapMirror 关系」→ **阻塞** |
| 可否解除 | 无需解除（本就不阻塞） | 删 backup → 后台异步释放 copy-to-cloud（≤1min）→ 可转（可解除软阻塞） |

---

## 四、NetApp 官方文档依据

来源：docs.netapp.com/us-en/ontap/flexgroup/convert-flexvol-volume-task.html（2026-09-01 实查）

转换前置检查清单里，**关于 snapshot 只有一条数量限制**，不涉及"存在即阻塞"：
> "For ONTAP 9.7 and earlier, NetApp snapshots must not exceed 255. For ONTAP 9.8 and later, 1023 snapshots are supported."

真正会阻塞转换的与 SnapMirror 相关的两条（FSx Backup 底层正是 SnapMirror-to-Cloud）：
> "The volume is a source of a SnapMirror relationship, and the destination has not yet been converted."
> "The volume is part of an active (not quiesced) SnapMirror relationship."

关于转换对 snapshot 的影响（本次实测已验证）——check-only 原文 warning：
> "Converting flexible volume ... to a FlexGroup will cause the state of all snapshots from the volume to be set to 'pre-conversion'. Pre-conversion snapshots cannot be restored."

**文档层面即可推断**：snapshot 只受数量限制、转换会把它们置为 pre-conversion，但从不阻塞；阻塞的是 SnapMirror 关系。本实验用实测验证了这一推断。

---

## 五、执行步骤与关键输出

### 5.1 环境（吞吐一步到位，跳过升级/扩 HA）
```
create-file-system --file-system-type ONTAP --storage-capacity 4096 \
  --ontap-configuration DeploymentType=SINGLE_AZ_2, HAPairs=2, \
    ThroughputCapacityPerHAPair=1536 (total 3072), FsxAdminPassword=***
Subnet: subnet-0c551a33e366d52d4 (us-east-2c, vpc-0c28d2a9082ef222e)
```
- FileSystemId: **fs-05cc3578781832d5e**，AVAILABLE 约 18 分钟。
- 2 HA pair → 2 个 aggregate：aggr1 (1.77TB), aggr2 (1.77TB)。
- 坑记录：绑定的 `NetApp` 安全组默认只放 9060/9061/8443/3128，**没有 SSH(22)/NFS(2049,111,635,4045-4046)**；需手动放行（源 172.31.0.0/16）后 ONTAP CLI 与 NFS 挂载才通。

### 5.2 SVM + FlexVol
```
create-storage-virtual-machine --name testsvm  → svm-01c6aff9b8c53b5e2 (CREATED)
volume create -vserver testsvm -volume snapvol -aggregate aggr1 -size 200GB \
  -security-style unix -junction-path /snapvol -space-guarantee none  → [Job 63] succeeded
```
转换前：`volume-style-extended = flexvol`，online，aggr1。

### 5.3 写数据 + 建 4 个不同时间点 snapshot
挂载到 Ohio 跳板机（NFS v3），分批写入让 snapshot 各有差异：

| snapshot | 触发前动作 | 转换前 size | 转换后 size |
|----------|-----------|------------|------------|
| snap1_after1gb | 写 file1 1GB | 216KB | 1.01GB |
| snap2_after2gb | 写 file2 1GB | 182.6MB | 2.03GB |
| snap3_after_modify | 写 file3 512M + 改 file1 256M | 60.23MB | 2.61GB |
| snap4_final | 写 file4 512M | 0B | 3.06GB |

（size 随 active fs 与快照分叉增长，说明快照确实各含不同时间点数据）

### 5.4 转换 check-only（diag 级）
```
set -privilege diagnostic -confirmations off
volume conversion start -vserver testsvm -volume snapvol -check-only true
```
输出（**无 error，仅 3 条 warning，可 proceed**）：
```
Conversion of volume "snapvol" in Vserver "testsvm" to a FlexGroup can proceed with the following warnings:
* After the volume is converted to a FlexGroup, it will not be possible to change it back to a flexible volume.
* Converting flexible volume "snapvol" ... will cause the state of all snapshots from the volume to be set to "pre-conversion". Pre-conversion snapshots cannot be restored.
* Converting the volume to a FlexGroup will not add additional resources for capacity. After converting, use the "volume expand" command to add resources.
```

### 5.5 实转（diag 级）
```
volume conversion start -vserver testsvm -volume snapvol
[Job 65] Job is queued: Converting flexible volume to FlexGroup.
[Job 65] success
[Job 65] Job succeeded: success
```

### 5.6 转换后验证
```
# 卷类型
vserver volume  aggr-list size  state  volume-style volume-style-extended
testsvm snapvol aggr1     200GB online flex         flexgroup          ← 变 flexgroup ✅

# constituent（单成员 FlexGroup）
testsvm snapvol__0001  aggr1

# snapshot 状态全部 pre-conversion（含转换自动生成的 convert.* 快照）
snap1_after1gb ... pre-conversion
snap2_after2gb ... pre-conversion
snap3_after_modify ... pre-conversion
snap4_final ... pre-conversion
convert.2026-09-01_103439 ... pre-conversion

# 数据完整
file1.bin 1.0G, file2.bin 1.0G, file3.bin 512M, file4.bin 512M ; 3.6G used
```

---

## 六、与前几次实验的呼应

| 实验 | 变量 | 结果 |
|------|------|------|
| 干净卷（bfa9b06, ctrlvol） | 无 DataSync / 无 backup | ✅ 转换成功 |
| DataSync source 卷（srcvol） | 被 DataSync 用作 source（留 SM-C） | ❌ 硬阻塞 |
| Backup 根因复核（11768de/d8dc999, bkpvol） | 做过 FSx 卷级 backup | ❌ 阻塞；删 backup 后 ≤1min 又能转 |
| **本次（snapvol）** | **只 snapshot、零 backup** | ✅ **转换成功 → 反证阻塞来自 backup 而非 snapshot** |

三方对照闭合：
- 无 backup 无 snapshot → 成功
- 无 backup 有 snapshot（本次）→ 成功
- 有 backup → 失败（删 backup 后又成功）

⇒ **唯一决定阻塞的变量是 backup / SnapMirror-to-Cloud，与 snapshot 无关。**

---

## 七、AWS 资源清单（默认保留）

| 资源 | ID |
|------|-----|
| FSxN 文件系统 | fs-05cc3578781832d5e |
| SVM | svm-01c6aff9b8c53b5e2 (testsvm) |
| 卷 | snapvol（已转 FlexGroup，单 constituent snapvol__0001） |
| 安全组 | sg-07bab98ddeefb19ad（NetApp，已加 SSH/NFS 放行） |
| 跳板机 | i-0dffb881b2a90daa2（Ohio MySQL-Master，SSM） |

fsxadmin 密码：见私有记录（报告中已脱敏）。Mgmt endpoint / NFS IP 见私有记录。

### 清理命令（需要时按顺序执行）
```bash
# 1. 删卷的 snapshot（可选，删卷会连带）
# 2. 删卷
sshpass ... ssh fsxadmin@<mgmt-ip> "volume unmount -vserver testsvm -volume snapvol; \
  volume offline -vserver testsvm -volume snapvol; \
  volume delete -vserver testsvm -volume snapvol -force true"
# 3. 删 SVM
aws fsx delete-storage-virtual-machine --storage-virtual-machine-id svm-01c6aff9b8c53b5e2 --region us-east-2
# 4. 删文件系统
aws fsx delete-file-system --file-system-id fs-05cc3578781832d5e --region us-east-2 \
  --ontap-configuration SkipFinalBackup=true
```
> 本实验**未创建任何 FSx backup**，所以无需先删 recovery point。

---

## 八、成本提示
- 2HA/1536-per-HA/4096 Gen2 FSxN 按小时计费（吞吐档越高越贵）。本实验数据量极小（3.6G），主要成本在文件系统运行时长，建议不用时删除。

---

## 九、自检合规
- 结论基于 NetApp 官方文档（convert-flexvol-volume-task.html）+ 实测。
- 实测高于推理：假设与实测一致且用实测坐实，变量隔离（只留 snapshot，去掉 backup/DataSync）。
- 无推测冒充事实；所有命令输出见 `logs/experiment-log.txt`。
