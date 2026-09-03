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

---

## 批次 5：Q9–Q10（2026-09-03）

### Q9. PD 多挂载(multi-writer / read-only)
**伟伟答**：multi-writer多个VM写会互相覆盖,必须上层有集群文件系统;read-only是一写多读,分享数据使用。

**① 对照**：✅✅ multi-writer需要上层集群文件系统(PD本身不提供锁/协调)——核心限制答对;✅ read-only多读用于分享数据——对;🔶 "一写多读"表述不准:read-only模式下**没有任何实例能写**(不是"一个写多个读"),是纯只读多挂;🔶 漏具体限制数字(multi-writer仅**最多2个N2 VM+SSD PD**;read-only可挂很多)。

**② 参考答案(GCP官方,已核实)**：
- **read-only 多挂载**:一块PD可同时以只读模式挂到**多个VM**,**所有实例都只能读、谁都不能写**。用于把静态数据集(ML模型权重、参考数据、软件包)分发给一批VM,只存一份省钱省管理。⚠️不是"一写多读"——是**全只读**;要更新内容得先全部卸载、挂到单个可写VM改完再重新只读分发。
- **multi-writer 模式**:**SSD Persistent Disk** 可同时**读写挂载到最多 2 个 N2 VM**,两个VM都能读写。⚠️**PD 本身不做写协调/锁**,两VM各写各的会**互相覆盖/损坏数据**——所以**必须在上层跑集群感知(cluster-aware)/共享文件系统或应用**(如带分布式锁的DB、集群FS)自己管并发。它只提供"共享块设备"这块地基。
- 限制小结:read-only=纯只读、可多挂;multi-writer=SSD PD、**上限2个N2 VM**、需上层集群FS/应用管锁。

**③ 概念**:块存储多挂载的根本难点=**并发写一致性**。read-only回避问题(禁写);multi-writer把并发控制责任甩给上层(PD只保证两VM能同时连到同一块设备,不保证不冲突)。普通ext4/xfs是单机文件系统,多写会损坏,必须用GFS2/OCFS2这类集群文件系统或应用层锁。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 只读多挂 | PD read-only mode(多VM) | EBS 无原生只读多挂(AWS一般用EFS/S3分发);快照多次创卷 |
| 读写多挂 | multi-writer(SSD PD,最多2×N2) | **EBS Multi-Attach**(io1/io2,最多**16个**同AZ实例) |
| 都需上层管锁 | 是(集群FS) | 是(EBS Multi-Attach同样要cluster-aware FS,普通FS会损坏) |
👉 概念一致(共享块存储都需集群FS管并发);差异:AWS EBS Multi-Attach支持**16个**读写实例、限io1/io2、需同AZ;GCP multi-writer仅**2个**N2、限SSD PD。GCP的只读多挂AWS没有直接对应(EBS不支持只读多挂,AWS走EFS/S3)。

**⑤ 评分：7.5/10**。记忆点:read-only=**全只读**多挂分发静态数据(非"一写多读");multi-writer=SSD PD最多**2个N2 VM**读写,**PD不管锁必须上层集群FS**;对标AWS EBS Multi-Attach(io1/io2,最多16实例,同样要集群FS)。

### Q10. 在线扩容 / 能否缩小 / 扩容后文件系统操作
**伟伟答**：可以扩展容量,不能缩小,文件系统要resize,lvm要extend。

**① 对照**：✅✅✅ 全对!在线扩容✓、不能缩小✓、扩完要resize文件系统✓、用了LVM要先extend✓。答得干净准确。🔶 可补:①扩容不停机(无需卸载/重启)②有分区表的还要先扩分区(growpart)③resize命令具体名。

**② 参考答案(GCP官方)**：
- **在线扩容**:PD/Hyperdisk 可**不停机在线增大容量**(`gcloud compute disks resize` 或控制台),VM运行中、盘挂着就能扩,不用卸载。
- **不能缩小**:官方明确**只能增不能减**(要减只能建小盘+迁数据)。
- **扩完的文件系统层操作(关键,分层)**:
  1. (若盘上有**分区**)先扩分区:`growpart /dev/sdb 1`。
  2. (若用**LVM**)扩物理卷+逻辑卷:`pvresize` → `lvextend`。
  3. **扩文件系统**:ext4 用 `resize2fs`;xfs 用 `xfs_growfs`(xfs只能扩不能缩)。
  - 顺序:先扩盘(云层)→再扩分区→(LVM)扩PV/LV→最后扩文件系统。不做最后这步,`df`看到的可用空间不会变(云层扩了但FS没跟上)。

**③ 概念**:云层扩容(把块设备变大)和**客户机OS内文件系统扩容是两回事**——云把 `/dev/sdb` 从100G变200G,但文件系统还认为自己只有100G,必须在OS里 resize2fs/xfs_growfs 才用得上新空间。缩小危险(要先缩FS再缩设备,极易丢数据)所以云厂商普遍禁止块设备缩小。

**④ AWS对照**:
| | GCP PD | AWS EBS |
|--|--|--|
| 在线扩容 | ✓(disks resize) | ✓(modify-volume,弹性卷) |
| 缩小 | ✗不能 | ✗不能 |
| 扩后OS操作 | growpart+resize2fs/xfs_growfs | 完全相同(growpart+resize2fs/xfs_growfs) |
👉 **两家几乎一模一样**:都能在线扩、都不能缩、扩完都要在OS里 growpart + resize2fs/xfs_growfs。AWS弹性卷扩完还有个"optimizing"过渡期,GCP无此概念。

**⑤ 评分：9/10**。记忆点:PD在线扩容(不停机)、**只增不能缩**;扩完必须OS内跟进——有分区先growpart、LVM先lvextend、最后resize2fs(ext4)/xfs_growfs(xfs);和AWS EBS流程完全一致。

---

**批次 5 小结**：Q9=7.5、Q10=9,均分8.25(本批最高!)。补强→①read-only是**全只读**多挂(非一写多读);multi-writer仅**2个N2+SSD PD**且**PD不管锁需上层集群FS**,对标EBS Multi-Attach(io1/io2最多16)②扩容:在线扩、不能缩、扩完OS里growpart+lvextend+resize2fs/xfs_growfs,与AWS EBS完全一致。

---

## 批次 6：Q11–Q12（2026-09-03）

### Q11. 快照工作原理 + 增量 + 存哪
**伟伟答**：快照记录磁盘数据块,复制传送到GCS;后续快照只传变化部分省空间;快照之间互相reference。

**① 对照**：✅✅✅ 增量机制答得很准——首次全量、后续只传变化块、快照互相reference、省空间,核心全中;✅ "存到GCS"方向对(底层映射到Cloud Storage);🔶 措辞可精确:不是存进"你自己的GCS bucket",是Google托管的、**底层映射到Cloud Storage位置**的快照存储(多位置+校验和)。

**② 参考答案(GCP官方)**：
- **增量快照机制**:第一次快照=**全量**(该盘所有已用块);之后每次快照**只存自上次快照以来变化的块**,未变的块**引用(reference)已有快照的数据**——所以快照之间互相依赖、链式引用。
- **省空间/省钱**:只为增量块付费,不是每次都全量拷一份。
- **删除的智能处理(重点)**:删除某个中间快照时,**它独有、且被后续快照依赖的块会被"下放/合并"到下一个快照**,保证剩余快照仍可完整恢复——所以"删一个旧快照"并不会等比例释放空间(它引用的块可能还被后面用着)。
- **存哪**:快照数据**存储在Google的Cloud Storage(底层),跨多个位置冗余存放+自动校验和(checksum)保证完整性**,与承载盘的物理存储分离(所以盘/zone挂了快照还在)。**不放在你的GCS bucket里**,是Compute Engine托管的独立快照存储,但存储位置可选regional/multi-regional(映射到GCS的region/multi-region)。

**③ 概念**:增量+引用=块级去重的链;正因链式引用,"快照存储用量"不等于"各快照大小之和";首次快照最大最慢,后续快小快;和承载盘解耦(独立于zone),这是它能做跨zone/跨region恢复的基础。

**④ AWS对照**:
| | GCP PD Snapshot | AWS EBS Snapshot |
|--|--|--|
| 增量 | 是(首次全量后续增量) | 完全相同(增量) |
| 底层存储 | Google Cloud Storage(多位置+校验) | **Amazon S3**(用户不可直接访问的托管S3) |
| 删中间快照 | 块下放给后续快照,不破坏恢复 | 完全相同(块合并到下一快照) |
👉 两家快照机制**高度一致**:都是块级增量、底层放对象存储(GCP→GCS / AWS→S3)、删中间快照都做块合并保证可恢复。

**⑤ 评分：8.5/10**。记忆点:首次全量+后续只传变化块+链式reference+底层存Cloud Storage(多位置+校验);删中间快照块会下放给后续快照(所以删旧快照不等比例省空间);对标AWS EBS快照(底层S3),机制几乎一样。

### Q12. 快照是什么级别资源 + 跨region恢复
**伟伟答**：快照是regional,可以在另外regional恢复硬盘;可对磁盘拍快照传输到其他Region做迁移和容灾。

**① 对照**：✅ 跨region恢复✓、用于迁移/容灾✓(用途完全对);❌ **关键错误:快照默认是 global(全局)资源,不是 regional**;🔶 混淆了"快照资源级别(global)"和"快照存储位置(可选regional/multi-regional)"两个概念。

**② 参考答案(GCP官方,已核实)**：
- **快照默认是 global 资源**(官方原文"Snapshots are, by default, global resources")——它不绑定某个zone或region,在**同一project内任意zone/region都能用它恢复出新盘/新VM**。⚠️伟伟说"regional"不对。
- **但"存储位置"可配置**:创建时可指定快照**存储位置为 regional 或 multi-regional**(映射到GCS的region如`us-central1`或multi-region如`us`)。这是"数据实际存哪"的选择,和"资源是global(哪都能引用)"是两码事。
- **跨region恢复**:正因为是global资源,**可以用一个zone拍的快照,在另一个region创建新磁盘**。→ 直接支撑**跨区容灾(DR)**和**跨region迁移**(把工作负载搬到别的region)。
- **纠正**:资源级别=**global**;存储位置=可选regional/multi-regional。别把两者混成"快照是regional"。

**③ 概念**:GCP资源分三级——zonal(如zonal PD、Local SSD)、regional(如regional PD、subnet)、global(如snapshot、image、VPC网络)。快照是global的意义=你不用关心它在哪个region就能全局引用来恢复,天然适合跨region迁移/DR;存储位置选项只影响数据落地的物理region(合规/就近/成本考虑)。

**④ AWS对照**:
| | GCP Snapshot | AWS EBS Snapshot |
|--|--|--|
| 资源作用域 | **global**(全局可用) | **regional**(绑定所在region) |
| 跨region用 | 直接可跨region恢复 | 需先**copy-snapshot到目标region**再用 |
👉 **重要差异**:GCP快照是global,跨region恢复更省事(直接引用);**AWS EBS快照是regional的,跨region要先显式copy一份到目标region**才能在那恢复。伟伟把GCP说成regional,恰好把它错当成了AWS的模型。

**⑤ 评分：6/10**。⚠️主要扣在"快照是regional"这个定级错误(应为global)。记忆点:**GCP快照=global资源(哪个region都能恢复),存储位置可选regional/multi-regional**;跨region恢复→天然支持DR/迁移;对比AWS EBS快照是**regional、跨region要先copy-snapshot**(这正是伟伟记混的点)。

---

**批次 6 小结**：Q11=8.5、Q12=6,均分7.25。重点纠错→**①快照默认是 global 资源(不是regional!)——"资源global(哪都能恢复)" vs "存储位置可选regional/multi-regional"是两回事**②增量:首次全量+后续变化块+链式reference,删中间快照块下放给后续③底层存Cloud Storage(AWS存S3)④GCP快照global跨region直接恢复,**AWS EBS快照regional跨region要先copy-snapshot**(伟伟把GCP错记成了AWS模型)。

> 💡伟伟追问:快照global会不会违反数据隐私/主权(GDPR)? 答:**不会**。global 只是**控制面"全局可寻址/可引用"**,不是数据物理全球乱放。**数据落地位置由 `--storage-location` 控制,可锁 regional(如europe-west1,数据只在该region)或 multi-regional(如eu,限该大区内冗余)**。官方明确此功能就是"meet data residency/regulatory requirements(如病历/金融数据存特定位置)"。合规做法:建快照显式设 storage location 到合规region + 用 Org Policy `gcp.resourceLocations` 从组织层强制资源位置。合规责任在"你把快照restore到哪",不在"快照是不是global"。对比AWS EBS快照regional(默认锁死region,跨region要copy)——GCP更灵活但合规更依赖你正确设location。

---

## 批次 7：Q13–Q14（2026-09-03）

### Q13. Snapshot Schedule(快照计划)
**伟伟答**：定时快照,保存多久,保存多少副本,自动不忘记,自动清理过期。

**① 对照**：✅✅ 定时自动拍✓、保留时长(保存多久)✓、自动不忘✓、自动清理过期✓——核心全中;🔶 "保存多少副本"表述略偏:保留策略主要按**保留天数(max retention days)**,不是"固定副本数"(到期自动删,间接决定保有数量);🔶 漏了"计划附加到盘、可设频率(每小时/天/周)、可跨region存、删盘时快照保留策略"等细节。

**② 参考答案(GCP官方)**：
- **Snapshot Schedule = 资源策略(resource policy),附加到磁盘上,让Compute Engine按计划自动增量快照**。
- **配置项**:①**频率(schedule)**:hourly/daily/weekly + 具体时刻;②**保留策略(retention)**:`max-retention-days` 到期**自动删除旧快照**;③**删盘行为**:`on-source-disk-delete`(删源盘时快照是保留keep还是一起删apply-retention);④存储位置(regional/multi-regional)、标签等。
- **对比手动快照的优势**:①**自动化不遗漏**(人不会忘,合规必备);②**自动清理过期**(手动要自己记着删,不然快照堆积涨钱);③**一致的保留策略**(RPO可控);④一个策略可**附加到多块盘**统一管理;⑤审计/合规友好。
- **实践**:一块盘可附加**最多10个**schedule(官方限制,以最新文档为准);策略改了对已存在快照的保留也生效。

**③ 概念**:Snapshot Schedule本质是"自动增量快照+生命周期管理(到期自动删)"。手动快照=一次性动作,靠人;计划快照=策略驱动的持续备份,把"拍+留多久+到期删"自动化,是生产环境备份/DR的标准做法。保留策略决定RPO(多久一个恢复点)和成本(留越久越贵)。

**④ AWS对照**:
| | GCP Snapshot Schedule | AWS |
|--|--|--|
| 自动定期快照+保留 | Snapshot Schedule(resource policy) | **Data Lifecycle Manager (DLM)** 或 **AWS Backup** |
| 机制 | 附加到盘,频率+max-retention-days | DLM按tag批量,policy定频率+保留数/天数 |
👉 GCP Snapshot Schedule ≈ AWS **DLM**(轻量、EBS快照生命周期)或 **AWS Backup**(统一备份服务)。都做"自动拍+自动过期删",都是为了不靠人手、合规、控成本。

**⑤ 评分：8/10**。记忆点:Snapshot Schedule=附加到盘的策略,自动按频率(时/天/周)增量快照+按max-retention-days自动删过期+可控删盘行为;优势=不遗漏/自动清理/统一保留策略/合规;对标AWS DLM或AWS Backup。

### Q14. 默认加密 / CMEK / CSEK / 与GCS对照
**伟伟答**：加密使用CMEK key,和GCS类似,读时自动解密,没有client side加密,不从on-premise上传。

**① 对照**：✅ 用CMEK✓、和GCS类似✓、读时自动解密✓——对;🔶 漏了**默认加密(GMEK,Google托管)**这个最基础层(不配任何东西也默认加密);🔶 CMEK和CSEK没分清各是什么;⚠️ "没有client side加密"——**CSEK不等于客户端加密**,这里概念要厘清;🔥 **重大时效更新:CSEK在Compute Engine已于2026-07-20停用(deprecated)**,伟伟"没有客户提供密钥"这个直觉现在反而"歪打正着"(见下)。

**② 参考答案(GCP官方,含2026最新变更)**：GCP块存储加密**永远默认开启(at-rest),数据落盘前自动加密、读时自动解密**,分三种密钥管理方式:
1. **GMEK(Google-managed,默认)**:啥都不配,Google全自动管密钥。免费、透明、读写自动加解密。
2. **CMEK(Customer-Managed,用Cloud KMS)**:你在**Cloud KMS**里建/管密钥,PD用它加密。你能控制密钥轮换/禁用/审计(密钥禁用=盘打不开)。这是企业合规最常用的"自己管钥但不离开云"的方案。
3. **CSEK(Customer-Supplied,你自带原始密钥)**:你在API调用里**直接传入原始密钥**,Google用它保护数据但**不存你的密钥**(密钥丢=数据永久打不开)。
   - 🔥**重大更新(必须知道)**:**CSEK 在 Compute Engine 已弃用——自 2026-07-20 起不能再用 CSEK 加密 PD/镜像/机器镜像/快照;2027-07-20 从Compute Engine彻底移除**。所以**现在(2026-09)PD 实际只推 GMEK 默认 或 CMEK**,CSEK 已是历史。→ 伟伟说"没有客户提供密钥"当下已基本成立(在CE场景)。
- **读时自动解密**:对(GMEK/CMEK都是服务端透明加解密,应用无感)。
- **⚠️厘清"client-side加密"**:CSEK ≠ 客户端加密。CSEK是**你提供密钥但加密仍在Google服务端做**;真正的**client-side encryption(CSE)是你在上传前自己在本地加密好**(GCS有CSE概念,PD块存储没有CSE概念)。伟伟"没有client side加密+不从on-premise上传"——**PD确实没有"本地先加密再上传"这种模式**(PD是VM挂载的块设备,不是你从本地传文件),这点直觉对,但用词该是"PD无CSE",别和CSEK混。

**③ 概念**:三层控制权递增——GMEK(Google管)<CMEK(你用KMS管钥,数据和钥都在云)<CSEK(你自带钥,Google不留)。CMEK靠Cloud KMS做密钥生命周期(轮换/禁用/权限/审计),禁用密钥即刻锁死盘=合规"随时可撤销访问"。默认永远加密,加解密对应用透明(读时自动解)。CSEK因运维风险高(丢钥即丢数据)+管理麻烦,GCP已在CE弃用。

**④ AWS对照**:
| GCP | AWS EBS | 说明 |
|--|--|--|
| GMEK(默认) | 默认AWS托管密钥(aws/ebs) | 都默认加密(新EBS默认加密可开) |
| CMEK(Cloud KMS) | **KMS CMK(customer managed key)** | 概念完全对应,都用KMS管钥 |
| CSEK(自带原始钥,已弃用) | EBS**无**CSEK等价 | AWS EBS从来只有KMS托管/客户KMS,无"传原始密钥"模式 |
👉 CMEK↔AWS KMS客户管理密钥,概念一致(自管密钥、可轮换/禁用/审计);GCP独有的CSEK正在退场,AWS本就没有对应物。**与GCS加密对照**:GCS同样有 GMEK默认/CMEK(KMS)/CSEK 三层——所以伟伟"和GCS类似"完全正确(GCP块存储与GCS的密钥模型是一套体系)。

**⑤ 评分：6.5/10**。记忆点:块存储**永远默认加密**;三种密钥=**GMEK(默认Google管) / CMEK(你用Cloud KMS管,合规首选) / CSEK(自带原始钥——⚠️已于2026-07-20在Compute Engine弃用,2027彻底移除)**;读时服务端自动解密;CSEK≠client-side加密(PD无CSE);与GCS加密模型同一套;CMEK对标AWS KMS客户管理密钥。

---

**批次 7 小结**：Q13=8、Q14=6.5,均分7.25。重点补强→**①快照计划=附加到盘的策略,频率+max-retention-days自动删过期+删盘行为,对标AWS DLM/Backup ②加密三层GMEK(默认)/CMEK(Cloud KMS,合规首选)/CSEK ③🔥CSEK已于2026-07-20在Compute Engine弃用(2027移除)——现在PD只用GMEK/CMEK ④CSEK≠client-side加密;CMEK对标AWS KMS客户管理密钥;GCS加密同一套体系**。

---

## 批次 8：Q15–Q16（2026-09-03）

### Q15. CSEK 密钥丢失 + 快照/扩容额外要求
**伟伟答**：密钥丢了,数据无法解密;快照必须能够读密钥权限。

**① 对照**：✅✅ 密钥丢=数据永久无法解密✓(核心对);✅ 快照/操作必须能拿到同一个CSEK密钥✓(方向对);🔶 措辞:CSEK是"每次操作都要**在API里重新提供原始密钥**",不是"读密钥权限"(那是CMEK/KMS的IAM权限概念);🔶 漏了"CSEK加密盘做的快照也是CSEK加密、后续从该快照建盘/扩容都要再传密钥"这个链式要求;🔥 应点出**CSEK已于2026-07-20在CE弃用**。

**② 参考答案(GCP官方)**：
- **密钥丢失后果**:CSEK的密钥**Google完全不保存**,只用它包裹(wrap)真正加密数据的密钥。**密钥一丢,Google无法帮你恢复,数据永久无法解密=等于数据永久丢失**。这是CSEK最大的运维风险(也是它被弃用的原因之一)。
- **快照/扩容等操作的额外要求**:CSEK加密盘的**每一个后续操作都必须重新提供同一个原始密钥**:
  - 创建快照 → 快照继承CSEK加密,建时要传密钥;
  - 从CSEK快照恢复/建新盘 → 要传密钥;
  - 扩容、创建镜像 → 都要传密钥;
  - 挂载启动VM → 要传密钥(否则VM起不来)。
  - 本质:因为Google不存密钥,**任何要解密盘内容的动作都得你临时把密钥送进去**。伟伟"必须能读密钥"意思对,但准确说是"**必须重新提供原始密钥**"。
- 🔥**时效(必记)**:**CSEK 自 2026-07-20 起在 Compute Engine 弃用,不能再用于 PD/快照/镜像;2027-07-20 彻底移除**。现在要"自管密钥"应用 **CMEK(Cloud KMS)**——CMEK靠IAM授权访问密钥(禁用密钥=锁盘),不用每次传原始密钥,运维安全得多。伟伟"读密钥权限"这个说法其实更贴合CMEK。

**③ 概念**:CSEK=你拿钥、Google不留→丢钥=数据死,且每次操作要重新递钥(极繁琐+高危);CMEK=钥放Cloud KMS你授权→靠IAM控制访问、可轮换/禁用/审计,禁用即锁盘但不丢(重新启用可恢复)。这就是CSEK被CMEK取代的根本原因:同样"客户掌控密钥",CMEK更安全易用。

**④ AWS对照**:
| | GCP CSEK(已弃用) | GCP CMEK | AWS EBS |
|--|--|--|--|
| 密钥保管 | 你自己(Google不存) | Cloud KMS | AWS KMS |
| 丢钥后果 | 数据永久不可恢复 | 禁用可恢复(重新启用) | 同CMEK(KMS key删了才彻底丢) |
| 每次操作递钥 | 要 | 不要(IAM授权) | 不要(IAM/KMS授权) |
👉 AWS EBS **无CSEK等价**(从来只有KMS托管密钥);AWS对应的是CMEK↔KMS CMK:靠IAM+KMS策略授权,禁用/撤销key即锁数据,删key才永久丢。GCP弃用CSEK后,两家的"客户管钥"模型就趋于一致了(都走KMS)。

**⑤ 评分：7/10**。记忆点:CSEK丢钥=数据永久死(Google不存钥);CSEK加密盘的**快照/扩容/建盘/启动每步都要重新提供原始密钥**;🔥CSEK已2026-07-20在CE弃用→改用CMEK(Cloud KMS,IAM授权、禁用锁盘可恢复,对标AWS KMS)。

### Q16. 数据库块存储选型 + latency官方数值(伟伟专门问)
**伟伟答**：选hyperextreme(如Oracle/HANA),普通选pd-ssd,看成本和机型VM;并问:GCP官方文档有没有注明latency具体多少ms?

**① 对照**：✅✅ Hyperdisk Extreme给顶级DB(Oracle/SAP HANA)✓、普通pd-ssd✓、要看成本和VM机型✓——选型思路完全正确;🔶 可补"pd-extreme的定位"和"选型判据的量化门槛(IOPS/吞吐阈值)"。

**② 参考答案(GCP官方选型)**：
- **判据优先级**:①**延迟需求**→要SSD级(亚毫秒)选Hyperdisk Balanced/Extreme或pd-ssd;②**单卷IOPS/吞吐需求**→<160K IOPS且<2.4GiB/s,**Hyperdisk Balanced**够用且划算;要**>160K IOPS(超高)→Hyperdisk Extreme**;③**成本+机型支持**(关键:Hyperdisk只在特定第三代+机型支持,老机型只能pd-*)。
- **具体选型**:
  - **pd-ssd**:通用高性能DB,中等IOPS,老机型/不支持Hyperdisk时的选择。
  - **pd-extreme**:PD里最高性能、可provision IOPS,高端DB(SAP HANA)——但属"上一代"高端。
  - **Hyperdisk Extreme**:**新一代最高性能**,超高IOPS(单卷可到很高)、亚毫秒延迟,给Oracle/SAP HANA/大型高事务DB——伟伟选它给HANA/Oracle**完全正确**。
  - 趋势:新机型只支持Hyperdisk,Google主推 Hyperdisk Balanced(通用DB)/Extreme(顶级DB)取代 pd-ssd/pd-extreme。

**③ 关于latency官方数值(直接回答伟伟的问题)**：
- **GCP官方文档对块存储latency只给"定性"描述,不给具体ms数字/SLA**。查到的官方原文(Hyperdisk overview):
  - **"Hyperdisk Balanced and Hyperdisk Extreme offer sub-millisecond latency"**(亚毫秒,即 **<1ms**)。
  - 官方还说:把 Hyperdisk Balanced/Balanced HA/Extreme/ML 的延迟**类比企业级SSD(enterprise SSD)**;把 Hyperdisk Throughput 类比**HDD**的延迟。
  - 选型博客原文:"If your workload requires **SSD-like latency (i.e., sub-millisecond)**, it likely should be served by Hyperdisk Balanced or Hyperdisk Extreme."
- **结论**:GCP**没有**在官方文档标注像"0.5ms/0.3ms"这样的精确数字或延迟SLA,只承诺**"sub-millisecond(亚毫秒,<1ms)"**这个定性级别(IOPS/吞吐才有精确数值和计费)。要精确延迟得自己在目标机型上实测(fio)。⚠️这条我查了官方文档核实:延迟无官方精确ms值,只有"sub-millisecond"表述——不是我记不清,是GCP确实不公布精确数。

**④ AWS对照**:
| | GCP | AWS EBS |
|--|--|--|
| 顶级DB(HANA/Oracle) | Hyperdisk Extreme / pd-extreme | **io2 Block Express**(亚毫秒,可到256K IOPS) |
| 通用高性能DB | Hyperdisk Balanced / pd-ssd | gp3 / io1 |
| 官方latency数值 | 只给"sub-millisecond"定性 | AWS **io2 Block Express官方称"sub-millisecond"**;也主要定性,精确值靠实测 |
👉 两家都**只承诺"亚毫秒(sub-millisecond)"定性级别,不给精确ms SLA**。顶级DB:GCP Hyperdisk Extreme ↔ AWS io2 Block Express;通用:Hyperdisk Balanced ↔ gp3。选型逻辑一致(延迟/IOPS/吞吐/成本/机型支持)。

**⑤ 评分：8/10**。记忆点:选型三判据=延迟(要亚毫秒选Hyperdisk Balanced/Extreme或pd-ssd)+单卷IOPS/吞吐(>160K选Extreme)+成本&机型支持;HANA/Oracle→Hyperdisk Extreme(对标AWS io2 Block Express);**GCP官方latency只给"sub-millisecond(<1ms)"定性,无精确ms数值/SLA,精确值靠fio实测**。

---

**批次 8 小结**：Q15=7、Q16=8,均分7.5。重点→**①CSEK丢钥=数据永久死+每步操作(快照/扩容/建盘/启动)要重传原始密钥;已2026-07-20在CE弃用→改CMEK(Cloud KMS,IAM授权)②DB选型:延迟(亚毫秒)+单卷IOPS(>160K选Extreme)+成本&机型;HANA/Oracle→Hyperdisk Extreme↔AWS io2 Block Express ③🔍伟伟问的latency:GCP官方只给"sub-millisecond(<1ms)"定性,不公布精确ms/SLA,类比企业SSD;精确值靠实测**。

---

## 批次 9：Q17–Q18（2026-09-03）

### Q17. 小盘性能差 + 性能随容量线性机制 + 怎么避免瓶颈
**伟伟答**：小容量IOPS/吞吐都低,容易达到上限;每个GB提供多少iops;用hyperdisk可以自由配置。

**① 对照**：✅✅ 小盘IOPS/吞吐低、易达上限✓、每GB给固定iops(per-GB rate)✓、Hyperdisk解耦自由配✓——机制和解法全中;🔶 没给具体per-GB数值(可量化更好);🔶 还可补"加大容量"和"换机型"两个PD内的避坑手段。

**② 参考答案(GCP官方,含具体数值)**：
- **机制:PD性能 = 基线(baseline) + 每GiB速率 × 容量**,即**性能随容量线性增长**。官方实例(pd-balanced):**baseline 3,000 IOPS + 6 IOPS/GiB**。
  - 例:100GiB pd-balanced = 3000 + 6×100 = **3,600 IOPS**;2000GiB = 3000 + 6×2000 = **15,000 IOPS**。
  - 所以**盘越小,能叠加的"6×容量"越少,总IOPS越低** → 小盘性能差的根因。
- **为什么线性**:GCP把PD性能按容量配额发放(每GiB一份性能),官方原话"to improve a Persistent Disk volume's performance, you must **increase its size**"——想要更高性能,只能加容量(或换更高档类型)。
- **怎么避免小盘瓶颈(三招)**:
  1. **加大容量**(哪怕用不满空间,也为拿性能而买大盘——传统PD无奈之举)。
  2. **换更高档磁盘类型**(pd-ssd每GiB IOPS更高;pd-extreme可自定义IOPS)。
  3. **✅最优:用Hyperdisk**——性能与容量**解耦**,小容量也能单独 provision 高IOPS/吞吐,不用为性能被迫买大盘(伟伟答的方向)。
- ⚠️还要注意**VM实例上限**:盘性能再高也不能超过VM(vCPU数)的per-instance cap,小VM给不满大盘。

**③ 概念**:PD "线性" = baseline + perGiB×size,是"用容量买性能"的配额模型 → 小盘先天性能低;Hyperdisk打破这个绑定(三独立旋钮),是Google给"小容量高性能"场景的正解;pd-extreme是PD内的过渡(可provision IOPS但仍属老一代)。

**④ AWS对照**:
| | GCP | AWS |
|--|--|--|
| 容量定性能(线性) | pd-standard/balanced/ssd(baseline+perGiB) | **gp2**(3 IOPS/GiB,同样小盘慢) |
| 解耦(容量与性能独立) | Hyperdisk / pd-extreme | **gp3**(独立配IOPS/吞吐) / io1/io2 |
👉 完全同构:GCP的pd-balanced小盘慢 = AWS gp2小盘慢(3IOPS/GB);解法都是换解耦型(GCP Hyperdisk / AWS gp3)。

**⑤ 评分：8/10**。记忆点:PD性能=**baseline + perGiB×容量**(pd-balanced=3000+6/GiB),小盘先天IOPS低;避坑=加容量/换高档类型/**上Hyperdisk解耦**(小容量也能高IOPS);还受VM实例cap封顶;对标AWS gp2(线性)→gp3(解耦)。

### Q18. Local SSD RAID + 为何仍不能替代PD
**伟伟答**：RAID0提升容量,RAID1提升持久性;但机器VM坏了数据跟着坏,所以不能替代PD。

**① 对照**：✅ RAID0提升容量(和性能)✓、VM坏数据跟着坏所以不能替代PD✓——核心结论对;⚠️ **"RAID1提升持久性"在Local SSD上基本无意义(要纠正)**:所有Local SSD都在同一台宿主机,RAID1两份镜像也在同一host,host/VM挂了两份一起没——**RAID1挡不住Local SSD最主要的失效场景**;🔶 RAID0除了容量,更主要是**提升IOPS/吞吐**(条带化);🔶 GCP官方对Local SSD**推荐RAID0**。

**② 参考答案(GCP官方)**：
- **RAID配置**:每块Local SSD=**375GB NVMe分区**。**GCP官方推荐用 `mdadm` 做 RAID 0(条带化 striping)把多块Local SSD拼起来**,**同时提升容量(累加)和IOPS/吞吐(并行条带)**。要跑满性能还要用GCP镜像自带的Local SSD优化脚本。
- **RAID0**:条带化,N块盘容量和性能≈N倍,**但无冗余**(一块坏全丢)——不过Local SSD场景本来就不追求冗余(见下)。
- **⚠️ RAID1(镜像)在Local SSD上意义不大(纠正伟伟)**:RAID1靠"两份镜像在不同盘"防单盘故障。但**GCP的Local SSD全部物理绑定在承载VM的同一宿主机**——host宕机/VM停止/删除/迁移时,**所有Local SSD(含RAID1的两份镜像)一起丢**。所以RAID1挡不住Local SSD的主要失效场景(host级),白白牺牲一半容量。**这正是"RAID也救不了"的原因**。
- **为何RAID也不能替代PD存持久数据**:
  1. Local SSD是**临时(ephemeral)**存储,绑定宿主机;**stop/suspend/delete VM、host故障**都会丢数据(RAID0/1都救不了host级丢失)。
  2. **无跨宿主机冗余、无快照、不能独立于VM存活、不能重挂到别的VM**。
  3. RAID只是在"同一台host的多块临时盘"之间做条带/镜像,**改变不了"数据绑死在这台host"这个根本属性**。
  - 所以:要持久/可恢复/可迁移的数据,必须用**PD/Hyperdisk**(网络块存储,独立于VM,有快照,跨zone/region能恢复)。Local SSD(即使RAID)只配当**临时高性能盘**(缓存/scratch/临时溢写),重要数据要靠应用/脚本同步落到PD/GCS。

**③ 概念**:RAID解决的是"同一host内多盘的容量/性能/单盘冗余",解决不了"整台host丢失";Local SSD的持久性缺陷是**架构级(绑宿主机+临时)**,不是"多几块盘做冗余"能补的。PD的持久性来自"网络分布式存储+独立生命周期",这是Local SSD RAID永远给不了的。

**④ AWS对照**:
| | GCP Local SSD | AWS Instance Store |
|--|--|--|
| RAID提升性能/容量 | RAID0(mdadm,官方推荐) | RAID0(同样做法) |
| RAID能否给持久性 | 否(绑同一host,host挂全丢) | 否(同理,绑实例) |
| 持久数据该用 | PD/Hyperdisk | EBS |
👉 完全同构:两家的本地临时盘做RAID0都只提性能/容量、都给不了持久性;持久数据都必须用网络块存储(PD/Hyperdisk 或 EBS)。

**⑤ 评分：6.5/10**。⚠️主要纠正"RAID1提升持久性"——**在Local SSD上无效(镜像也在同一host,host挂全丢)**。记忆点:每块Local SSD=375GB NVMe,**官方推荐RAID0(mdadm)提升容量+IOPS/吞吐**;RAID救不了持久性(数据绑死宿主机,host/stop/delete全丢);持久数据必须用PD/Hyperdisk(独立生命周期+快照+跨zone恢复);对标AWS Instance Store RAID0(同样只提性能不给持久)。

---

**批次 9 小结**：Q17=8、Q18=6.5,均分7.25。重点→**①PD性能=baseline+perGiB×容量(pd-balanced=3000+6/GiB),小盘先天慢;避坑加容量/换类型/上Hyperdisk解耦;对标gp2→gp3 ②Local SSD官方推荐RAID0(mdadm)提性能+容量,每块375GB;⚠️RAID1在Local SSD无意义(镜像同host,host挂全丢);RAID改变不了"绑宿主机+临时"的根本属性,持久数据必须用PD/Hyperdisk;对标AWS Instance Store**。
