# FSx for Lustre — Metadata IOPS 与 MDT 数量关系实测

实证 Amazon FSx for Lustre 的 **provisioned metadata IOPS** 与底层 **MDT（Metadata Target）
数量** 的对应关系：逐档提升 metadata IOPS（3000 → 12000 → 24000 → 36000），
每档挂载后用 `lfs df -i` / `lfs mdts` 数 MDT 数量。

> 环境标识（文件系统 ID / subnet / SG / 实例 ID / DNS / mountname）已脱敏为 `REDACTED`。

## 背景与动机

在之前一个 6PB Lustre + S3 DRA warmup 的案例中观察到某文件系统有 **16 个 MDT**，
且 HSM restore 由 **每个 MDT 一个 Coordinator** 调度——MDT 数量直接决定 warmup 并行度。
于是想搞清楚：**FSx Lustre 的 metadata IOPS 到底和 MDT 数量是什么关系？是不是每 N IOPS 加一个 MDT？**

官方文档没有直接给出"每多少 IOPS 一个 MDT"的公式，所以直接实测。

官方文档：
- Managing metadata performance
  https://docs.aws.amazon.com/fsx/latest/LustreGuide/managing-metadata-performance.html

官方文档确认的事实：
- Metadata IOPS 合法档位（SSD）：**1500, 3000, 6000，然后 12000 的倍数，最高 192000**。
- Automatic 模式：**每 24 TiB 存储 = 12000 metadata IOPS**。
- ⚠️ Metadata IOPS **只能升不能降**；两次升配至少间隔 **6 小时**。
- 升配几分钟内生效，期间文件系统可能短暂不可用（客户端透明重试）。

## 环境

| 项 | 值 |
|---|---|
| 服务 | FSx for Lustre, PERSISTENT_2 |
| 容量 | 1200 GiB SSD, PerUnitStorageThroughput 250 |
| Metadata 模式 | USER_PROVISIONED（必须建时指定，才能后续调整）|
| 起始 Metadata IOPS | 3000 |
| 挂载 | Lustre client（同 AZ/子网的 EC2）|

关键：**要能后续调整 metadata IOPS，创建时必须指定 `MetadataConfiguration`（USER_PROVISIONED）。**
建时不指定 metadata 配置的文件系统，之后无法添加或修改 metadata 配置。

## 操作命令

### 创建（起始 IOPS=3000，非默认，为后续可调）

```bash
aws fsx create-file-system \
  --region REDACTED \
  --file-system-type LUSTRE \
  --storage-capacity 1200 --storage-type SSD \
  --subnet-ids REDACTED --security-group-ids REDACTED \
  --lustre-configuration '{"DeploymentType":"PERSISTENT_2","PerUnitStorageThroughput":250,"MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":3000}}'
```

### 挂载 + 数 MDT

```bash
sudo mkdir -p /mnt/fsxexp
sudo mount -t lustre -o relatime,flock <DNS>@tcp:/<mountname> /mnt/fsxexp

# 数 MDT 数量（两种方法）
sudo lfs df -i /mnt/fsxexp     # 每个 MDTxxxx_UUID 一行
sudo lfs mdts  /mnt/fsxexp     # 直接列出 ACTIVE 的 MDT
```

### 逐档升配 metadata IOPS（每次至少隔 6 小时）

```bash
aws fsx update-file-system --region REDACTED --file-system-id REDACTED \
  --lustre-configuration '{"MetadataConfiguration":{"Mode":"USER_PROVISIONED","Iops":12000}}'
# 等 AdministrativeActions 里 FILE_SYSTEM_UPDATE 状态 COMPLETED，再重新 lfs df -i 数 MDT
# 依次升到 24000、36000（每档之间等 6 小时冷却）
```

### 查升配进度

```bash
aws fsx describe-file-systems --region REDACTED --file-system-ids REDACTED \
  --query 'FileSystems[].AdministrativeActions[?AdministrativeActionType==`FILE_SYSTEM_UPDATE`]'
```

## 实测结果

| Metadata IOPS | MDT 数量 | 单 MDT inode 容量（示例）| 备注 |
|---|---|---|---|
| 3000（起始）| **1** | ~12,438,986 | 单 MDT |
| 12000 | **1** | ~102,020,624 | MDT 数不变，单 MDT inode ↑约 8 倍 |
| 24000 | **2** | 各 ~1.0–1.07 亿 | 加第 2 个 MDT（MDT0000+MDT0001）|
| 36000 | **3** | 各 ~1.0 亿 | 加第 3 个 MDT（MDT0000+0001+0002）|

`lfs mdts` 在 36000 IOPS 时输出：
```
MDTS:
0: <fs>-MDT0000_UUID ACTIVE
1: <fs>-MDT0001_UUID ACTIVE
2: <fs>-MDT0002_UUID ACTIVE
```

## 结论

1. **FSx Lustre metadata IOPS ↔ MDT 数量 ≈ 每 12000 IOPS 一个 MDT**（从 12000 档起线性）：
   - IOPS ≤ 12000 → 始终 **1 个 MDT**
   - 24000 → **2 个**，36000 → **3 个**，依此类推
   - 推断最大 192000 IOPS = **16 个 MDT**（与之前 6PB 案例观察到的 16 MDT 吻合）

2. **≤12000 的低档（1500/3000/6000/12000）都是单 MDT**，性能提升靠给单个 MDT 扩容量/算力
   （实测单 MDT inode 从 3000 档的 ~1240 万 涨到 12000 档的 ~1.02 亿，约 8 倍），MDT 数量不变。

3. **12000 是单 MDT 的满配档**；要拿到更多 MDT 并行度，IOPS 必须跨过 12000 的整数倍。

4. **对 HSM warmup / 元数据密集场景的启示**：Lustre HSM restore 由"每 MDT 一个 Coordinator"调度，
   想要多个 Coordinator 并行，metadata IOPS 至少配到 **24000+**（才有 ≥2 个 MDT），
   并配合 `lfs setdirstripe -c N` 在数据导入前把文件铺到多个 MDT 上。

## 注意事项

- **metadata IOPS 只能升不能降，且升配后计费永久增加**——实验/生产都要谨慎，测完及时删。
- 两次升配之间至少间隔 **6 小时**（FSx Lustre metadata 特有冷却，与 EBS 无关）。
- 升配几分钟生效，`lfs df -i` 需在 COMPLETED 后再数，才能看到新增的 MDT。
- 数 MDT 用 `lfs df -i` 或 `lfs mdts` 最直接；`lctl dl` 在部分执行环境下拿不到输出。
