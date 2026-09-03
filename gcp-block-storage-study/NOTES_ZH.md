# GCP 块存储 练习题 —— 批改与知识点沉淀

> 配套题库：`./QA_ZH.md`
> 每批（2 题）批改后追加并推送 GitHub。
> 结构：①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点。
> 范围：Persistent Disk / Hyperdisk / Local SSD / 快照 / 加密 / 性能 / AWS EBS 对照。

（批改从批次 1 开始追加。）

---

## 批次 1：Q1–Q2（2026-09-02）

### Q1. Persistent Disk 类型

**伟伟答**：Balanced通用,Extreme高性能数据库,Standard性能一般web。

**① 对照**：✅ balanced通用/extreme数据库/standard一般 三定位对;❌ 漏pd-ssd(四种只答三种);❌ 没说清介质(standard=HDD其余SSD)和性能梯度;🔶 漏pd-extreme可自定义IOPS。

**② 参考答案(GCP官方文档已核实介质)**：
| 类型 | 介质(官方原文) | 定位 | 场景 |
|------|------|------|------|
| pd-standard | **HDD**("Uses standard hard disk drives (HDD)") | 低成本吞吐型 | 顺序I/O/日志/冷数据/dev-test |
| pd-balanced | **SSD** | 通用均衡(控制台默认) | 大多数通用/启动盘/中型DB |
| pd-ssd | **SSD** | 高性能通用 | 企业应用/高性能DB(更低延迟更高IOPS) |
| pd-extreme | **SSD** | 最高性能**可provision IOPS** | 高端数据库(SAP HANA),限部分机型 |
- 性能梯度:standard(HDD)<balanced<ssd<extreme。
- ⚠️默认坑(官方):**控制台默认pd-balanced,但gcloud CLI/API默认pd-standard(HDD)**——命令行建盘不指定类型给HDD,性能差。
- ⚠️趋势(官方):最新机型系列已不支持PD,**Google主推Hyperdisk**。

**③ 概念**:standard是HDD(便宜吞吐尚可但IOPS低延迟高),其余SSD;balanced是默认推荐性价比款;pd-extreme"自定义IOPS"是Hyperdisk性能容量解耦的前身;PD性能随容量增长(官方"performance increases with size")。

**④ AWS对照**:
| GCP | 介质 | 对标EBS |
|-----|------|---------|
| pd-standard | HDD | st1/sc1 |
| pd-balanced | SSD | gp3/gp2 |
| pd-ssd | SSD | gp3~io1/io2间 |
| pd-extreme | SSD可自定义IOPS | io1/io2 |
👉 梯度=HDD(standard)→通用SSD(balanced/ssd)→预置IOPS SSD(extreme),对标st1/sc1→gp2/gp3→io1/io2。

**⑤ 评分：6/10**。记忆点:四种=standard(HDD吞吐)<balanced(SSD通用默认)<ssd(SSD高性能)<extreme(SSD可自定义IOPS);对标EBS st1/sc1→gp2/gp3→io1/io2;CLI默认pd-standard(HDD)是坑。

### Q2. PD是什么+与VM生命周期

**伟伟答**：块存储,底层虚拟成VM一个硬盘,互相独立生命周期。

**① 对照**：✅ 块存储、网络虚拟成VM盘 对;🔶 "互相独立生命周期"太绝对——**默认不独立**(启动盘auto-delete=true跟随VM删),要独立须显式设auto-delete=false;❌ 漏auto-delete机制;❌ 漏可卸载重挂能力。

**② 参考答案**：
- PD=网络附加**块存储**(block device),挂载后格式化像本地盘,数据走Google网络(非物理主机本地)。不是对象存储(那是GCS)。
- 与VM:PD是独立资源,可挂载/卸载/重挂到别的VM。
- **生命周期由auto-delete控制**:启动盘默认auto-delete=true→删VM时一起删;数据盘可设false。要独立于VM须设**auto-delete=false**,则删VM后PD保留可重挂。
- 纠正"互相独立":有能力独立但默认不一定独立,由auto-delete决定。

**③ 概念**:auto-delete=PD挂VM时属性,决定删VM时删不删盘(启动盘默认true);PD独立价值=数据与计算解耦(VM挂了数据盘还在可挂新VM);块(挂载/格式化/随机读写)vs对象(API/海量并发/无挂载)。

**④ AWS对照**:
| | EBS | PD |
|--|-----|----|
| 删实例是否删盘 | DeleteOnTermination(启动卷默认true) | auto-delete(启动盘默认true) |
| 独立保留 | 设DeleteOnTermination=false | 设auto-delete=false |
👉 PD/EBS都是网络块存储可独立于实例,但默认启动盘跟随实例删;GCP用auto-delete,AWS用DeleteOnTermination。

**⑤ 评分：6/10**。记忆点:PD=网络块存储可卸载重挂;生命周期默认不独立(启动盘auto-delete=true随VM删),要独立设auto-delete=false(对标EBS DeleteOnTermination)。

---

**批次 1 小结**：Q1=6、Q2=6,均分6。补强→①PD四种:standard=HDD(官方明文),balanced/ssd/extreme=SSD,extreme可自定义IOPS②CLI默认pd-standard坑+最新机型只支持Hyperdisk③PD生命周期默认不独立(auto-delete=true),对标EBS DeleteOnTermination。

---

## 批次 2：Q3–Q4（2026-09-02）

### Q3. Hyperdisk 是什么+与PD区别+类型

**伟伟答**：PD下一代,性能更好,可单独配IOPS和throughput,有大吞吐ML,ML有限制(忘了)。

**① 对照**：✅ 下一代/性能更好/单独配IOPS吞吐/ML大吞吐 核心全对(解耦这个魂抓住了);🔶 ML限制忘了;❌ 四种类型只答到ML,漏Balanced/Extreme/Throughput。

**② 参考答案**：
- Hyperdisk=GCP新一代块存储,PD进化版。**最新机型系列只支持Hyperdisk不再支持PD**。两大优势:①性能可自定义(独立于容量)②整体IOPS/吞吐上限更高。
- 四类型:**Balanced**(通用默认,配IOPS+吞吐)/**Extreme**(超高IOPS,大型DB如SAP HANA)/**Throughput**(高吞吐成本优化,大数据/Kafka)/**ML**(AI专用超高聚合吞吐)。
- **Hyperdisk ML限制(补)**:**只读**,可**多实例只读挂载**(几百上千个),给GPU集群共享一份数据(模型权重/训练集),聚合吞吐极高。不能写/不能当启动盘。

**③ 概念**:最新机型只支持Hyperdisk(PD逐步被取代);四类型调节维度不同(Balanced调IOPS+吞吐,Extreme主打IOPS,Throughput主打吞吐,ML主打只读多挂聚合吞吐);ML价值=几百GPU读同一份模型,一块只读盘多挂避免各存一份。

**④ AWS对照**:Balanced≈gp3;Extreme≈io2/io2 Block Express;Throughput≈st1(但SSD架构);ML无直接等价(类似io2 multi-attach只读语义/或FSx共享)。👉 Hyperdisk性能容量解耦对标gp3首创理念。

**⑤ 评分：6.5/10**。记忆点:Hyperdisk=PD下一代(新机型只支持它),性能容量解耦+更高上限;四型=Balanced(通用)/Extreme(超高IOPS)/Throughput(高吞吐)/ML(只读多挂给AI集群共享)。

### Q4. 性能与容量解耦

**伟伟答**：容量小为了更好性能可配置不浪费容量,反过来一样。

**① 对照**：✅✅ 核心完全正确(容量小也能配高性能/不浪费/双向独立),魂抓得准;🔶 没讲机制(PD绑定vs Hyperdisk三独立旋钮);🔶 没给具体例子。

**② 参考答案**：
- 传统PD:性能**由容量决定**,随容量线性增长,要高IOPS必须买大盘(官方"to improve performance you must increase its size")。
- Hyperdisk:**容量/IOPS/吞吐三个独立配置项,分别设置分别计费,可在线动态调**(官方"performance independent of provisioned capacity")。
- 例:100GB数据库要5万IOPS→PD得买几TB大盘(浪费),Hyperdisk开100GB容量+单独provision 5万IOPS(不浪费)。反向:10TB容量只要中等吞吐,不用为大容量付高性能钱。命令`--provisioned-iops --provisioned-throughput`分开指定。

**③ 概念**:三个独立旋钮(容量/IOPS/吞吐分别计费),PD只有容量一个旋钮性能被动跟着走;可在线调(不重建不停机);成本精细化按需付费。

**④ AWS对照**:老一代性能绑容量=gp2(3IOPS/GB)/PD;新一代解耦=**gp3**(容量IOPS吞吐独立)/Hyperdisk;超高预置=io2 Block Express/Hyperdisk Extreme。👉 Hyperdisk解耦≈AWS gp3核心卖点,演进思路一致(解决"为性能被迫买大容量"的浪费)。

**⑤ 评分：7/10**。记忆点:性能容量解耦=容量/IOPS/吞吐三独立旋钮分别计费可在线调;PD性能随容量线性(要高IOPS买大盘浪费);对标AWS gp3(都从gp2/PD"IOPS随容量"进化来)。

---

**批次 2 小结**：Q3=6.5、Q4=7,均分6.75。补强→①Hyperdisk四型(Balanced/Extreme/Throughput/ML),ML=只读多挂给AI集群②最新机型只支持Hyperdisk③性能容量解耦=三独立旋钮,对标gp3。

---

## 批次 3：Q5–Q6（Local SSD）已批改

> 说明:本批(Q5-Q6)伟伟本人已作答且已在对话中批改完;当时批改正文未持久化到本文件,此处补记关键结论+伟伟提出的重要更正,供后续复习。以后每批批改后**立即写入本文件并推 GitHub**,避免再丢。

### Q5. Local SSD vs PD(物理位置/持久性/性能)
- **物理位置**:Local SSD=**物理挂在承载VM的宿主机上**(本地直连NVMe/SCSI),不走网络;PD=**网络附加**块存储(数据在Google分布式存储,走网络)。
- **持久性**:Local SSD=**临时(ephemeral)**,生命周期绑定该VM实例;PD=**持久(durable)**,可独立于VM存活。
- **性能**:Local SSD 因本地直连,**延迟极低、IOPS/吞吐极高**(远超PD);代价是不持久、不能独立、容量固定(按375GB分区块加,NVMe接口)。

### Q6. Local SSD 何时丢数据 + 场景
**⚠️ 伟伟的重要更正(已查GCP官方文档核实,成立)**:不是"任何停机都丢"——**数据是否保留分情况**:
- **保留(数据在)**:guest OS 内部 reboot(重启操作系统);host maintenance 走 **live migrate**;部分较新机型(如带 Titanium/Local SSD 的第三代,维护策略 TERMINATE and RESTART)在维护事件的 terminate→restart 中 **Compute Engine 会保留 Local SSD 数据**;host error 若在 **Local SSD recovery timeout** 内恢复,数据保留。
- **丢失(数据没)**:**stop / suspend / delete VM**;host error 超过 recovery timeout 未恢复;底层硬件故障;删除实例。
- 所以"关机就一定丢"是错的——**取决于停机类型与机型/维护策略**;但**stop/suspend/delete 这类主动停机默认会丢**,不能当持久存储用。
- **不适合存重要数据的原因**:无冗余/无跨宿主复制,绑定单台宿主机,stop/delete/硬件故障即失,无快照能力。
- **典型场景**:临时高性能盘——缓存、临时文件、scratch space、数据库/大数据的临时溢写(temp/spill)、本地暂存后再落 PD/GCS、ML 训练的本地临时数据。生产要靠"shutdown 脚本或应用层把数据同步到 PD/GCS"来防丢。

### ④ AWS 对照
| | GCP Local SSD | AWS Instance Store(临时) |
|--|--|--|
| 物理位置 | 宿主机本地 | 宿主机本地 |
| 持久性 | 临时,stop/delete丢 | 临时,stop/terminate丢 |
| 数据保留 | reboot/部分维护事件保留 | reboot保留,stop/terminate丢 |
| 对标 | Local SSD ≈ **EC2 Instance Store(NVMe SSD)** | |
👉 都是"宿主机本地、极高性能、非持久、绑实例",行为几乎一致(reboot 保、stop/删 丢)。

**批次 3 小结**：Local SSD=宿主机本地临时高性能盘,对标 EC2 Instance Store。关键更正:**不是所有停机都丢**——reboot/live migrate/部分维护事件(TERMINATE+RESTART)会保留;但 stop/suspend/delete 默认丢。场景=缓存/scratch/临时溢写,重要数据靠 shutdown 脚本同步到 PD/GCS。

---

## 批次 4：Q7–Q8（2026-09-03）

### Q7. PD 性能由什么决定
**伟伟答**：性能和容量成比例,最高性能不能超过VM支持的上限。

**① 对照**：✅✅ 两大要点全中——性能随容量成比例增长 + 受VM(实例)上限封顶,核心机制抓准;🔶 没展开"第三个因素"(磁盘类型)也影响每GB性能系数;🔶 没说VM上限具体由什么决定(vCPU数)。

**② 参考答案(GCP官方)**：PD 的 IOPS/吞吐由**三者共同决定**,取其中的**最小值(木桶效应)**:
1. **磁盘类型**:不同类型每GB给的性能系数不同(pd-standard最低、balanced、ssd、extreme最高)。
2. **磁盘容量(size)**:官方"performance scales with size"——**每GB一个baseline IOPS/吞吐,容量越大总性能越高**(线性),所以小盘性能差。
3. **VM实例规格(尤其vCPU数)**:每个机型/vCPU数有 per-VM 的 IOPS/吞吐**上限(cap)**,盘再大也不能超过VM能吃下的上限。
- **最终性能 = min(磁盘类型×容量给出的盘能力, VM实例上限)**。所以你说的"成比例"(容量)和"不超VM上限"(cap)正是这个 min 的两端;还差个"磁盘类型系数"。

**③ 概念**:①per-GB baseline——如 pd-balanced 每GB约6 read IOPS,1000GB≈6000 IOPS(数字随类型/文档更新,以官方为准),要更高IOPS就加容量;②VM cap——大盘挂小VM,性能被VM的网络/存储带宽上限卡住(小VM给不了那么多IOPS);③要打满盘性能,得同时"容量够大 + VM规格够高 + 选对磁盘类型"。

**④ AWS对照**:
| | GCP PD | AWS EBS |
|--|--|--|
| 容量影响性能 | 是(per-GB baseline,随容量线性) | gp2是(3IOPS/GB);gp3/io2解耦(容量不再定IOPS) |
| 实例上限 | VM per-instance cap(看vCPU) | EC2 **EBS-optimized 带宽/IOPS上限**(看实例规格) |
👉 两家都有"实例侧上限"这层封顶(EBS叫EBS-optimized bandwidth,GCP叫per-VM limit);"容量定性能"GCP的PD类似AWS gp2,而Hyperdisk/gp3已解耦。

**⑤ 评分：7.5/10**。记忆点:PD性能=**min(磁盘类型×容量, VM实例上限)**;容量线性(小盘慢)+VM封顶(小VM给不满大盘)+磁盘类型系数,三者取最小;对标EBS(容量like gp2、实例上限like EBS-optimized)。

### Q8. zonal PD vs regional PD
**伟伟答**：zonal指副本在同一个zonal;regional PD 跨Region Replication;有几种同步状态。

**① 对照**：✅ zonal=单zone、regional有复制、"有几种同步状态"方向对;❌❌ **关键错误:regional PD 不是"跨Region"复制,而是跨"同一Region内的两个zone(跨AZ)"**;🔶 没说同步复制RPO=0;🔶 同步状态没具体说是哪几种。

**② 参考答案(GCP官方,已核实)**：
- **zonal PD**:数据只在**单个 zone**(可有多副本但都在同zone),该zone挂了盘不可用。
- **regional PD**:**在同一个 region 内的两个 zone 之间同步复制(synchronous replication)**写入,**RPO=0**(写成功=两个zone都写入),可容忍**单个zone故障**仍可用。⚠️**是跨 zone(跨AZ),不是跨 region**——伟伟这里说反了。
- **高可用机制**:一个zone挂 → 可把regional PD **force-attach / failover** 到另一个zone的VM,数据不丢(RPO=0)继续用。
- **对性能影响**:因为**每次写都要同步到两个zone(等两边都确认)**,写延迟比zonal略高(多一跳跨zone网络往返);读通常从本地zone副本读不受影响。这是HA的代价——用一点写延迟换RPO=0的跨zone容灾。
- **复制状态(replication states,官方3种)**:
  1. **Fully replicated(完全复制)**:两zone副本都最新,健康态。
  2. **Degraded(降级)**:只有一个副本在同步(另一zone副本掉了/未跟上),此时无HA保护。
  3. **Catching up(追赶中)**:降级后正在自愈,副本重新同步,追平后回到 Fully replicated。
  (另有 per-replica 的 Replica State 指标可单独监控每个副本。)

**③ 概念**:同步复制=写必须两zone都落盘才返回成功(RPO=0,不丢数据),代价是写延迟↑;zonal只1个zone无跨zone保护;regional靠"两zone同步副本+failover"扛单zone故障,是MySQL/SQLServer等关键DB要HA时的主存储选择;复制状态用于HA合规监控(Fully→Degraded告警→Catching up自愈)。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 单zone盘 | zonal PD | EBS(单AZ) |
| 跨zone同步HA盘 | **regional PD / Hyperdisk Balanced High Availability** | **io2 Block Express Multi-Attach 不等价**;更接近的是 **无原生等价**——EBS本身单AZ,AWS靠 **应用层复制(如RDS Multi-AZ)** 或 **io2 跨AZ无**;真正对标是 GCP regional PD 独有的"块层跨AZ同步" |
👉 重点差异:**GCP regional PD 提供块存储层的跨AZ同步复制(RPO=0),AWS EBS 无同等的原生跨AZ块复制**(AWS通常在数据库/应用层做Multi-AZ,如RDS/Aurora),这是两家HA思路的一个明显区别。

**⑤ 评分：5/10**。⚠️主要扣在把"跨zone"说成"跨Region"(方向性错误,HA范围理解偏了)。记忆点:**regional PD=同一region内跨两zone同步复制(RPO=0),容单zone故障**(不是跨region!);写要等两zone→写延迟略高;3种复制态=Fully replicated/Degraded/Catching up;AWS EBS无原生跨AZ块复制(靠RDS等应用层Multi-AZ)。

---

**批次 4 小结**：Q7=7.5、Q8=5,均分6.25。重点纠错→**①regional PD 是"同一Region内跨两个zone(跨AZ)"同步复制,不是跨Region!RPO=0容单zone故障**②PD性能=min(磁盘类型×容量,VM上限)三者取小③复制3态Fully/Degraded/Catching up④regional PD块层跨AZ同步是GCP特色,AWS EBS无原生等价(靠RDS Multi-AZ)。
