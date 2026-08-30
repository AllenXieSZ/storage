# DataSync → FlexVol→FlexGroup 转换阻塞：真正根因定位实验

> 实验日期：2026-08-30 | 区域：us-east-2 | ONTAP 9.18.1P5 | FSxN Gen2 SINGLE_AZ_2
> 执行：storage-bench 子 agent | 任务：datasync-snapmirror-rootcause
> **本结论仅代表本次测试环境实测结果，不代表官方结论。**

---

## 一、结论先行

**在本次干净受控实验中，AWS DataSync（NFS 模式）传输后，FlexVol → FlexGroup 就地转换成功，没有被 "copy to cloud relationship" 阻塞。**

三个假设的实测裁定：

| 假设 | 内容 | 裁定 | 依据 |
|---|---|---|---|
| **H1** | DataSync 传输会在源卷创建 SnapMirror / copy-to-cloud 关系或 backup 快照 | **❌ 证伪** | 传输前后 `snapmirror show` / `list-destinations` / `snapshot show` **完全一致（全空）**，snapshot-count 始终为 0 |
| **H2** | 转 2 HA pair 后再转 FlexGroup 会报错（阻塞来自 2HA 结构） | **❌ 证伪** | 扩 2HA 后依旧无任何 snapmirror 关系；conversion check-only 只有 warning 无 error；实际转换 `[Job 61] Job succeeded` |
| **H3** | 阻塞与 DataSync 无关 | **✅ 本次支持** | 走过 DataSync（NFS）+ 2HA 扩展的卷，转换照样成功 |

**一句话**：走 NFS 协议的 DataSync **不留任何 SnapMirror/快照痕迹**，也不阻塞 FlexGroup 转换。之前 fs-0ab60 被阻塞的真正原因**不是"DataSync 这个动作本身"**（详见第五节讨论）。

---

## 二、实验设计

按 HANDOFF 的 7 步严格执行，每步记录命令+输出+耗时。核心是**对照 DataSync 传输前(步骤2) vs 后(步骤4)** 源卷的 snapmirror / snapshot 状态。

**为什么用 NFS 模式？** 查 AWS DataSync 官方文档确认：
> "DataSync can connect to an FSx for ONTAP file system's SVM and copy data by using the Network File System (NFS) or Server Message Block (SMB) protocol."
> —— https://docs.aws.amazon.com/datasync/latest/userguide/create-ontap-location.html

即 DataSync 对 FSx ONTAP 走的是**文件协议（NFS/SMB）**，不是 SnapMirror。本实验用 NFS3 传输，正是要验证"文件协议传输"是否会遗留 SnapMirror。

---

## 三、环境与资源

| 资源 | ID | 配置 |
|---|---|---|
| 源 FSxN | fs-027217e10840009de | Gen2 SINGLE_AZ_2, 起步 1HA / throughput **1536** MB/s / storage 2048GB |
| 目标 FSxN | fs-07695c839cde46696 | Gen2 SINGLE_AZ_2, 1HA / 1536 / 1024GB |
| 源 SVM / 卷 | srcsvm / **srcvol** (FlexVol, /srcvol, UNIX, 512GB) | 转换对象 |
| 目标 SVM / 卷 | dstsvm / dstvol (FlexVol, /dstvol) | DataSync 目标 |
| 灌数机 EC2 | i-09d530edb2544dc9a | c6i.large, AL2023, ohio key, SSM |
| SG | sg-07e321ff528ced7b0 | VPC 内全通 + ssh |

私网不通 → 全程 SSM RunShellScript 驱动 EC2 → sshpass `ssh -tt` 连 ONTAP CLI（fsxadmin）。

---

## 四、逐步实测记录

### 步骤 1 — 灌数据
源卷 NFS3 挂载，`dd if=/dev/urandom` 写 **100 个文件 × 100MiB = 9.9G**。
```
WROTE 100 files in 52s
100
9.9G	/mnt/src/data
```

### 步骤 2 ⭐ — DataSync 传输【前】基线（diag 级）
```
snapmirror show                → This table is currently empty.
snapmirror list-destinations   → This table is currently empty.
snapmirror show-history        → There is no SnapMirror history.
volume snapshot show srcvol    → There are no entries matching your query.
snapshot-count                 → 0
```
**基线：无任何 SnapMirror 关系，无任何快照。**

### 步骤 3 — DataSync 传输（NFS3）
source location(源SVM /srcvol, NFS3) + dest location(目标SVM /dstvol) + task(VerifyMode=POINT_IN_TIME_CONSISTENT)。
```
Status:           SUCCESS
BytesTransferred: 10485760000  (10 GiB)
FilesTransferred: 102
BytesWritten:     10485760000
```
**传输总 wall time = 156s**（其中 LAUNCHING ~5.5min 属于 DataSync 托管资源冷启开销，实际 TRANSFERRING→VERIFYING→SUCCESS 仅约 35s；10G 小数据远快于之前 800G=40.5min）。

### 步骤 4 ⭐ — DataSync 传输【后】复查（与步骤2对照）
```
snapmirror show                → This table is currently empty.   （与传输前一致）
snapmirror list-destinations   → This table is currently empty.   （一致）
snapmirror show-history        → There is no SnapMirror history.  （一致）
volume snapshot show srcvol    → There are no entries matching.   （一致）
snapshot-count                 → 0                                （一致）
```
加宽查询（含 XDP/DP/RST/LS/TDP/STDP 全类型 + SVM 级 snapshot）依旧全空。
**→ DataSync（NFS）传输后源卷零变化：无 SnapMirror、无 backup 快照。H1 证伪。**

### 步骤 5 — 源扩 1→2 HA pair
throughput 已是 1536，直接 `update-file-system HAPairs=2, storage 2048→4096`。
```
HA EXPAND wall time: 670s (~11 min)   （落在之前实测 10–26min 区间内）
扩完：HAPairs=2, aggr1 + aggr2 两个 aggregate
再查 snapmirror/snapshot → 依旧全空
srcvol 仍在 aggr1, 仍是 FlexVol
```
**→ 扩 2HA 未引入任何 copy-to-cloud 关系。H2 证伪。**

### 步骤 6 ⭐ — 转 FlexGroup（diag 级）
**check-only：**
```
Conversion ... can proceed with the following warnings:
* ...not be possible to change it back to a flexible volume.  (不可逆)
* ...will not add additional resources for capacity...        (需 volume expand)
```
**只有 warning，无 error。没有出现 "copy to cloud relationship" 报错。**

**实际转换：**
```
[Job 61] Job is queued: Converting flexible volume to FlexGroup.
[Job 61] Renaming volume.
[Job 61] Job succeeded: success
```
转换后：
```
volume-style=flex, is-flexgroup=TRUE, aggr-list=aggr1, snapshot-count=1
唯一快照：convert.2026-08-30_033055 (9.81GB)  ← 转换动作自建的常规快照，非 DataSync backup 快照
snapmirror show → 仍然全空
```

---

## 五、关键讨论：那和之前 fs-0ab60 被阻塞矛盾吗？

**不矛盾，而是澄清了根因归属。** 之前（2026-08-28）把阻塞归给"DataSync 用 SnapMirror-to-Cloud"，本实验**推翻了这个具体归因**：

- 走 **NFS 模式**的 DataSync，实测**不建任何 SnapMirror、不留 backup 快照**（步骤2 vs 4 逐条对照全空），也**不阻塞**转换（步骤6 成功）。
- 因此"只要当过 DataSync source 就一定被 copy-to-cloud 阻塞"这个结论**在本次 NFS 场景下不成立**。

**那之前的阻塞从何而来？** 本实验不能直接证明旧 FS 的根因（旧 FS 环境已不同），但可缩小范围。之前被阻塞的 fs-0ab60 与本次的差异点（候选真凶，待后续单独验证）：
1. **旧 FS 可能开过 FSx 原生 Backup（AWS Backup / 每日自动备份）** —— FSx ONTAP 的原生备份底层确实用 SnapMirror-to-Cloud，会在卷上留客户 CLI 看不见的隐藏关系 + `backup-xxx` 参考快照。**这才是最可能的真凶**，与"DataSync"无关。
2. 旧 FS 可能开过 **capacity tiering / FabricPool**。
3. 旧实验里"看到 backup-xxx 快照"很可能来自①的 FSx 原生备份，被误记到了 DataSync 头上。

> ⚠️ 上述第五节第 2 段是**基于本实验缩小范围后的推断（标注：待验证）**，不是本次实测直接结论。本次实测直接结论只有第一节的三条裁定。

---

## 六、耗时对比（WHY_FAST_SLOW）

| 操作 | 本次实测 | 之前实测 | 是否一致 |
|---|---|---|---|
| 灌 10G / 100 文件 | 52 s | — | — |
| DataSync 传输 (10G) | 156 s (实际传输+校验~35s) | 参考 800G=40.5min | ✅ 小数据远快，符合预期 |
| 扩 HA pair 1→2 | **670 s (~11 min)** | ~10–26 min | ✅ 落在区间内 |
| FlexVol→FlexGroup 转换 | **< 1 min** ([Job] succeeded) | < 1 min | ✅ 一致（改元数据，不搬数据） |

原理（沿用 fsxn-flexgroup-rebalance/WHY_FAST_SLOW.md）：
- **转 FlexGroup 秒级** = 只改卷类型元数据（WAFL 数据块原地不动），NetApp 官方称 in-place、不复制数据。
- **扩 HA 分钟级** = AWS 后台真 provision 一对新物理文件服务器 + 新 aggregate。

---

## 七、原始命令与日志

`logs/` 目录下逐步原始输出：
- `step2_pre_datasync.txt` — 传输前基线
- `step4_post_datasync.txt` / `step4b_post_datasync_broad.txt` — 传输后复查（关键对照）
- `step5_post_ha_expand.txt` — 扩 2HA 后复查
- `step6a_conversion_checkonly.txt` — 转换 check-only（只有 warning）
- `step6b_conversion_start.txt` — 实际转换（Job succeeded）
- `step6c_final_state.txt` — 转换后终态（is-flexgroup=true）

---

## 八、资源处置

**全部保留**（ROLE.md 铁律 + 伟伟已确认预算保留），删除前需伟伟确认。资源清单见 `RESOURCES.md`。

预估成本：2 个最小 FSxN（源扩到 2HA/4096）+ 1 台 c6i.large + 10G DataSync，跑约 1 小时，约 $3–6 量级。
