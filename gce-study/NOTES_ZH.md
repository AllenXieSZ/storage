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
