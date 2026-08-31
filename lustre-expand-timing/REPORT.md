# FSx for Lustre 容量扩容耗时实测报告：1.2 TiB → 2.4 TiB

> ⚠️ **仅本次测试环境实测，不代表官方结论。** 单次实测，样本 n=1，实际耗时受容量、已用数据量、DeploymentType、区域负载等影响。

## 结论先行

**在本次测试环境下，FSx for Lustre（PERSISTENT_2 / 500 MB/s/TiB）把容量从 1.2 TiB 扩到 2.4 TiB（已灌 ~900 GB 真实数据），从发起 `update-file-system` 到文件系统 Lifecycle 回到 `AVAILABLE`（新容量 2400 GiB 可用）实测耗时 ≈ 15.7 分钟（943 秒）。**

- 之后还有一段**后台 `STORAGE_OPTIMIZATION`（数据重分布）**，把老数据从原 OST 均衡到新增 OST，**不阻塞使用**（此时 Lifecycle 已是 AVAILABLE、文件系统可正常读写）。该重分布从发起 update 起算 ≈ **38.9 分钟（2336 秒）** 完成。
- **扩容机制 = 加 OST**：1.2 TiB 时 1 个 OST；扩到 2.4 TiB 后变成 2 个 OST（容量翻倍靠新增 OST0001），并非把原 OST 撑大。MDT 容量也从 34.4G 涨到 69.0G。

---

## 测试配置

| 项 | 值 |
|---|---|
| 服务 | Amazon FSx for Lustre |
| DeploymentType | **PERSISTENT_2** |
| PerUnitStorageThroughput | **500** MB/s/TiB |
| 起始容量 | **1200 GiB (1.2 TiB)** |
| 目标容量 | **2400 GiB (2.4 TiB)** |
| Region / AZ | us-east-2 / us-east-2c |
| Subnet / VPC | subnet-0c551a33e366d52d4 / vpc-0c28d2a9082ef222e |
| SG | sg-08f2883d5c47ced16 (复用 lustre-learn) |
| FileSystemId | fs-01d83babb9999c2ad |
| MountName | spxr3b4v |
| DNS | fs-01d83babb9999c2ad.fsx.us-east-2.amazonaws.com |
| 灌数据 | ~900 GB（9 × 100 GiB，dd if=/dev/urandom 并行）|
| 灌数据 EC2 | c6in.2xlarge, AL2023 (kernel 6.18.41), lustre-client 2.15.6-32 |

---

## 精确时间线

### 阶段 1：创建文件系统（1.2 TiB）
- `create-file-system` 提交：**03:14:08 UTC**
- CreationTime（AWS 记录）：03:14:10
- 检测到 AVAILABLE：**03:21:34 UTC**
- **创建耗时 ≈ 7 分 26 秒**

### 阶段 2：灌 ~900 GB 数据
- 9 路并行 dd（每路 100 GiB，`bs=1M iflag=fullblock`）
- 单路速率 68.9 MB/s，**聚合 ≈ 591 MB/s**（贴近 PERSISTENT_2/500 的写入能力）
- **灌数据耗时 ≈ 26 分钟**（1559 s/路）
- 灌完 `lfs df`：OST0000 用 900.3G / 1.1T（79%），单 OST

### 阶段 3：扩容 1.2 → 2.4 TiB（核心测量）
`update-file-system --storage-capacity 2400` 提交 = **03:49:08 UTC = T0**

| 相对 T0 | Lifecycle | FILE_SYSTEM_UPDATE | STORAGE_OPTIMIZATION | Cap |
|---|---|---|---|---|
| +12s | UPDATING | IN_PROGRESS | PENDING | 1200 |
| +59s ~ +896s | UPDATING | IN_PROGRESS | PENDING | 1200 |
| **+943s** | **AVAILABLE** ✅ | UPDATED_OPTIMIZING | IN_PROGRESS (0%) | **2400** |
| +989s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (2%) | 2400 |
| +1227s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (20%) | 2400 |
| +1720s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (45%) | 2400 |
| +1843s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (60%) | 2400 |
| +2028s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (77%) | 2400 |
| +2089s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (99%) | 2400 |
| **+2336s** | AVAILABLE | **COMPLETED** ✅ | (完成，action 消失) | 2400 |

- ⭐ **到 AVAILABLE（新容量可用）= 943s ≈ 15.7 分钟**（转变发生在 +896s 仍 UPDATING 与 +943s 已 AVAILABLE 之间，误差 ≤ 47s）
- **后台数据重分布完成 = 2336s ≈ 38.9 分钟**（不阻塞使用）

---

## OST 容量与数据分布变化

### 扩容前（1.2 TiB，单 OST）
```
spxr3b4v-MDT0000   34.4G   used 8.9M
spxr3b4v-OST0000   1.1T    used 900.3G   79%
summary            1.1T    used 900.3G   79%
```

### 扩容刚 AVAILABLE 时（2.4 TiB，2 OST，重分布刚开始）
```
spxr3b4v-MDT0000   69.0G   used 9.1M
spxr3b4v-OST0000   1.1T    used 910.2G   80%   ← 老数据仍全在原 OST
spxr3b4v-OST0001   1.1T    used  20.8G    2%   ← 新增 OST，刚开始接收
summary            2.2T    used 931.1G   41%
```

### STORAGE_OPTIMIZATION 完成后（重分布均衡）
```
spxr3b4v-MDT0000   69.0G   used 9.2M
spxr3b4v-OST0000   1.1T    used 549.1G   48%   ← 迁走 ~360G
spxr3b4v-OST0001   1.1T    used 360.8G   32%   ← 接收 ~360G
summary            2.2T    used 909.9G   40%
```

**观察**：
1. **新容量靠新增 OST 实现**（OST0000→OST0000+OST0001），不是撑大原 OST。
2. **老数据初始全留在 OST0000**；扩容后 AWS 自动跑 `STORAGE_OPTIMIZATION` 把约 350–360G 老数据重分布到新 OST。
3. 重分布后两 OST 大致均衡（549G vs 361G），但**未完全 50:50**——因为是按已有文件/条带迁移，非精确对半。
4. **重分布阶段不影响可用性**：Lifecycle 全程 AVAILABLE，文件系统可正常读写。

---

## 成本

| 项 | 说明 |
|---|---|
| FSx Lustre PERSISTENT_2 500 | 1.2→2.4 TiB，存活约 1.5 小时 |
| EC2 c6in.2xlarge | 约 1.5 小时 |
| 合计 | ≈ $5–6（符合预算），测完已清理 |

---

## 复现命令（关键步骤）

```bash
# 1. 创建 1.2 TiB Lustre
aws fsx create-file-system --file-system-type LUSTRE --storage-capacity 1200 \
  --subnet-ids <subnet> --security-group-ids <sg> \
  --lustre-configuration DeploymentType=PERSISTENT_2,PerUnitStorageThroughput=500 \
  --region us-east-2

# 2. 挂载（AL2023 自带 lustre-client 2.15.6，modprobe lustre 即可）
mount -t lustre -o relatime,flock <dns>@tcp:/<mountname> /mnt/fsx

# 3. 灌 900G
for i in $(seq 1 9); do dd if=/dev/urandom of=/mnt/fsx/big_$i.bin bs=1M count=102400 iflag=fullblock & done

# 4. 扩容（计时核心）
aws fsx update-file-system --file-system-id <fsid> --storage-capacity 2400 --region us-east-2

# 5. 轮询 Lifecycle + AdministrativeActions
aws fsx describe-file-systems --file-system-ids <fsid> --region us-east-2 \
  --query 'FileSystems[0].{Life:Lifecycle,Cap:StorageCapacity,Actions:AdministrativeActions[].{T:AdministrativeActionType,S:Status,P:ProgressPercent}}'
```

---

## 关键结论速记

- **扩容 1.2→2.4 TiB（900G 数据）到 AVAILABLE ≈ 15.7 分钟**（本次实测）。
- **AVAILABLE ≠ 重分布完成**：AVAILABLE 后仍有 ~23 分钟的后台 STORAGE_OPTIMIZATION（不阻塞使用）。
- **扩容 = 加 OST**：新容量在新 OST 上；老数据初始不动，靠后台重分布均衡。
- AL2023（kernel 6.18）**默认 repo 已含 lustre-client 2.15.6**，无需额外加 aws-fsx repo。

> ⚠️ 再次声明：以上均为**单次测试环境实测**，n=1，不代表 AWS 官方性能承诺。扩容耗时会随数据量、容量、区域负载变化。
