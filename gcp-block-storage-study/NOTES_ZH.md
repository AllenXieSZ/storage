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
