# GCP Compute Engine (GCE) 练习题 —— 批改与知识点沉淀

> 配套题库：`./QA_ZH.md`（30 题，每批 2 题）
> 每批批改后追加并推送 GitHub。
> 结构：①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点。
> 范围：机型系列 / 生命周期 / 镜像模板 / MIG自动伸缩 / Spot / 折扣CUD-SUD / 维护实时迁移 / GPU / Sole-tenant / 网络SA安全 / 计费优化 / AWS EC2 对照。
> 铁律：回答先查 GCP 官方文档核实；不确定标注；旧缺点须查最新文档验证是否仍成立。

（批改从批次 1 开始追加。）

---

## 批次 1：Q1–Q2（2026-09-03）

### Q1. GCE 机型系列（machine family）分类 + 典型系列/场景
**伟伟答**：类型有通用、内存、网络、存储优化、高性能;有没有mac实例(AWS有)?

**① 对照**：✅ 通用、内存优化 对;❌ **GCE没有"网络优化""存储优化"独立机型系列**(多答了);🔶 "高性能"应叫**计算优化(compute-optimized)**;❌ 漏了第四大类**加速优化(accelerator-optimized)**;🔥 好问题:**GCE没有Mac实例**(AWS有EC2 Mac,GCP没有,见下)。

**② 参考答案(GCP官方,已核实)**：GCE机型系列**只有4大类**:
| 家族(family) | 定位 | 典型系列 | 场景 |
|------|------|----------|------|
| **通用 General-purpose** | 性价比均衡,最广用 | **E2**(低成本)、**N1/N2/N2D/N4**、**C4/C4A(Axion Arm)**、**Tau T2D/T2A** | Web/应用服务器、中小DB、开发测试 |
| **计算优化 Compute-optimized** | 最高单核性能 | **C2/C2D、C3/C3D** | 高性能计算HPC、游戏服务器、高单线程 |
| **内存优化 Memory-optimized** | 超高内存:vCPU比 | **M1/M2/M3、X4** | SAP HANA、大型内存数据库、内存分析 |
| **加速优化 Accelerator-optimized** | 挂GPU/TPU | **A2(A100)、A3(H100)、G2(L4)** | AI训练/推理、ML、大规模并行 |
- ⚠️注意:GCP用**machine family(家族)→machine series(系列,如N2)→machine type(具体规格,如n2-standard-4)** 三级划分。
- **没有独立的"网络优化""存储优化"family**(这是伟伟记混了AWS的分类,AWS也没有纯"网络优化"family,有的是网络增强/存储优化如I系/D系)。GCE高网络/高存储通过具体系列+加Local SSD/更高带宽档实现,不单列family。
- 🍎 **Mac实例**:**GCE不提供macOS/Apple硬件实例**。**AWS有EC2 Mac(mac1 Intel / mac2 Apple M系列,dedicated host形式,专给iOS/macOS开发编译)**。要在云上跑macOS,AWS(EC2 Mac)是主流选择,GCP没有对应产品。伟伟这个"AWS有Mac"记得准,GCP确实没有。

**③ 概念**:GCE按"资源配比+处理器"分family;通用是默认;compute-optimized给单核性能;memory-optimized给内存密集(HANA);accelerator给AI。选型先定family(看瓶颈:均衡/算力/内存/GPU),再选series(看代际/处理器:Intel/AMD/Arm),再定type(具体vCPU/内存)。

**④ AWS对照**:
| GCP family | AWS 类别 | 对应例 |
|------|------|------|
| 通用 E2/N/C4A | General purpose | M系(m7i)、T系(t3突发)、Arm(m7g Graviton) |
| 计算优化 C2/C3 | Compute optimized | **C系(c7i/c7g)** |
| 内存优化 M1/M2/M3 | Memory optimized | **R系(r7i)、X系(x2)高内存** |
| 加速优化 A2/A3/G2 | Accelerated computing | **P系(p5)、G系(g6)GPU** |
| （无） | **EC2 Mac(mac1/mac2)** | GCP无对应 |
👉 四大类基本一一对应(通用/计算/内存/加速);差异:**AWS多一个EC2 Mac(GCP没有)**;AWS还有存储优化(I/D系,本地NVMe/HDD密集),GCP用系列+Local SSD覆盖不单列。

**⑤ 评分：5/10**。⚠️扣在"网络/存储优化"误列 + 漏加速优化 + "高性能"用词。记忆点:**GCE只有4大family=通用(E2/N)/计算优化(C2/C3)/内存优化(M系,HANA)/加速优化(A/G,GPU)**;三级=family→series→type;**GCE无Mac实例,AWS有EC2 Mac**;对标AWS M/T→C→R/X→P/G。

### Q2. predefined vs custom machine type + 限制
**伟伟答**：预定义是内存和vCPU配比固定、不断增加规格;自定义是内存和vCPU自己定义,限制应该有比例上限下限。

**① 对照**：✅✅ 预定义=固定配比、按档递增✓;✅ 自定义=自选vCPU/内存✓;✅✅ "有比例上下限"✓——判断准确(确实有per-vCPU内存的上下限);🔶 可补具体数值(每vCPU内存范围、vCPU须偶数、扩展内存extended memory突破上限)。

**② 参考答案(GCP官方,已核实)**：
- **预定义机型(predefined)**:GCP预设好的固定 vCPU+内存 组合,按档定价。分标准/高CPU(highcpu)/高内存(highmem)/大内存(megamem)等子档:
  - `n2-standard-4`(4vCPU/16GB,约4GB/vCPU)、`n2-highcpu-4`(4vCPU/4GB,省内存)、`n2-highmem-4`(4vCPU/32GB,多内存)。伟伟"配比固定、递增规格"对。
- **自定义机型(custom)**:自己指定vCPU数和内存,不用迁就预设档,精确匹配负载省钱。**限制(伟伟"有上下限"对)**:
  1. **vCPU数**:通常必须是**1 或偶数**(>1时偶数);有系列上限。
  2. **每vCPU内存范围(核心限制)**:有**下限和上限**,按系列不同。经典N系列约**0.9–6.5 GB/vCPU**;较新如N4D为**0.5–8 GB/vCPU**;内存必须是**256MB的整数倍**。
  3. **扩展内存(extended memory)**:若要**超过"每vCPU内存上限"**(如每vCPU>6.5GB),可启用extended memory突破比例上限,但**超出部分单独更高价计费**。
  4. 不是所有系列都支持自定义(E2/N1/N2/N2D等支持;部分系列不支持)。
- **总结**:自定义不能"任意乱设",受 vCPU须偶数 + 每vCPU内存上下限 + 256MB增量 约束;要突破内存上限走extended memory(加价)。

**③ 概念**:预定义=省心、有承诺折扣、覆盖大多数场景;自定义=避免"为了内存被迫买多余vCPU"(或反之)的浪费,精确rightsizing省钱。每vCPU内存上下限是为匹配底层硬件配比;extended memory是给"内存远大于常规配比"(如内存DB)开的口子,但加价。自定义机型也享受SUD/CUD折扣。

**④ AWS对照**:
| | GCP | AWS EC2 |
|--|--|--|
| 固定规格 | predefined machine type | 固定instance type(m7i.large等) |
| 自选vCPU/内存 | **custom machine type(GCP特色)** | **EC2无真正自定义**(只能从固定type里选);略近的是**Fargate/Lambda**按需配 |
👉 **重要差异:GCP有custom machine type(自选vCPU+内存),这是GCP相对AWS的一个特色**;AWS EC2只能从预设instance type选,没有"任意配vCPU+内存"的等价物(Graviton/各系列虽多但仍是固定档)。所以"精确配比省钱"是GCP卖点之一。

**⑤ 评分：8/10**。记忆点:预定义=固定vCPU/内存档(standard/highcpu/highmem);自定义=自选,但受**vCPU偶数+每vCPU内存上下限(如N系0.9–6.5GB、N4D 0.5–8GB)+256MB增量**约束,超内存上限用**extended memory(加价)**;**custom machine type是GCP特色,AWS EC2无等价(只能选固定type)**。

---

**批次 1 小结**：Q1=5、Q2=8,均分6.5。重点纠错→**①GCE只有4大family:通用/计算优化(C2/C3)/内存优化(M系HANA)/加速优化(A/G GPU),没有"网络/存储优化"family;三级=family→series→type ②🍎GCE无Mac实例,AWS有EC2 Mac ③custom machine type是GCP特色(AWS无),自定义受vCPU偶数+每vCPU内存上下限+256MB增量约束,超上限用extended memory加价**。
