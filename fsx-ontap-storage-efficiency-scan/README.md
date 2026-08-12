# FSx for NetApp ONTAP — Storage Efficiency 存量数据（scan-old-data）实测

验证 **FSx ONTAP volume 先写入数据、后开启 Storage Efficiency 时，存量数据的压缩/去重行为**，并给出对存量数据启用压缩去重的命令与实测结果。

> 结论先行：**inline（实时）Storage Efficiency 只处理开启之后的新写入，不会自动处理已经存在的存量数据。** 要对存量数据做去重/压缩/压紧，必须手动运行一次后台扫描命令 `volume efficiency start -scan-old-data true`。

---

## 背景：ONTAP Storage Efficiency 三项技术

Storage Efficiency (SE) = **compression（压缩）+ compaction（压紧）+ deduplication（去重）**，官方称通用文件共享最高可省 65% 容量。全部作用在 **4 KiB WAFL 物理块层级**（不是文件层级）：

| 技术 | 作用 |
|---|---|
| Compaction | 把多个 <4KB 的零碎块合进 1 个 4KB 物理块 |
| Deduplication | 对每个 4KB incoming write 去重（写入 <4KB 时去重率差） |
| Compression | inline 默认 8KB compression group；冷数据可调 32KB group（更省但费 CPU/IOPS） |

**执行时机分两种（关键）：**
- **inline**：写盘前在内存中完成，实时 —— **只对新写入生效**
- **background（后台）**：写盘后在 SSD 层周期性运行的 efficiency job —— **存量数据靠它，但不会自动对"开 SE 之前就存在的数据"回溯，需手动触发 scan-old-data**

官方依据：
- AWS FSx ONTAP — *Managing storage capacity*（SE = compression + compaction + dedup，最高省 65%）
- AWS FSx ONTAP — *Managing storage efficiencies* <https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/manage-vol-SE.html>

---

## 实验一：对照实验（efficiency ON+scan vs OFF）

### 环境
- FSx ONTAP 文件系统（us-east-2），通过跳板 EC2 SSH 进 ONTAP CLI + NFS v3 挂载
- 卷 `thick_vol`（10GB，junction `/thick_vol`）
- 测试数据：6×200MB 文件（5 个完全相同 + 1 个全单字符填充）→ 既高度可压缩又完全重复，放大 SE 效果

### 结果

| 阶段 | logical used | volume used（物理） | 总节省 | 节省率 |
|------|------|------|------|------|
| A 组 efficiency **ON** + 写 1.2GB 全 'A' + `efficiency start -scan-old-data true` | 1.18GB | **43.45 MB** | 1.14GB | **96%** |
| B 组 efficiency **OFF** + 写 1.2GB 全 'B' | 2.36GB | **1.18GB** | 1.17GB | 50%（全来自 A 组存量） |

### 结论
1. **efficiency 真的能关**：`volume efficiency off` 后 State=Disabled，Compression / Inline-Compression / Inline-Dedupe / Data-Compaction **全部 false**。
2. **`volume efficiency off` 连带关压缩**（不只是 dedup）——实测 compression 也变 false。
3. **disable 后新写入不再省空间**：B 组 1.2GB 重复+可压缩数据，物理几乎全额占用（used 43MB→1.18GB，增量≈1.18GB），0 节省。
4. **disable 不影响存量**：A 组已优化的 43MB 没有膨胀回去。

---

## 实验二：存量数据 scan-old-data 专项验证（核心）

**目的**：坐实"先写数据、后开 SE，存量数据不会被自动处理，必须手动 scan"。

### 环境
- 独立卷 `se_test_vol`（SVM `se-svm`）
- **~9 GB 存量数据**，数据构成：1×全零文件 + 4×相同文件（去重收益最大化）
- **顺序：先写入 9GB 数据 → 之后才开启 Storage Efficiency**

### 步骤与观察

**① 开 SE 后、扫描前的基线（关键证据）**
```
volume show -vserver se-svm -volume se_test_vol \
  -fields used,logical-used,sis-space-saved,dedupe-space-saved,compression-space-saved
```
观察：
```
used            = 9.05 GB
logical-used    = 9.05 GB        # used == logical，无任何缩减
dedupe-space-saved      = 0
compression-space-saved = 0
sis-space-saved         = 0
```
→ **证实：SE 后开，inline 只管新写入，对 9GB 存量数据零处理。**

**② 手动触发存量扫描（启动压缩/去重存量处理的命令）**
```
volume efficiency start -vserver se-svm -volume se_test_vol -scan-old-data true
```

**③ 扫描完成后结果（46 分钟，处理 9GB；384 MBps 最小吞吐档后处理较慢）**
```
volume show -vserver se-svm -volume se_test_vol \
  -fields used,logical-used,dedupe-space-saved,compression-space-saved,sis-space-saved-percent
```
观察：
```
used                     = 4.09 GB        # 9.05GB → 4.09GB，物理省 ~55%
dedupe-space-saved       = 8 GB           # ✓ 去重生效
compression-space-saved  = 0             # ✗ 压缩未生效（原因见下）
logical-used             = 12.09 GB       # 去重后逻辑引用重算变大
```

### 结果解读
- **去重 ✓ 生效**（省 8GB）：数据是 1×全零 + 4×相同文件，去重收益最大。
- **压缩 ✗ 未生效**（0）：该卷后处理 **Compression=false**（只开了 inline compression），`scan-old-data` 跑的是**去重 + compaction**；且数据已被去重消重，几乎没有剩余可压缩空间。
- **物理 used 下降 55%**，`logical-used` 反而升高 —— 去重把重复块合并后，逻辑引用计数重算所致，属正常。

---

## 命令速查

### 启动存量数据的压缩/去重（对已存在数据生效的关键命令）
```bash
# ONTAP CLI（进入文件系统的 fsxadmin 会话后执行）
volume efficiency start -vserver <SVM> -volume <VOLUME> -scan-old-data true
```
⚠️ **坑（ONTAP 9.17 实测）**：`volume efficiency start` **不支持 `-compression` / `-dedupe` 参数**（会报 *invalid argument*），只能带 `-scan-old-data true`。存量扫描会执行卷当前已启用的效率策略（去重 / compaction；压缩需卷的后处理 Compression=true 才会跑）。

### 查看进度 / 状态
```bash
volume efficiency show -vserver <SVM> -volume <VOLUME>
```

### 查看节省量（关键字段）
```bash
volume show -vserver <SVM> -volume <VOLUME> -fields \
  used,logical-used,physical-used,\
  sis-space-saved,sis-space-saved-percent,\
  dedupe-space-saved,compression-space-saved
```

### 开启 / 关闭 Storage Efficiency
```bash
# FSx 原生（推荐，三项一起开关）
aws fsx update-volume --volume-id <fsvol-xxx> \
  --ontap-configuration StorageEfficiencyEnabled=true   # 或 false

# ONTAP CLI 细粒度
volume efficiency on  -vserver <SVM> -volume <VOLUME>
volume efficiency off -vserver <SVM> -volume <VOLUME>    # ⚠️ 会连带关压缩；关前先 stop
volume efficiency stop -vserver <SVM> -volume <VOLUME>
```

---

## 关键结论（TL;DR）

1. **先写数据、后开 SE → 存量数据不会自动压缩/去重**（inline 只处理新写入）。
2. **对存量数据启用压缩/去重的命令**：`volume efficiency start -scan-old-data true`。
3. **该命令不接受 `-compression`/`-dedupe` 参数**，跑的是卷当前已启用的效率策略。
4. 去重是否有效取决于数据重复度；压缩是否有效取决于卷的后处理 Compression 是否为 true + 数据可压缩性 + 是否已被去重吃掉空间。
5. `volume efficiency off` 会连带关压缩，且不影响已优化的存量数据。

> 本文所有数字均为实测（非推测）。IP / 文件系统 ID / 凭证等已脱敏，请用你自己的环境值替换 `<SVM>` / `<VOLUME>` / `<fsvol-xxx>`。
