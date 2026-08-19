# FSx for ONTAP 缩容实测：文件系统 SSD 缩容 vs Volume 缩容

在 AWS us-east-2 实测 FSx for ONTAP **第二代（Gen-2 / SINGLE_AZ_2）** 文件系统的两种缩容：
1. **文件系统级 SSD 容量缩容**（2TB → 1.5TB）
2. **Volume 缩容**（2TB → 1TB）

> ⚠️ 所有敏感值（账号 ID、资源 ID、IP、密码、域名）已用占位符。

---

## 实验环境

- **文件系统**：Gen-2 FSx ONTAP，`SINGLE_AZ_2`，SSD 2048 GiB（2TB），`ThroughputCapacityPerHAPair=384`，`HAPairs=1`
- **SVM + Volume**：1 个 SVM，1 个 volume（2TB，UNIX 安全风格，NFS，TieringPolicy=NONE 保证数据全在 SSD）
- **数据**：从 S3 下载 1 个 100GB 大文件，本地 `cp` 复制成 5 份 = **~500GB**（占 volume 25%，占 SSD ~33%）
- **挂载**：NFSv3，`mount -t nfs -o nfsvers=3 <NFS_IP>:/<junction> /mnt/xxx`

---

## 测试 1：文件系统 SSD 容量缩容 2TB → 1.5TB

**命令（AWS CLI，走 FSx API）**：
```bash
aws fsx update-file-system --region <REGION> \
  --file-system-id <FSID> --storage-capacity 1536
```

**过程与耗时**：
| 阶段 | 观察 |
|---|---|
| PENDING（排队）| 约 3 分钟 |
| IN_PROGRESS（数据 rebalance）| 进度 0→100%，稳步推进 |
| COMPLETING → 容量变 1536 GiB | — |
| **总耗时** | **≈ 1470 秒（约 24.5 分钟）** |

**要点**：
- ✅ **仅 Gen-2 文件系统支持缩 SSD**；Gen-1 只能增不能减。
- ✅ **原地缩容，无需数据迁移、无停机**，数据全程完整（5 个文件缩后都在）。
- ⚠️ 缩容是**后台数据 rebalance 过程**（把待移除存储上的数据搬走），耗时随数据量增长（本次 500GB≈24.5 分钟）。
- ⚠️ 受 **80% 利用率约束**：缩后容量的 80% 必须容得下现有数据（500GB < 1.5TB×80%=1.2TB，OK）。
- 用 `describe-file-systems` 的 `AdministrativeActions[].{Status,ProgressPercent}` 跟踪进度（FILE_SYSTEM_UPDATE）。

---

## 测试 2：Volume 缩容 2TB → 1TB

### ⚠️ 关键发现：FSx `update-volume` API 不支持缩小 volume

**先试了 FSx CLI（失败，静默不生效）**：
```bash
aws fsx update-volume --region <REGION> \
  --volume-id <VOLID> --ontap-configuration '{"SizeInBytes":1099511627776}'
```
→ API **接受请求、返回正常、但 volume size 静默不变**（既不报错也不生效，`AdministrativeActions` 为 null）。**FSx update-volume 只支持增大 volume，不支持缩小。**

**正解：用 ONTAP CLI `volume modify -size`**：
```bash
# SSH 到文件系统 Management endpoint（fsxadmin）
ssh fsxadmin@<MGMT_IP>
volume modify -vserver <SVM_NAME> -volume <VOL_NAME> -size 1TB
# → "Volume modify successful"
```

**过程与耗时**：
| 项 | 结果 |
|---|---|
| 命令执行 | **近乎瞬时（秒级）** |
| ONTAP `volume show` | size 立即变 1TB，data 502GB 完好 |
| 挂载点 `df -h` | 从 2.0T 变 973G（=1TB），数据 5 文件完整 |

**要点**：
- ✅ Volume 缩容是**改逻辑配额（thin provisioning），秒级完成**，与文件系统 SSD 物理缩容完全不同（后者要搬数据、几十分钟）。
- ⚠️ **缩后 size 不能小于已用数据量**（1TB > 502GB，OK）。
- ⚠️ **必须走 ONTAP CLI**（`volume modify`），FSx update-volume API 缩不了。
- ⚠️ ONTAP CLI 命令**必须带 `-vserver`**，否则报 "Either specify all keys, or set at least one key to *"。
- ⚠️ 走 ONTAP CLI 缩容后，**FSx API `describe-volumes` 的 SizeInBytes 不会同步**（仍显示旧值 2TB），但 ONTAP 层和挂载点是真实的 1TB。做自动化/监控时要注意这个不一致。
- fsxadmin 登录用**文件系统 Management endpoint IP**（`describe-file-systems ... Endpoints.Management`），不是 SVM 的 NFS/mgmt IP。

---

## 两种缩容对比总表

| | 文件系统 SSD 缩容 | Volume 缩容 |
|---|---|---|
| 改的是 | **物理 SSD 容量**（真省钱）| **逻辑配额**（thin，不直接改物理占用）|
| 入口 | FSx API `update-file-system` ✅ | **必须 ONTAP CLI `volume modify`**（FSx API 缩不了）|
| 耗时（500GB 数据）| ~24.5 分钟（后台 rebalance）| 秒级 |
| 代际限制 | **仅 Gen-2** | 任意代（NAS 卷；iSCSI 卷不支持缩）|
| 主要约束 | 缩后 80% 容量 ≥ 现有数据 | 缩后 size ≥ 已用数据量 |
| 数据完整性 | 完整、无停机 | 完整、无停机 |

---

## 排障备忘

1. FSx create-volume 的 `SizeInBytes` 是 **int**，JSON 里别加引号（用 `--cli-input-json` 传最稳）。
2. SSD 缩容进度看 `AdministrativeActions`（FILE_SYSTEM_UPDATE 的 Status/ProgressPercent）。
3. Volume 缩容 FSx API 无声失败 → 改用 ONTAP CLI，且带 `-vserver`。
4. ONTAP CLI 走 SSH 到 Management endpoint；命令用 base64 经跳板机传避免引号转义。
