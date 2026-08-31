# 附录：测试 B 详细数据 —— 灌到 ~92% 满（~1.05 TB）对照测试 A

> ⚠️ **仅本次测试环境实测，不代表官方结论。** 单次实测，样本 **n=1**，实际耗时受容量、已用数据量、DeploymentType、区域负载等影响。本报告核心是与 v1（灌 900G / 79% 满）的**单次对照**，用于观察「接近容量满时扩容/重分布耗时是否变长」的方向性趋势，**不构成统计结论**。

## 结论先行

**本次实验唯一变量 = 灌数据量从 v1 的 ~900G（79% 满）提高到 v2 的 ~1.05 TB（92% 满），其余参数（PERSISTENT_2 / 500 MB/s/TiB / 1200→2400 GiB / us-east-2c）与 v1 完全一致。**

单次实测方向性结论（n=1）：

- **到 AVAILABLE（新容量 2400 GiB 可用）**：v1 ≈ **15.7 分钟** → v2 ≈ **16.8 分钟**（+1.1 min，略增，基本持平）。
- **后台 STORAGE_OPTIMIZATION（数据重分布）完成**：v1 ≈ **38.9 分钟** → v2 ≈ **46.0 分钟**（**+7.1 min，明显变长**）。
- **趋势解读（单次，谨慎）**：接近容量满时，「到 AVAILABLE」这段（本质是扩容加 OST 的控制面操作）**几乎不受已用数据量影响**；真正随数据量拉长的是**后台重分布**——因为要搬到新 OST 的老数据更多（v2 要重分布 ~514G，v1 只 ~361G）。**AVAILABLE 不阻塞使用，重分布在后台进行**，所以对业务的「可用等待」两次都在 ~16 分钟量级。

---

## 测试配置（v2，与 v1 唯一差异=灌数据量）

| 项 | v1 | v2（本次）|
|---|---|---|
| 服务 | FSx for Lustre | 同 |
| DeploymentType | PERSISTENT_2 | 同 |
| PerUnitStorageThroughput | 500 MB/s/TiB | 同 |
| 起始容量 | 1200 GiB (1.2 TiB) | 同 |
| 目标容量 | 2400 GiB (2.4 TiB) | 同 |
| Region / AZ | us-east-2 / us-east-2c | 同 |
| Subnet / SG | subnet-0c551a33e366d52d4 / sg-08f2883d5c47ced16 | 同 |
| 灌数据 EC2 | c6in.2xlarge, AL2023, lustre-client 2.15.6 | 同 |
| **灌数据量** | **~900 GB（79% 满）** | **~1.05 TB（92% 满）** ← 唯一变量 |
| FileSystemId | fs-01d83babb9999c2ad | **fs-0f29a383fee84742e** |
| MountName | spxr3b4v | **7tsb3b4v** |

> 说明：本次 AL2023（kernel 6.18.41）默认 repo **未**自带 lustre-client 用户态工具（`lfs`/`mount.lustre` 缺失，仅内核模块内置），需按 AWS FSx repo 安装 `lustre-client 2.15.6`。（v1 报告曾称"默认已含"，本次实测需手动安装，已修正。）

---

## v2 精确时间线

### 阶段 1：创建文件系统（1.2 TiB）
- `create-file-system` 提交：**05:51:22 UTC**
- 检测到 AVAILABLE：**05:57:34 UTC**
- **创建耗时 ≈ 6.2 分钟（372 s）**

### 阶段 2：灌 ~1.05 TB 数据（灌到 92% 满）
- 先 10 路并行 `dd`（每路 100 GiB，`if=/dev/urandom bs=1M iflag=fullblock`）= 1000 GiB，聚合 ~545–555 MB/s
- 灌完到 1000.3G（88% 满），再追加 1 个 50 GiB 文件 topup 至 **1050.3G / 92% 满**（灌前 `lfs df` 确认可用 95.4G，未写爆）
- **灌数据总耗时 ≈ 42.7 分钟**（含 topup；纯 1000G 主体 ~30 min）
- 灌完 `lfs df`：OST0000 用 **1.0T / 1.1T（92%）**，单 OST，可用 95.4G

### 阶段 3：扩容 1.2 → 2.4 TiB（核心测量）
`update-file-system --storage-capacity 2400` 提交 = **06:41:40 UTC = T0**

| 相对 T0 | Lifecycle | FILE_SYSTEM_UPDATE | STORAGE_OPTIMIZATION | Cap |
|---|---|---|---|---|
| +19s | UPDATING | PENDING | PENDING | 1200 |
| +56s ~ +971s | UPDATING | IN_PROGRESS | PENDING | 1200 |
| **+1007s** | **AVAILABLE** ✅ | UPDATED_OPTIMIZING | IN_PROGRESS (0%) | **2400** |
| +1117s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (2%) | 2400 |
| +1263s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (15%) | 2400 |
| +1519s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (32%) | 2400 |
| +1775s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (54%) | 2400 |
| +2032s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (69%) | 2400 |
| +2361s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (78%) | 2400 |
| +2544s | AVAILABLE | UPDATED_OPTIMIZING | IN_PROGRESS (99%) | 2400 |
| **+2763s** | AVAILABLE | **COMPLETED** ✅ | (完成，action 消失) | 2400 |

- ⭐ **到 AVAILABLE（新容量可用）= 1007s ≈ 16.8 分钟**（转变发生在 +971s 仍 UPDATING 与 +1007s 已 AVAILABLE 之间，误差 ≤ 36s）
- **后台数据重分布完成 = 2763s ≈ 46.0 分钟**（不阻塞使用）

---

## ⭐ v1 vs v2 对照表（核心）

| 指标 | v1（灌 900G / 79% 满）| v2（灌 ~1.05TB / 92% 满）| 差值 | 方向 |
|---|---|---|---|---|
| 灌数据量 | ~900 GB | ~1050 GB | +~150 GB / +~17% | — |
| 灌前 OST 使用率 | 79% | 92% | +13pp | — |
| **到 AVAILABLE 耗时** | **15.7 min (943s)** | **16.8 min (1007s)** | **+1.1 min (+7%)** | 略增 / 基本持平 |
| **重分布完成耗时** | **38.9 min (2336s)** | **46.0 min (2763s)** | **+7.1 min (+18%)** | **明显变长** |
| AVAILABLE 时 OST 数 | 1→2 (OST0001 新增) | 1→2 (OST0001 新增) | 同 | 机制一致 |
| 重分布后分布 | 549G : 361G | 570G : 514G | v2 更均衡 | 数据越多越接近 50:50 |
| MDT 容量变化 | 34.4G→69.0G | 34.4G→69.0G | 同 | 机制一致 |

**对照结论（n=1，单次实测，谨慎）**：
1. **「到 AVAILABLE」几乎不随数据量变长**（+7%，落在轮询误差量级）——这段是扩容控制面/加 OST 操作，与已用数据量弱相关。**业务侧真正的「可用等待」两次都是 ~16 分钟。**
2. **「后台重分布」明显随数据量变长**（+18%）——要迁到新 OST 的老数据从 v1 的 ~361G 增到 v2 的 ~514G，搬得越多越久。这段**不阻塞使用**。
3. **数据越满，重分布后越接近 50:50**：v2 达 570:514（52.6% : 47.4%），比 v1 的 549:361（60% : 40%）更均衡——数据越多，条带/文件分摊越充分。

---

## OST 容量与数据分布变化（v2）

### 扩容前（1.2 TiB，单 OST，92% 满）
```
7tsb3b4v-MDT0000   34.4G   used 8.9M
7tsb3b4v-OST0000   1.1T    used 1.0T (1050G)  92%
summary            1.1T    used 1.0T          92%
```

### 扩容刚 AVAILABLE 时（2.4 TiB，2 OST，重分布刚开始）
```
7tsb3b4v-MDT0000   69.0G   used 9.2M
7tsb3b4v-OST0000   1.1T    used 1.0T (~1050G) 93%   ← 老数据仍全在原 OST
7tsb3b4v-OST0001   1.1T    used 107.8M         1%   ← 新增 OST，刚开始接收
summary            2.2T    used 1.0T          47%
```

### STORAGE_OPTIMIZATION 完成后（重分布均衡）
```
7tsb3b4v-MDT0000   69.0G   used 9.4M
7tsb3b4v-OST0000   1.1T    used 570.1G  50%   ← 迁走 ~480G
7tsb3b4v-OST0001   1.1T    used 514.0G  45%   ← 接收 ~514G
summary            2.2T    used 1.1T    48%
```

**观察**（与 v1 机制一致）：
1. **新容量靠新增 OST0001 实现**，不是撑大原 OST。
2. **老数据初始全留 OST0000**，扩容后 AWS 自动跑 STORAGE_OPTIMIZATION 把 ~514G 重分布到新 OST。
3. 重分布阶段 **Lifecycle 全程 AVAILABLE**，文件系统可正常读写。
4. v2 重分布后（570:514）比 v1（549:361）更接近 50:50。

---

## 时间线图

见 `lustre_expand_timeline_B_fill92.png`（含 v2 时间线 + v1/v2 耗时对照柱状 + v2 OST 分布前后对比）。

---

## 成本

| 项 | 说明 |
|---|---|
| FSx Lustre PERSISTENT_2 500 | 1.2→2.4 TiB，存活约 1.6 小时 |
| EC2 c6in.2xlarge | 约 1.6 小时 |
| 合计 | ≈ $5–7（符合预算），测完已清理 |

---

## 清理结果

- ✅ **terminate 灌数据 EC2** `i-099d95e58e85c3d79`
- ✅ **delete 本次新建 FSx Lustre** `fs-0f29a383fee84742e`
- ✅ SG `sg-08f2883d5c47ced16`（lustre-learn，复用）**未删**
- ✅ 伟伟保留的 learn Lustre `fs-026825936499d3bdb`（4800）**未动**

（清理命令与返回见报告末尾 / GitHub 提交记录。）

---

## 复现命令（关键步骤）

```bash
# 1. 创建 1.2 TiB Lustre
aws fsx create-file-system --file-system-type LUSTRE --storage-capacity 1200 \
  --subnet-ids subnet-0c551a33e366d52d4 --security-group-ids sg-08f2883d5c47ced16 \
  --lustre-configuration DeploymentType=PERSISTENT_2,PerUnitStorageThroughput=500 \
  --region us-east-2

# 2. AL2023 装 lustre-client（默认 repo 无 lfs 用户态工具，需 AWS FSx repo）
curl -s https://fsx-lustre-client-repo-public-keys.s3.amazonaws.com/fsx-rpm-public-key.asc | rpm --import -
curl -s https://fsx-lustre-client-repo.s3.amazonaws.com/al2023/fsx-lustre-client.repo -o /etc/yum.repos.d/aws-fsx.repo
dnf install -y lustre-client   # 2.15.6

# 3. 挂载
mount -t lustre -o relatime,flock <dns>@tcp:/<mountname> /mnt/fsx

# 4. 灌到 ~92% 满（先看 lfs df 剩余空间，别写爆）
lfs df -h /mnt/fsx
for i in $(seq 1 10); do dd if=/dev/urandom of=/mnt/fsx/big_$i.bin bs=1M count=102400 iflag=fullblock & done
dd if=/dev/urandom of=/mnt/fsx/topup.bin bs=1M count=51200 iflag=fullblock   # 追加至 ~92%

# 5. 扩容（计时核心）
aws fsx update-file-system --file-system-id <fsid> --storage-capacity 2400 --region us-east-2

# 6. 每 35s 轮询 Lifecycle + AdministrativeActions 直到 STORAGE_OPTIMIZATION COMPLETED
aws fsx describe-file-systems --file-system-ids <fsid> --region us-east-2 \
  --query 'FileSystems[0].{Life:Lifecycle,Cap:StorageCapacity,Actions:AdministrativeActions[].{T:AdministrativeActionType,S:Status,P:ProgressPercent}}'
```

---

## 关键结论速记

- **接近容量满（92%）时，扩容到 AVAILABLE 耗时几乎不变**（15.7→16.8 min，+1.1 min），因为这段主要是控制面加 OST。
- **后台数据重分布明显变长**（38.9→46.0 min，+7.1 min / +18%），因为要搬到新 OST 的老数据更多；**但这段不阻塞使用**。
- **扩容机制 = 加 OST**：新容量在新 OST（OST0001）上；老数据初始不动，靠后台重分布均衡。两版本机制一致。
- **数据越满，重分布后越接近 50:50**（v2 570:514 vs v1 549:361）。
- AL2023（kernel 6.18）**默认 repo 不含 lustre-client 用户态工具**，需 AWS FSx repo 安装（修正 v1 报告的说法）。

> ⚠️ 再次声明：以上均为**单次测试环境实测**，v1、v2 各 **n=1**，两点连线不构成统计规律，仅作方向性参考，不代表 AWS 官方性能承诺。扩容/重分布耗时会随数据量、容量、区域负载变化。
