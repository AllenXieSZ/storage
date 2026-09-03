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

---

## 批次 2：Q3–Q4（2026-09-03）

### Q3. E2 vs N 系列 + 共享核心
**伟伟答**：共享核心是不是超卖了,会不会性能不好? AWS也有vCPU对应几个物理核的概念。

**① 对照**：✅✅ "共享核心是超卖"——**直觉基本正确**(shared-core是分数vCPU+突发,底层超卖共享物理核);✅ "AWS也有vCPU对物理核的概念"✓(见Q4);🔶 没正面答E2 vs N的定位区别和E2为何便宜。下面补全。

**② 参考答案(GCP官方,已核实)**：
- **E2 系列(成本优化 cost-optimized)**:GCP最便宜的通用系列。特点:①**不绑定特定CPU平台**(Google动态调度到Intel/AMD多种底层CPU,资源利用率高→成本低);②**不支持挂GPU/Local SSD、不支持实时迁移到指定CPU**等高级特性;③标准E2:2–32 vCPU,0.5–8 GB/vCPU。适合Web、微服务、开发测试、成本敏感的常规负载。
- **N 系列(N1/N2/N2D/N4,均衡 balanced)**:通用主力,性能更稳更可预测。N2=Intel,N2D=AMD EPYC,N1=老一代。支持更高性能、Local SSD、更多特性,单价比E2高。适合生产DB、稳定性能要求的应用。
- **为什么E2更便宜(关键机制)**:E2靠**灵活调度+资源超卖(把多个VM的vCPU映射到共享物理资源,统计复用)**提升利用率,把省下的成本让给用户。代价=**性能可预测性不如N系(可能有轻微邻居干扰、不保证固定CPU型号)**。
- **共享核心(shared-core: e2-micro/small/medium)**:
  - 这些是**分数vCPU(fractional vCPU)**:e2-micro=0.25 vCPU、e2-small=0.5、e2-medium=1(官方0.25–1 vCPU区间)。
  - **机制=突发型(burstable)**:给一个**baseline保证算力**,空闲时攒credit,忙时可**短时突发**到更高(甚至接近整核),但**持续高负载会被限回baseline**。
  - **是"超卖/共享"没错**:多个共享核心VM复用同一物理核,平时够用、成本极低;**但不适合持续高CPU负载**(会被限速)——伟伟"会不会性能不好"问得对:**低负载/间歇性负载(小网站、代理、轻量后台、dev)性能没问题且超便宜;持续满载会掉到baseline,不适合**。
  - 场景:e2-micro还是GCP**免费层(free tier)**机型。

**③ 概念**:E2 = 用"灵活调度+超卖"换低价,牺牲一点性能确定性;N系 = 稳定可预测性能。共享核心 = 突发模型(baseline+burst credit),把碎片算力卖给低负载场景,极致省钱但满载受限。选型:成本敏感/常规负载→E2;要稳定性能/生产DB→N2;超轻量/间歇→共享核心e2-micro/small。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 成本优化通用 | **E2** | 无完全等价(E2的"跨CPU灵活调度"较独特);理念近似通用低价 |
| 突发/共享核心 | **shared-core E2(e2-micro/small/medium)** | **T系列(t3/t4g)突发实例**(CPU credit模型) |
| 稳定均衡通用 | **N2/N2D/N4** | **M系列(m7i/m7g)** |
👉 **共享核心E2 ≈ AWS T系突发实例**(都是baseline+credit突发、超卖、便宜、不适合持续满载);E2整体理念≈AWS通用低价,但E2"不绑CPU平台灵活调度"是GCP特色。

**⑤ 评分：7/10**(答的是提问但方向准)。记忆点:**E2=成本优化(灵活调度+超卖换低价,不绑CPU平台,不支持GPU/Local SSD);N系=稳定可预测通用(N2 Intel/N2D AMD)**;**共享核心e2-micro/small/medium=分数vCPU(0.25/0.5/1)突发模型(baseline+credit),确实超卖共享,低负载超省钱、满载被限,对标AWS T系突发实例**。

### Q4. vCPU / 物理核 / 超线程 / 关SMT的影响
**伟伟答**：(问)关闭超线程对性能有什么影响?

**① 对照**：🔶 伟伟以提问为主,没作答vCPU定义。下面给完整参考答案 + 正面回答"关超线程的影响"。

**② 参考答案(GCP官方,已核实)**：
- **vCPU定义**:GCE里**每个vCPU = 一个硬件线程(hardware multithread)**,**默认2个vCPU共享1个物理核(physical core)**——即启用了**同步多线程SMT(Intel叫超线程Hyper-Threading)**。所以"4 vCPU"通常=**2个物理核×2线程**。
- **超线程(SMT/HT)**:一个物理核跑2个硬件线程,靠填充核内空闲执行单元提升吞吐——但两线程**共享同一核的执行资源/缓存**,并非等于2个独立核。
- **为什么支持关超线程(threads-per-core=1)**:设为1 → **每个vCPU独占一个完整物理核**(不再2线程共享),vCPU数减半但每个更"纯"。
- **关超线程的性能影响(正面回答伟伟)**:
  - **利**:①消除同核两线程的资源争抢 → 对**计算密集/HPC/浮点/科学计算**这类"吃满执行单元"的负载,单线程性能更稳更高、抖动更小;②**按物理核授权的商业软件(如某些数据库License按core计费)**可省license;③安全上减少跨线程侧信道风险。
  - **弊**:**总逻辑CPU数减半 → 高并发/多线程可并行的吞吐型负载(如Web并发、批处理)总吞吐可能下降**(少了一半可调度线程)。
  - 结论:**计算密集/延迟敏感/按核授权 → 关SMT有利;高并发吞吐型 → 保留SMT更好**。不改计费(仍按vCPU数×... 具体看机型,关SMT后vCPU数变化影响配置但Google按分配的vCPU计)。
- ⚠️共享核心E2(e2-micro等)和部分机型不支持自定义threads-per-core。

**③ 概念**:vCPU=线程不是核(2vCPU=1核是默认);SMT提升吞吐但两线程抢核内资源;关SMT=1线程独占核→单线程更强、并行度减半。这是"吞吐 vs 单线程性能/隔离"的权衡。AWS/GCP同理。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| vCPU=线程 | 是(2vCPU/核默认) | **完全相同**(1 vCPU=1线程,2vCPU/核) |
| 关超线程 | threads-per-core=1 | **CPU Options: `--threads-per-core 1`**(几乎同名) |
👉 **两家概念完全一致**(伟伟"AWS也有vCPU对物理核的概念"对):vCPU都=硬件线程、默认2线程/核、都能关超线程(GCP threads-per-core / AWS CPU Options threads-per-core)。用途也一样(HPC/按核License/隔离)。

**⑤ 评分：待伟伟补答(本题以提问为主)**。记忆点:**vCPU=1个硬件线程,默认2vCPU共享1物理核(SMT/超线程)**;关SMT(threads-per-core=1)→每vCPU独占整核:**计算密集/单线程/按核License受益,高并发吞吐型可能降(逻辑CPU减半)**;AWS概念完全相同(CPU Options threads-per-core)。

---

**批次 2 小结**：Q3≈7、Q4以提问为主(参考答案已给)。重点→**①E2=成本优化(灵活调度+超卖换低价,不支持GPU/Local SSD);共享核心e2-micro/small/medium=分数vCPU突发(baseline+credit),确实超卖,低负载超省钱满载被限,对标AWS T系 ②vCPU=1硬件线程,默认2vCPU/物理核(SMT);关超线程→单线程/HPC/按核License受益、高并发吞吐降;AWS概念完全一致(threads-per-core)**。
