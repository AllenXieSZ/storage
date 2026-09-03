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

---

## 批次 3：Q5–Q6（2026-09-03）

### Q5. 生命周期状态 + stop/suspend/reset/delete
**伟伟答**：provisioning、running、terminated;stop了硬盘/根系统/网络ip还要付费;suspend是保留内存状态可resume,stop内存清理了。

**① 对照**：✅ provisioning/running/terminated 对(是核心几个);✅✅ stop后硬盘+静态IP仍付费✓、suspend保留内存可resume✓、stop清内存✓——关键计费/数据判断都对;🔶 状态列全一点更好(还有STAGING/STOPPING(PENDING_STOP)/SUSPENDING/REPAIRING);⚠️**一个易错点:GCP把"停止"后的状态叫 TERMINATED(不是"stopped"!),但TERMINATED≠删除**(见下,这是GCP独特命名坑);🔶 suspend的内存"保留在哪+要不要收费"没说(要收费)。

**② 参考答案(GCP官方,已核实)**：
- **完整生命周期状态**:`PROVISIONING`(分配资源)→`STAGING`(准备启动/引导)→`RUNNING`(运行)→ 停止路径`STOPPING`/`PENDING_STOP`→**`TERMINATED`**;挂起路径`SUSPENDING`→`SUSPENDED`;修复`REPAIRING`。
  - ⚠️**GCP命名坑**:stop一个实例后状态显示 **`TERMINATED`**——但**这只是"已停止",实例定义还在、可再启动**,**不等于delete(删除)**!(AWS里terminated=删除,GCP里terminated=停止,极易混,面试常考)。
- **四个操作**:
  | 操作 | 做什么 | 状态 | vCPU/内存计费 | 数据/内存 |
  |------|--------|------|------|------|
  | **stop(停止)** | 关机 | TERMINATED | **不收**vCPU/内存 | 内存**清空**;PD保留;临时外部IP**释放**,静态IP保留 |
  | **suspend(挂起)** | 保存内存到磁盘后暂停 | SUSPENDED | **不收vCPU**,但**收保存内存的存储费** | **内存状态保存(存到PD standard)**,resume恢复现场 |
  | **reset(重置)** | 硬重启 | 保持RUNNING | 照常收 | 类似断电重启,**内存丢失**(非优雅);盘/IP不变 |
  | **delete(删除)** | 删实例 | (消失) | 停收 | 实例没了;启动盘按auto-delete决定删/留 |
- **计费通则(官方原话)**:**vCPU+内存**只在 RUNNING/PENDING_STOP/SUSPENDING/SUSPENDED 收(注意suspend期间内存仍算);**挂载的盘、外部IP等资源只要存在就一直收,与实例状态无关**。→ 所以stop了盘和静态IP照付(伟伟对)。

**③ 概念**:stop=关机省vCPU/内存钱但盘/静态IP照付(适合"暂时不用但要留着");suspend=把内存快照存盘、快速resume恢复现场(适合"想快速恢复工作状态",代价是内存存储费);reset=硬重启(卡死时用);delete=彻底删。**TERMINATED在GCP=已停止非删除**,是最大命名坑。

**④ AWS对照**:
| GCP | AWS EC2 | ⚠️ |
|-----|---------|----|
| stop→**TERMINATED**(已停止) | stop→**stopped** | **命名反直觉!AWS的terminate=删除,GCP的TERMINATED=停止** |
| suspend→SUSPENDED(存内存) | **hibernate(休眠)**(存内存到EBS) | 概念对应 |
| reset | reboot | 硬/软重启 |
| delete | **terminate** | GCP叫delete,AWS叫terminate |
👉 **最大坑:GCP `TERMINATED`=停止(可重启),AWS `terminated`=删除(不可逆)**。suspend↔hibernate,delete↔terminate,stop↔stop。

**⑤ 评分：7.5/10**。记忆点:状态PROVISIONING→STAGING→RUNNING→(STOPPING→**TERMINATED**)/(SUSPENDING→SUSPENDED);**⚠️GCP TERMINATED=已停止非删除(AWS terminated才是删除)**;stop不收vCPU/内存但盘+静态IP照付、内存清空、临时IP释放;suspend存内存到PD可resume但收内存存储费;reset硬重启;delete才是真删。

### Q6. stop 计费明细 + suspend vs stop
**伟伟答**：(见Q5)stop硬盘/根/网络IP付费;suspend保留内存可resume,stop清内存。

**① 对照**：✅✅ 全对:stop后付盘+IP、不付算力;suspend留内存、stop清内存。🔶 补三点:①stop不付的是vCPU+内存;②静态IP"未挂在运行实例上"才单独收(闲置静态IP收费);③**suspend要额外付"内存保存到PD"的存储费**(伟伟没提这点)。

**② 参考答案(GCP官方)**：
- **stop(TERMINATED)后**:
  - **不付**:vCPU、内存(实例算力费停收)。
  - **仍付**:①**挂载的持久盘/PD**(启动盘+数据盘,只要没删就按GB收);②**保留的静态外部IP**(⚠️注意:静态IP挂在运行实例上免费,但**实例停止后该静态IP变"未使用",会按闲置静态IP收费**);③其他附加资源(如已预留的额外IP)。
  - **临时(ephemeral)外部IP**:stop时**释放**,重启可能拿到新IP(所以要固定IP得用静态IP)。
- **suspend vs stop 区别**:
  | | stop | suspend |
  |--|------|---------|
  | 内存 | **清空丢弃** | **保存到 PD standard**(内存快照) |
  | 恢复 | 重新启动(冷启动,进程从头来) | **resume 恢复到挂起前现场**(内存/进程在) |
  | vCPU/内存费 | 都不收 | vCPU不收,**但收"保存内存"的PD存储费** |
  | 盘/静态IP | 照付 | 照付 |
  | 适用 | 暂时不用、省钱 | 想快速恢复运行状态(如保留会话/热缓存) |
  - **本质**:suspend像笔记本"睡眠(内存存盘)",stop像"关机(内存丢)"。suspend恢复快但要为存内存付存储费;stop更省(不存内存)但恢复是冷启动。

**③ 概念**:计费三分离——**算力(vCPU+内存):只RUNNING/suspend相关态收;盘/静态IP:存在即收(与开关机无关);内存快照:suspend独有的额外存储费**。想彻底不花钱=delete实例+删盘+释放静态IP。只stop仍会为盘和静态IP持续扣费(常见"停了机还扣钱"的困惑根源)。

**④ AWS对照**:
| | GCP | AWS EC2 |
|--|--|--|
| 停机不付算力、付盘 | stop(TERMINATED),付PD+静态IP | stop(stopped),付EBS+闲置EIP |
| 存内存快速恢复 | suspend(收内存存盘费) | **hibernate**(内存写EBS,收该EBS存储费) |
| 闲置公网IP收费 | 停止后静态IP闲置收费 | **Elastic IP 未关联运行实例时收费** |
👉 几乎完全一致:停机都省算力、都继续付盘、闲置公网IP都收费;suspend↔hibernate(都把内存存到块存储、都为此付存储费)。

**⑤ 评分：8/10**。记忆点:**stop不付vCPU/内存,但付PD盘+闲置静态IP,临时IP释放,内存清空;suspend保存内存到PD(可resume恢复现场)但要付内存存储费**;想零费用=delete+删盘+放静态IP;对标AWS stop(付EBS+闲置EIP)/hibernate(存内存)。

---

**批次 3 小结**：Q5=7.5、Q6=8,均分7.75。重点→**①⚠️GCP `TERMINATED`=已停止(可重启)≠删除(AWS terminated才是删除,delete↔terminate);状态链PROVISIONING→STAGING→RUNNING→TERMINATED/SUSPENDED ②stop不付vCPU/内存,付盘+闲置静态IP,临时IP释放,内存清空 ③suspend存内存到PD可resume但收内存存储费(≈AWS hibernate);想零费用=delete+删盘+放静态IP**。

---

## 批次 4：Q7–Q8（2026-09-03）

### Q7. public image / custom image / machine image 区别
**伟伟答**：公共=大家都能用来启动;自定义=自己装了driver做了配置;machine image是跟机型有关,看这个镜像支持什么机型。

**① 对照**：✅✅ 公共镜像=Google/社区维护的可直接启动OS镜像✓;✅✅ 自定义镜像=在启动盘上装了driver/做了配置后打包✓;❌ **machine image理解错了:它跟"机型/支持什么机型"无关**,而是"**整台VM的完整快照(含多块盘+配置+元数据+权限)**"(见下,重点纠正)。

**② 参考答案(GCP官方,已核实)**：
- **公共镜像(public image)**:Google、开源社区、第三方厂商提供并维护的**OS启动盘镜像**(如 Debian/Ubuntu/RHEL/Windows Server)。用来做启动盘、直接开VM。
- **自定义镜像(custom image)**:你在一个VM的**启动盘(单块boot disk)**上装好软件/驱动/配置后,打包成的**启动盘镜像**。本质=**一块启动盘的模板**,用于批量开"预装好环境"的VM(golden image)。伟伟"装driver做配置"对。
- **机器镜像(machine image)——纠正伟伟**:它**不是"跟机型/支持什么机型"**!官方定义:machine image = **存储一台VM实例的"全部配置 + 元数据 + 权限 + 多块磁盘(启动盘+所有数据盘)的数据"**,即**整台VM的完整快照**。
  - 用途:**备份/克隆/迁移整台VM**(尤其多盘VM),或复制一个完整实例到别处。
  - 和custom image关键区别:**custom image只存一块启动盘;machine image存整台VM(多盘+配置)**。
  - ⚠️和机型的关系:machine image会**记录源VM当时的machine type作为配置的一部分**,但**它不"绑定/限制"机型**——从machine image创建新VM时**可以改机型/其他配置**。所以"看支持什么机型"是误解:它不挑机型,只是把源VM配置(含机型)一起存了,可覆盖。
- 三者层级(存的范围):**snapshot(单盘数据)< custom image(单块启动盘,可做启动模板)< machine image(整台VM:多盘+配置+元数据+权限)**。

**③ 概念**:public image=拿来即用的OS;custom image=你的"黄金启动盘模板"(标准化批量开机);machine image=整台VM打包(含数据盘和配置,备份/搬迁整机首选)。选择:只要OS环境模板→custom image;要整机(多盘+设置)搬家/备份→machine image;只备份一块盘数据→snapshot。

**④ AWS对照**:
| GCP | AWS | 说明 |
|-----|-----|------|
| public image | 公共 **AMI** | 官方/市场OS镜像 |
| custom image(单启动盘) | **自定义 AMI**(可含多EBS映射) | 启动模板;AWS AMI本身可含多卷映射,语义略比GCP custom image宽 |
| machine image(整VM多盘+配置) | 最接近 **AMI + 实例配置** 组合;或 **EC2 Image Builder / CreateImage(含所有卷)** | AWS无单一"machine image"名,AMI(多卷)+launch template近似 |
| snapshot(单盘) | EBS snapshot | 单盘备份 |
👉 GCP把"启动盘模板(custom image)"和"整机快照(machine image)"分成两个东西;AWS的AMI(可含多卷)大致覆盖两者,配合launch template表达实例配置。**machine image ≠ 机型相关**,是整机快照。

**⑤ 评分：6/10**。⚠️扣在machine image理解错(以为跟机型相关)。记忆点:**public=Google/社区OS镜像;custom image=单块启动盘模板(装好环境批量开机);machine image=整台VM完整快照(多盘+配置+元数据+权限,备份/搬迁整机),与机型无关(可覆盖机型);范围:snapshot<custom image<machine image;对标AWS AMI**。

### Q8. instance template + 与MIG关系 + 能否修改
**伟伟答**：instance template=启动image和机型规格,用MIG自动扩展;(问)模板启动时候可以修改吗?

**① 对照**：✅✅ 模板=保存启动镜像+机型规格(等配置)✓、给MIG自动扩展用✓——核心对;🔥 好问题"能否修改":**不能——instance template是不可变(immutable)的**(见下,面试常考点)。

**② 参考答案(GCP官方,已核实)**：
- **instance template(实例模板)**:保存一份VM配置的资源,包含 **机型(machine type)、启动盘镜像、磁盘、网络、标签labels、启动脚本、服务账号、元数据** 等——一次定义,反复用它开出**配置一致**的VM。
- **和MIG的关系**:**MIG必须基于instance template创建**。MIG按模板批量开出相同实例,并做自动伸缩/自动修复/滚动更新。模板是MIG的"实例蓝图"。也可以直接用模板单独开单个VM。
- **能否修改(正面回答伟伟)**:**❌ 不能修改!instance template创建后是不可变(immutable)的**。要改配置只能:**新建一个模板**(或基于旧模板复制后改),然后:
  - 对MIG执行**滚动更新(rolling update)**,把MIG指向新模板 → MIG按新模板逐步替换实例。
  - 这种不可变设计是故意的:保证"同一模板开出的实例完全一致、可预测、可回滚"。
- 补充:有 **global(全局)** 和 **regional(区域)** 两种模板;deterministic template(确定性模板)会把"latest镜像"等解析成固定版本,保证长期可复现。

**③ 概念**:模板=不可变蓝图,配合MIG实现"声明式、一致、可回滚"的批量部署。改配置=换模板+滚动更新(而非原地改),这与"不可变基础设施(immutable infrastructure)"理念一致——不改运行中的东西,只用新版本替换。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 实例蓝图 | **instance template**(不可变) | **Launch Template**(可出**多个版本version**) / 旧的Launch Configuration(不可变) |
| 给谁用 | MIG | **Auto Scaling Group(ASG)** |
| 改配置 | 新建模板+滚动更新 | Launch Template**加新版本**+ASG刷新;LaunchConfiguration则须新建 |
👉 都用"模板+伸缩组"。差异:**GCP instance template不可变(改=新建)**,更像AWS老的Launch Configuration;**AWS Launch Template支持多版本(可加版本、指定用哪个版本)**,比GCP模板灵活一点。MIG↔ASG。

**⑤ 评分：8/10**。记忆点:instance template=不可变的VM配置蓝图(机型+镜像+盘+网络+脚本+SA);**MIG必须基于模板创建**;**模板不能改(immutable),改配置=新建模板+对MIG滚动更新**(不可变基础设施);有global/regional两种;对标AWS Launch Template(但AWS支持多版本,GCP不可变更像Launch Configuration),MIG↔ASG。

---

**批次 4 小结**：Q7=6、Q8=8,均分7。重点纠错→**①machine image=整台VM完整快照(多盘+配置+元数据+权限),与"机型/支持什么机型"无关(可覆盖机型);范围snapshot<custom image(单启动盘模板)<machine image;对标AWS AMI ②instance template不可变(immutable),改配置=新建模板+MIG滚动更新;MIG必须基于模板;对标AWS Launch Template(AWS支持多版本更灵活)/MIG↔ASG**。

---

## 批次 5：Q9–Q10（2026-09-03）

### Q9. 启动脚本 / 关机脚本 / cloud-init / OS Login
**伟伟答**：启动脚本=image启动运行的定制化脚本;关机脚本=关机前运行?放在user data?cloud-init是driver启动加载。

**① 对照**：✅ 启动脚本=开机运行的定制脚本✓;✅ 关机脚本=关机前运行✓(基本对);❌ **"user data"是AWS术语**——GCP叫**实例元数据(metadata)的特定key**(`startup-script`/`shutdown-script`);❌ **cloud-init不是"driver启动加载"**(是跨云VM初始化框架,理解错了,见下);🔶 漏了OS Login。

**② 参考答案(GCP官方,已核实)**：
- **启动脚本(startup script)**:VM**每次启动时**(不只首次!首次+每次reboot都跑)自动以root执行的脚本,用于装包/配置/拉代码/注册服务。**放在实例元数据**里,key = **`startup-script`**(直接塞脚本内容)或 **`startup-script-url`**(指向Cloud Storage的脚本)。
- **关机脚本(shutdown script)**:VM**在停止/删除/reset前**尽力(best-effort)执行的脚本,用于优雅关闭(排空连接、保存状态、上传日志)。key = **`shutdown-script`** / **`shutdown-script-url`**。⚠️**有时间限制**(正常关机约90秒、抢占约30秒),超时会被强杀;**不保证一定执行完**(如宿主机崩溃)。
- **⚠️不叫user data**:AWS EC2叫"user data";**GCP叫"instance metadata"**,启动/关机脚本是其中的**保留元数据key**。这是术语纠正。
- **cloud-init(纠正伟伟)**:**不是"driver启动加载"**!cloud-init是**业界通用的跨云VM首次启动初始化框架**(设主机名/建用户/写文件/装包/跑命令)。GCP部分镜像(如Container-Optimized OS、某些Ubuntu)支持用cloud-init配置;但GCE**原生机制是startup-script(通过guest agent执行)**,cloud-init是可选的另一套。两者都做"开机初始化",但startup-script是GCP原生、cloud-init是跨云标准。
- **OS Login**:GCP管理SSH登录的机制——**用IAM角色+Google账号身份来授权SSH到VM**(而非手工管authorized_keys)。开启后SSH权限由IAM统一控制(如`roles/compute.osLogin`),便于集中管理/审计/撤销。与启动脚本无直接耦合,是登录鉴权层。

**③ 概念**:startup/shutdown script=通过metadata下发、guest agent执行的"开机/关机自动化",实现无人值守配置;放metadata(GCP)而非user data(AWS)。cloud-init是可选的跨云init标准;OS Login是IAM驱动的SSH鉴权。理解:GCP用"元数据key下发脚本",AWS用"user data下发脚本",概念对应但名字不同。

**④ AWS对照**:
| GCP | AWS EC2 | 说明 |
|-----|---------|------|
| startup-script(metadata key) | **user data**(常配cloud-init) | 开机脚本;AWS user data默认只首次跑,GCP startup-script每次开机都跑(差异!) |
| shutdown-script | 无原生等价(靠ASG lifecycle hook/spot中断处理/自建systemd) | AWS无直接"shutdown-script"元数据,常用其它机制 |
| cloud-init | cloud-init(AWS广泛用) | 跨云通用,两家都支持 |
| OS Login(IAM管SSH) | **EC2 Instance Connect / SSM Session Manager**(IAM管SSH) | 都用IAM鉴权SSH |
👉 关键差异:①**GCP叫metadata不叫user data**;②**GCP startup-script每次boot都执行,AWS user data默认仅首次**(要每次跑需额外配);③GCP有原生shutdown-script,AWS无(靠lifecycle hook等);④OS Login↔Instance Connect/SSM。

**⑤ 评分：5.5/10**。⚠️扣在"user data"(GCP叫metadata)+"cloud-init是driver加载"(错,是跨云init框架)。记忆点:**启动/关机脚本放实例metadata的key(startup-script/shutdown-script,或-url指GCS),不叫user data(那是AWS)**;startup-script每次开机都跑(AWS user data默认仅首次);shutdown-script尽力执行有超时;cloud-init=跨云VM初始化框架(非driver);OS Login=IAM管SSH登录。

### Q10. 实例元数据 + metadata server 访问 + 常用项
**伟伟答**：元数据包括机型、ip、硬盘,通过metadata server下载。

**① 对照**：✅✅ 元数据含机型/IP/磁盘等实例信息✓、通过metadata server获取✓——核心对;🔶 漏了**访问必须带 `Metadata-Flavor: Google` 头**(关键,防SSRF);🔶 漏了最重要的用途之一:**取服务账号access token**(免密调GCP API);🔶 可补自定义元数据+域名/IP。

**② 参考答案(GCP官方,已核实)**：
- **实例元数据(instance metadata)**:每个VM可查询的键值信息,分两类:①**默认/项目/实例元数据**(Google提供的VM信息:机型、主机名、内外网IP、zone、project ID、磁盘、网络、维护事件等);②**自定义元数据**(你自己塞的key-value,含startup-script等)。
- **metadata server 访问方式(关键,伟伟漏了头)**:VM内访问 **`http://metadata.google.internal/computeMetadata/v1/...`**(或IP **169.254.169.254**),**必须带请求头 `Metadata-Flavor: Google`**,否则拒绝。例:
  ```
  curl "http://metadata.google.internal/computeMetadata/v1/instance/machine-type" -H "Metadata-Flavor: Google"
  ```
  - ⚠️这个头是**强制的安全设计**:防止SSRF——外部诱导应用发的普通请求(无此头)拿不到元数据,只有明确带头的本地代码能取。
  - 用 `?recursive=true` 可递归取整棵子树JSON。
- **常用元数据项**:
  - `instance/machine-type`、`instance/hostname`、`instance/zone`、`instance/network-interfaces/0/ip`(内网IP)、`.../access-configs/0/external-ip`(外网IP)、`instance/disks/`、`instance/attributes/`(自定义)。
  - `project/project-id`、`project/numeric-project-id`。
  - **🔑最重要:`instance/service-accounts/default/token`** —— 取当前VM绑定服务账号的**OAuth2 access token**,应用/SDK靠它**免密调用GCP API**(无需存密钥)。这是GCE安全模型的核心(不落地长期密钥)。
  - `instance/maintenance-event`(监听主机维护事件,配合优雅迁移/处理)。
  - `instance/preempted`(Spot VM是否被抢占)。

**③ 概念**:metadata server = VM本地的"配置+身份信息端点"(169.254.169.254链路本地地址,无需鉴权授权但要Metadata-Flavor头)。核心价值:①启动脚本/应用无需外部授权就能拿自身信息;②**取SA token免密调API(workload identity的基础)**;③监听维护/抢占事件做优雅处理。带头要求=防SSRF安全闸。

**④ AWS对照**:
| | GCP | AWS EC2 |
|--|--|--|
| 元数据端点 | metadata.google.internal / 169.254.169.254 | **169.254.169.254(IMDS)** |
| 防护头/机制 | 必须 **`Metadata-Flavor: Google`** 头 | **IMDSv2:先PUT取token再带`X-aws-ec2-metadata-token`**(防SSRF) |
| 取身份凭证 | service-accounts/default/token(SA的OAuth token) | iam/security-credentials/(IAM role临时凭证) |
👉 概念完全对应:都在169.254.169.254、都能取机型/IP/身份临时凭证、都为防SSRF加了防护(GCP靠固定头Metadata-Flavor,AWS靠IMDSv2的token握手)。SA token↔IAM role临时凭证(都实现"实例免密调API")。

**⑤ 评分：7/10**。记忆点:**metadata server访问必须带 `Metadata-Flavor: Google` 头(防SSRF),端点metadata.google.internal或169.254.169.254**;含机型/IP/zone/磁盘/自定义;**最关键项=service-accounts/default/token(取SA的OAuth token免密调GCP API)**;还有maintenance-event/preempted;对标AWS IMDS(IMDSv2 token防护)+ IAM role临时凭证。

---

**批次 5 小结**：Q9=5.5、Q10=7,均分6.25。重点纠错→**①启动/关机脚本放"实例metadata的key(startup-script/shutdown-script)",GCP不叫user data(那是AWS);startup-script每次开机都跑(AWS user data默认仅首次) ②cloud-init是跨云VM初始化框架,不是"driver加载";OS Login=IAM管SSH ③metadata server访问必须带`Metadata-Flavor: Google`头(防SSRF),最关键项=SA token(免密调API);对标AWS IMDSv2+IAM role凭证**。

> 💡伟伟追问:cloud-init是不是脚本?哪个路径查?怎么保证只运行一次(标志位/标志文件)? 答(官方核实):
> - **不是单脚本**,是Python写的初始化框架/守护(几个systemd服务分阶段拉起);你写的是**cloud-config(YAML)**,框架执行内置模块(建用户/写文件/装包/runcmd)。
> - **路径 `/var/lib/cloud/`**:`instance/`(软链→当前实例)、`instances/<instance-id>/`、`instance/user-data.txt`(用户数据);日志`/var/log/cloud-init.log`+`cloud-init-output.log`;配置`/etc/cloud/cloud.cfg(.d)`。
> - **只运行一次靠"semaphore信号量标志文件"(伟伟猜对了)**:每模块有frequency——**per-once**(永远一次,标志在`/var/lib/cloud/sem/`,不绑instance-id)/**per-instance**(每个instance-id一次,标志在`/var/lib/cloud/instances/<id>/sem/config_<模块>.<freq>`)/**per-always**(每次跑)。模块跑成功写semaphore文件标记;开机对比**instance-id**(记在`/var/lib/cloud/data/instance-id`):相同→per-instance跳过;不同(克隆出新VM)→重跑。`cloud-init clean`清标志强制重跑。
> - 对比:**GCE startup-script每次boot都跑(无semaphore,幂等要自己保证);cloud-init靠semaphore+instance-id天然per-instance只跑一次**。AWS也用同一个cloud-init(机制完全一样),user data默认仅首次正是per-instance语义。

---

## 批次 6：Q11–Q12（2026-09-03）

### Q11. MIG vs 非托管IG + MIG能力
**伟伟答**：MIG是同样模版、不同az,可以按压力资源扩展/收缩,能滚动升级。

**① 对照**：✅✅ 同一模板✓、跨az✓(regional MIG)、按压力伸缩✓、滚动升级✓——核心能力抓准;🔶 漏了**自动修复(autohealing)**;🔶 没正面答"vs非托管IG"的区别。补全:

**② 参考答案(GCP官方,已核实)**：
- **MIG(托管实例组)**:一组**基于同一instance template创建的相同(identical)VM**,作为单一实体管理。四大能力:
  1. **自动伸缩(autoscaling)**:按负载增/减实例(min/max)。
  2. **自动修复(autohealing)**:靠health check探测,不健康实例**自动重建**(伟伟漏了)。
  3. **滚动更新/金丝雀(rolling update/canary)**:换模板逐步替换实例。
  4. **高可用分布**:regional MIG把实例**跨同region多个zone**分布,单zone故障仍存活。
  5. (有状态可选)stateful MIG保留每实例的盘/IP/元数据。
- **非托管实例组(unmanaged IG)**:**一堆任意的、可以不同配置(异构)的现有VM**手动加进一个组,仅用于**给负载均衡当后端分组**。**无自动伸缩/无自动修复/无模板/无滚动更新**——纯手动管理。
- **核心区别**:MIG=模板化相同VM+全套自动化(伸缩/修复/更新/跨zone);unmanaged IG=手工凑的异构VM集合,只做LB后端,没有任何自动化。

**③ 概念**:MIG是GCP实现"弹性+自愈+滚动发布"的核心单位,声明式(定模板+min/max+策略),平台自动维持期望状态;unmanaged IG只是"把几台已有VM打个组"给LB用,适合异构/特殊场景。生产弹性一律用MIG。

**④ AWS对照**:
| GCP | AWS |
|-----|-----|
| **MIG** | **Auto Scaling Group (ASG)** |
| regional MIG跨zone | ASG跨多个AZ(subnet) |
| autohealing(health check重建) | ASG health check替换不健康实例 |
| unmanaged IG(异构VM给LB) | **直接把EC2注册到Target Group**(无ASG那套自动化) |
👉 MIG↔ASG(都模板化+伸缩+自愈+跨AZ);unmanaged IG≈手动把实例挂到LB Target Group。

**⑤ 评分：7.5/10**。记忆点:MIG=同模板相同VM+四大能力(**自动伸缩/自动修复autohealing/滚动更新canary/regional跨zone**);unmanaged IG=手工异构VM集合仅供LB后端(无自动化);MIG↔AWS ASG,unmanaged IG≈直接挂Target Group。

### Q12. MIG自动伸缩指标 + 对照ASG
**伟伟答**：可以按CPU、schedule、请求数、内存,和ASG类似。

**① 对照**：✅ CPU✓、schedule✓、请求数(=负载均衡serving capacity)✓、和ASG类似✓;⚠️ **"内存"——GCP autoscaler不原生支持内存指标!**(要靠自定义指标间接实现,见下,重点纠正)。

**② 参考答案(GCP官方,已核实)**：MIG autoscaler**原生支持4类伸缩信号**:
1. **CPU利用率(CPU utilization)**:最常用,设目标平均CPU%。
2. **负载均衡服务容量(load balancing serving capacity)**:按LB后端的利用率/每实例RPS(请求数)伸缩——伟伟"请求数"对应这个。
3. **Cloud Monitoring 指标(含自定义custom metric)**:按任意Monitoring指标伸缩(队列长度、Pub/Sub积压等)。
4. **计划(schedules)**:按时间表预置容量(如工作日9点预扩)。
- **⚠️内存不是原生指标(纠正伟伟)**:GCP autoscaler**没有"内存利用率"这个内置伸缩信号**。要按内存伸缩,得先用**Ops Agent把内存用量作为Cloud Monitoring自定义指标上报**,再用"Cloud Monitoring指标"方式对该自定义指标伸缩(第3类)。所以内存是"间接支持",不是原生开关。
- 可组合多信号(取最激进的扩容需求);有scale-in控制(冷却/稳定窗口防抖)。

**③ 概念**:GCP原生伸缩信号=CPU/LB容量/Monitoring指标/schedule四类;内存/业务指标走"自定义指标"路子。这与AWS一样:CPU是内置最常用,内存也不是CloudWatch的EC2默认指标(要装CloudWatch agent才有MemoryUtilization)——**两家都"CPU原生、内存需agent上报"**,这是常考对照点。

**④ AWS对照**:
| 伸缩依据 | GCP MIG autoscaler | AWS ASG |
|------|------|------|
| CPU | ✅原生(CPU utilization) | ✅目标追踪 ASGAverageCPUUtilization |
| 请求数/LB容量 | ✅LB serving capacity | ✅ ALBRequestCountPerTarget |
| 自定义/其它指标 | ✅Cloud Monitoring指标 | ✅CloudWatch自定义指标(目标追踪/步进) |
| 定时 | ✅schedule | ✅scheduled action |
| **内存** | ❌非原生,需Ops Agent上报自定义指标 | ❌非原生,需CloudWatch agent上报MemoryUtilization |
👉 高度一致(CPU/请求/自定义/定时都有);**关键共同点:内存两家都不是原生伸缩指标,必须靠agent上报自定义指标**。GCP用Cloud Monitoring指标,AWS用CloudWatch指标。

**⑤ 评分：7.5/10**。⚠️扣在"内存"当原生指标(实际需自定义指标)。记忆点:MIG原生4类伸缩信号=**CPU利用率 / 负载均衡serving capacity(请求数) / Cloud Monitoring指标(自定义) / schedule**;**内存非原生,须Ops Agent上报自定义指标后按Monitoring指标伸缩(AWS同理,须CloudWatch agent)**;MIG autoscaler↔ASG目标追踪/步进/定时策略。

---

**批次 6 小结**：Q11=7.5、Q12=7.5,均分7.5。重点→**①MIG=同模板相同VM+四大能力(自动伸缩/自动修复autohealing/滚动更新canary/regional跨zone);unmanaged IG=手工异构VM仅供LB后端(无自动化);MIG↔ASG ②MIG原生伸缩4类=CPU/LB serving capacity(请求)/Cloud Monitoring指标/schedule;⚠️内存非原生(须Ops Agent上报自定义指标),AWS同理(须CloudWatch agent)**。

---

## 批次 7：Q13–Q14（2026-09-03）

### Q13. MIG autohealing 判断不健康的机制 + 与LB健康检查的区别
**伟伟答**：怎么判断实例不健康,是不是通过ping、CPU负载?

**① 对照**：❌ **不是ping/CPU负载!**(重点纠正)——autohealing用的是**应用级健康检查(application-based health check)**,探测你的应用本身(HTTP/HTTPS/TCP/SSL);ping通、CPU不高但应用挂了照样算不健康。下面给完整机制。

**② 参考答案(GCP官方,已核实)**：
- **autohealing判据 = 应用级 health check(不是ping/CPU)**:你配一个health check,定期向实例发探测:
  - **HTTP/HTTPS**:请求某路径(如`/healthz`),要求返回**200**(可校验响应体);
  - **TCP/SSL**:能否建连到某端口。
  - 连续失败达阈值(unhealthy threshold)→判定不健康 → **MIG重建(recreate)该实例**(不是重启,是按模板重新造一台)。
  - ⚠️**ping(ICMP)/CPU负载都不是判据**:ping只说明网络通、机器活着,证明不了"应用能正常服务";CPU高低更不代表健康(高CPU可能正忙、低CPU可能进程已死)。**autohealing要的是"应用层面能正确响应"**——所以用HTTP/TCP探测,不用ping/CPU。这是伟伟的主要误区。
  - **initial delay(初始延迟)**:autohealing有启动宽限期,给应用足够时间boot起来再开始探测,避免刚启动就被误判重建。
- **和负载均衡(LB)健康检查是不是同一个?——不是同一用途(重点)**:
  | | autohealing health check | LB health check |
  |--|--|--|
  | 作用 | 不健康→**重建VM(recreate)** | 不健康→**停止转发流量到该VM**(不重建) |
  | 后果严重性 | 高(直接干掉重造) | 低(只是不发流量,VM还在) |
  | 官方建议 | **用单独、更保守(更宽松)的health check** | 可以更敏感 |
  - **虽然都用"health check"这类资源,但强烈建议用两个不同的检查**:autohealing的检查要保守(阈值宽松、延迟足够),否则**瞬时抖动就大面积重建实例=雪崩**;LB检查可敏感些(快速摘流量)。
  - 二者可独立存在:可只配LB health check不autoheal,也可只autoheal不接LB。

**③ 概念**:autohealing=应用级探测失败就"重造实例"实现自愈,关键是探"应用真能服务"(HTTP 200/TCP连通),而非机器活着(ping)或忙不忙(CPU)。与LB健康检查分工:LB管"流量走不走",autoheal管"要不要换机器"。保守配autoheal检查是生产铁律,防误判雪崩。

**④ AWS对照**:
| | GCP MIG | AWS ASG |
|--|--|--|
| 自愈健康检查 | 应用级health check(HTTP/TCP)→重建 | **ASG health check**:EC2状态检查 或 **ELB health check(应用级)**→替换实例 |
| 判据 | 非ping/CPU,是HTTP/TCP探测 | EC2 status check(底层)或ELB探测(应用级);同样非CPU |
👉 概念一致:都靠"应用级探测(HTTP/TCP)"判定不健康并**替换/重建**实例,都不是靠ping或CPU。AWS ASG可选"EC2 status check"(底层健康)或"ELB health check"(应用健康),后者对应GCP的应用级检查。

**⑤ 评分：4/10**。⚠️主要扣在"ping/CPU判断健康"这个误区(实际是应用级HTTP/TCP health check)。记忆点:**autohealing靠应用级health check(HTTP返200 / TCP连通),不是ping/CPU!失败→重建VM(recreate);有initial delay防误判**;**与LB health check不同用途(LB=摘流量不重建;autoheal=重建),建议autoheal用更保守的单独检查防雪崩**;对标AWS ASG(ELB health check应用级→替换实例)。

### Q14. zonal MIG vs regional MIG + 默认分布 + AWS对照
**伟伟答**：zonal实例在同一个az,regional跨az;AWS没有这么区分。

**① 对照**：✅✅ zonal MIG单zone、regional MIG跨zone✓——核心对;🔶 没说regional默认"均匀跨zone分布(evenly)"和推荐用途;⚠️ **"AWS没有这么区分"不完全准**:AWS ASG默认就跨多AZ(相当于GCP的regional行为),只是命名上AWS不分"zonal/regional两种ASG",而是靠"给ASG配几个子网(AZ)"决定——见下纠正。

**② 参考答案(GCP官方,已核实)**：
- **zonal MIG**:所有实例在**单个zone**。该zone故障→整组不可用。适合:zone内批量、对HA要求不高、或需要实例都在同一zone(如配合zonal资源)。
- **regional MIG**:实例**跨同一region内的多个zone(默认3个)分布**。单zone故障时其他zone的实例继续服务→**高可用**。**默认分布=均匀(EVEN,`target-distribution-shape=EVEN`)**,MIG尽量把实例平均分到各zone(如6实例/3zone≈每zone 2个);伸缩时也尽量维持均衡。**生产推荐用regional MIG**(GCP官方默认建议)。
  - 其它分布形态:BALANCED(优先可用容量,允许不均)、ANY(最大化可获得性,不强求均匀)、EVEN(严格均匀)。
- **AWS对照纠正**:**AWS ASG本身就设计为跨多AZ**——你在创建ASG时指定多个子网(每个子网属一个AZ),ASG默认**跨这些AZ均衡分布实例(AZ balancing)**,单AZ挂了在其他AZ补。所以:
  - **AWS没有"zonal ASG / regional ASG"这种显式两分命名**,但**功能上ASG默认≈GCP regional MIG(跨AZ均衡HA)**;
  - 想要"单zone"就给ASG只配一个AZ的子网(≈GCP zonal MIG)。
  - 所以伟伟"AWS没有这么区分"**部分对**:AWS确实没有这个命名区分,但**能力上AWS ASG跨AZ均衡=GCP regional MIG的默认行为**,并非AWS缺这个能力。

**③ 概念**:regional MIG跨zone分布是GCP做计算层HA的核心手段(单zone故障容忍),默认均匀分布(EVEN);zonal MIG局限单zone。GCP把这做成"两种MIG类型"显式选择;AWS则把它内建进ASG(配几个AZ子网就跨几个AZ),不单列类型。终点一样:跨AZ/zone分散实例扛单点故障。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 单zone组 | **zonal MIG** | ASG只配1个AZ子网 |
| 跨zone组(HA) | **regional MIG**(默认EVEN跨zone) | **ASG配多AZ子网**(默认AZ均衡) |
| 是否显式两分 | 是(zonal/regional两种) | 否(靠子网数决定,内建跨AZ) |
👉 能力对等(都能跨AZ均衡做HA);差异仅命名/配置方式:**GCP显式分zonal/regional MIG,AWS靠ASG配几个AZ子网(默认跨AZ均衡)**。伟伟"AWS不这么区分"指命名对,但别理解成"AWS没有跨AZ HA能力"。

**⑤ 评分：7/10**。记忆点:**zonal MIG=单zone;regional MIG=跨同region多zone(默认3个)均匀分布(EVEN),单zone故障仍可用,生产推荐**;分布形态EVEN/BALANCED/ANY;**AWS对照:无"zonal/regional"命名两分,但ASG默认跨多AZ均衡(配几个AZ子网决定)=功能等价GCP regional MIG**(伟伟"AWS不区分"仅指命名,非缺能力)。

---

**批次 7 小结**：Q13=4、Q14=7,均分5.5。重点纠错→**①⚠️autohealing靠应用级health check(HTTP返200/TCP连通)判不健康,不是ping/CPU!失败→重建VM;与LB health check不同(LB摘流量不重建),autoheal建议用更保守的单独检查防雪崩;对标AWS ASG ELB health check ②zonal MIG单zone/regional MIG跨zone(默认EVEN均匀,生产推荐);AWS无zonal/regional命名两分但ASG默认跨多AZ均衡=功能等价(伟伟"不区分"仅指命名)**。

> 💡伟伟类比:GCE health check是不是像K8s的health check、探一个路径URL? 答:**完全正确,同一套设计**。
> - 探测:GCE HTTP/TCP/SSL ↔ K8s httpGet/tcpSocket/exec/gRPC;都探路径URL,HTTP返2xx算活。
> - 参数对应:check-interval↔periodSeconds、healthy/unhealthy-threshold↔success/failureThreshold、**initial delay↔initialDelaySeconds/startupProbe**。
> - **两种检查的对应(重要)**:**autohealing HC ↔ liveness probe**(不活→重建VM / 重启容器);**LB HC ↔ readiness probe**(没就绪→只摘流量不重建)。上批"两个HC用途不同"就是K8s的liveness vs readiness。
> - 差异:K8s探**容器**(失败重启Pod,秒级);GCE探**VM**(失败重建整机,分钟级,代价大)→GCE autoheal更要保守阈值+足够initial delay防雪崩。
> - AWS同构:ALB/NLB Target Group HC↔readiness(摘流量);ASG用ELB HC↔liveness(替换实例)。三家在"探路径判健康"上完全一致。

---

## 批次 8：Q15–Q16（2026-09-03）

### Q15. MIG滚动更新/金丝雀 + maxSurge/maxUnavailable
**伟伟答**：滚动更新跟kubernetes类似,升级一个下线一个;金丝雀是发布几个没问题再继续;maxSurge...

**① 对照**：✅✅ 滚动更新类比K8s✓、金丝雀=先发少量验证再全量✓——理解准确;🔶 maxSurge/maxUnavailable只提了名字没展开,补全。

**② 参考答案(GCP官方)**：
- **滚动更新(rolling update)**:给MIG指定**新instance template**,MIG**逐步(分批)用新模板替换旧实例**,不停机平滑升级。你说"升级一个下线一个"对(具体节奏由下面两参数控制)。
- **maxSurge(最大超出)**:更新期间**允许临时超出目标实例数的数量/百分比**——即可以**先多开几台新实例再删旧的**(容量不掉,先加后减)。例:目标10、maxSurge=3 → 最多同时存在13台。
- **maxUnavailable(最大不可用)**:更新期间**允许同时不可用(被删/正在替换)的实例数/百分比**——控制"最多能少几台"。例:目标10、maxUnavailable=2 → 任意时刻至少8台在服务。
- **两者配合控制升级节奏与容量**:
  - `maxSurge>0, maxUnavailable=0` → **先加后删**(全程容量不低于目标,零容量损失,但要额外配额/成本);
  - `maxSurge=0, maxUnavailable>0` → **先删后加**(不超配额,但升级时容量临时下降);
  - 两者都>0 → 混合,更快。
- **金丝雀(canary)**:滚动更新的一种模式——用**两个版本共存**,给新模板设一个**较小的目标数量(如`--canary-version ... template=NEW,target-size=2`)**,只让**一小部分实例跑新版**,观察无问题后再把**全部**滚到新版。伟伟"发布几个没问题再继续"完全对。
- 更新可选**PROACTIVE(主动立即滚)**或**OPPORTUNISTIC(机会式,仅在扩容/重建时才用新模板,不主动替换)**。

**③ 概念**:滚动更新=分批换模板不停机;maxSurge(先加)与maxUnavailable(允许少几台)是"容量 vs 配额/成本"的权衡旋钮;canary=先小流量验证再全量,降低发布风险。与K8s Deployment的rollingUpdate(maxSurge/maxUnavailable同名同义)几乎一模一样。

**④ AWS对照**:
| | GCP MIG | AWS |
|--|--|--|
| 滚动更新 | rolling update(换模板) | **ASG Instance Refresh**(换Launch Template) |
| maxSurge/maxUnavailable | 同名参数 | Instance Refresh的**minHealthyPercentage**(类似maxUnavailable反向) / 或CodeDeploy | 
| 金丝雀 | canary(双版本+小目标数) | CodeDeploy canary/linear、或ASG分批 |
| 同源概念 | ≈K8s Deployment rollingUpdate | ≈K8s |
👉 三家(K8s/GCP/AWS)滚动更新思路一致;**GCP的maxSurge/maxUnavailable和K8s Deployment完全同名同义**;AWS用Instance Refresh的minHealthyPercentage表达类似约束。

**⑤ 评分：8/10**。记忆点:滚动更新=分批换模板不停机;**maxSurge=可临时多开几台(先加后减,保容量);maxUnavailable=允许同时少几台(先减后加,省配额)**;canary=新模板设小目标数先验证再全量;PROACTIVE vs OPPORTUNISTIC;与K8s Deployment同名同义,AWS对应Instance Refresh。

### Q16. Spot VM vs Preemptible VM + 回收/最长运行时间(伟伟让查最新)
**伟伟答**：spot便宜但会被回收,退出有grace time;preemptible不会回收自己终止;spot取消了最长时间限制(让查最新文档)。

**① 对照**：✅ spot便宜、会被回收、退出有grace(preemption notice)✓;✅✅ **"spot没有最长时间限制"✓(查证成立)**;❌ **"preemptible不会回收、自己终止"说反了**——preemptible**既会被回收,又额外有24小时硬上限自动终止**(见下,重点纠正)。

**② 参考答案(GCP官方,已查最新核实)**：
- **两者共同点**:都是用**Google空闲容量**跑的**深度折扣(约60–91% off)**VM;**容量紧张时都会被抢占(preempted=停止/终止)**;抢占前都给**preemption notice(抢占通知)**+ ACPI关机信号,让你优雅处理(checkpoint、保存、摘流量)。
- **Preemptible VM(旧,legacy)**:
  - **有24小时硬性最长运行上限**:官方原话"preemptible VMs can only run for **up to 24 hours** at a time"——**即使没被容量抢占,满24小时也会被Compute Engine自动终止**。
  - **会被回收**(容量需要时随时抢占)。→ 伟伟"不会回收、自己终止"**错**:它**又会被回收、又有24h自动终止**,两个都有。
- **Spot VM(新,推荐)**:
  - **没有最长运行时间限制**(官方原话"Spot VMs **don't have a maximum runtime** unless you limit the runtime")——可跑数天/数周,直到Google需要容量才抢占。**伟伟"取消了最长时间限制"方向对**(准确说:Spot本就没有24h上限,是比Preemptible更新的模型;Preemptible才有24h)。
  - 同样会被抢占,同样有通知。**Google推荐新工作负载一律用Spot**(Preemptible仅为向后兼容保留)。
- **抢占通知(grace/notice)时长**:默认 **30秒**;可设 **120秒(Preview)**——给需要更长时间收尾的工作负载。通知通过metadata(`instance/preempted`=TRUE)+系统关机信号下发,配合shutdown-script做优雅退出。
- **核心区别小结**:
  | | Preemptible(旧) | Spot(新,推荐) |
  |--|--|--|
  | 最长运行 | **24小时硬上限**(到点自动终止) | **无上限** |
  | 被容量抢占 | 会 | 会 |
  | 折扣 | ~60-91% | ~60-91% |
  | 通知 | 30秒 | 30秒(可120秒Preview) |
  | 定位 | legacy | 现役推荐 |

**③ 概念**:Spot是Preemptible的升级替代——去掉了24h硬上限、机制更灵活,同样便宜同样可被抢占。都适合**容错/无状态/可checkpoint/可重试**的工作(批处理、渲染、CI、Spot GKE节点池)。设计要点:checkpoint+重试+跨zone分散+留少量on-demand baseline。伟伟"preemptible不会回收"是最大误区:它照样被回收,还多个24h自杀。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 折扣可抢占实例 | Spot VM / (旧)Preemptible | **EC2 Spot Instance** |
| 最长运行 | Spot无上限;Preemptible 24h | EC2 Spot无固定上限(可设duration,早期有Spot Blocks已弃) |
| 抢占通知 | 30秒(可120s Preview) | **EC2 Spot 2分钟中断通知(interruption notice)** |
👉 GCP Spot ↔ AWS EC2 Spot(都空闲容量、深折扣、可被抢占、给通知)。差异:**通知时长GCP默认30秒(可120s),AWS是2分钟**;GCP有个旧的Preemptible(24h上限)已被Spot取代,AWS无"24h硬上限"这种旧型。

**⑤ 评分：6/10**。⚠️主要扣在"preemptible不会回收、自己终止"(说反:它既会被回收、又有24h硬上限自动终止)。记忆点:**Spot(新,推荐)无最长运行限制;Preemptible(旧)有24小时硬上限到点自动终止;两者都会被容量抢占、都~60-91%折扣、都给抢占通知(默认30秒,可120秒Preview)**;对标AWS EC2 Spot(但AWS通知是2分钟,无24h旧型);设计=checkpoint+重试+跨zone。

---

**批次 8 小结**：Q15=8、Q16=6,均分7。重点纠错→**①滚动更新分批换模板不停机;maxSurge=可临时多开(先加后减保容量)/maxUnavailable=允许同时少几台(先减后加省配额);canary=新模板小目标数先验证;与K8s Deployment同名同义,AWS↔Instance Refresh ②⚠️Preemptible(旧)既会被抢占回收、又有24h硬上限自动终止(伟伟"不回收"说反了);Spot(新推荐)无最长运行限制;都~60-91%折扣+抢占通知(默认30秒/可120秒);对标AWS EC2 Spot(AWS通知2分钟)**。
