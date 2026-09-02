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
