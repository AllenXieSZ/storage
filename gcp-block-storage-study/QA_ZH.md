# GCP 块存储（Block Storage）练习题库（20 题）

> 生成日期：2026-09-02
> 范围：Persistent Disk (PD)、Hyperdisk、Local SSD、快照、加密、性能、与 AWS EBS 对照
> 用法：伟伟每次过 **2 道**，我逐题完整批改（①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点）。
> 铁律：批改必须完整展开五板块；答完即停，不预告不催。

---

## 一、Persistent Disk 基础

**Q1.** GCP Persistent Disk (PD) 有哪几种类型（pd-standard / pd-balanced / pd-ssd / pd-extreme）？各自的定位、性能特征和典型场景是什么？

**Q2.** Persistent Disk 是块存储还是对象存储？它和挂载它的 VM(GCE) 是什么关系？VM 删除后 PD 会怎样？如何让 PD 独立于 VM 生命周期存在？

## 二、Hyperdisk（新一代块存储）

**Q3.** 什么是 Hyperdisk？它和传统 Persistent Disk 最大的区别是什么？有哪几种类型（Balanced / Extreme / Throughput / ML）？

**Q4.** Hyperdisk 最重要的特性是"性能与容量解耦"——这是什么意思？为什么它比 PD 更灵活？举例说明如何单独调整 IOPS/吞吐而不改容量。

## 三、Local SSD

**Q5.** 什么是 Local SSD？它和 Persistent Disk 在物理位置、持久性、性能上有什么本质区别？

**Q6.** Local SSD 的数据在什么情况下会丢失？为什么它不适合存重要数据？典型使用场景是什么？

## 四、性能与规格

**Q7.** Persistent Disk 的性能（IOPS/吞吐）由什么决定？为什么说"PD 性能和容量、以及挂载它的 VM 规格都相关"？

**Q8.** 什么是 zonal PD 和 regional PD？regional PD 如何提供高可用？它的写入机制（同步复制到两个 zone）对性能有什么影响？

**Q9.** 一块 PD 可以同时挂载到多个 VM 吗？什么是 multi-writer 模式和只读多挂载（read-only multi-attach）？各自的限制是什么？

**Q10.** 如何在不停机的情况下扩展一块 PD 的容量？能缩小吗？扩容后文件系统层面还需要做什么？

## 五、快照与备份

**Q11.** PD 快照（snapshot）是怎么工作的？第一次快照和后续快照在存储上有什么区别（增量快照）？快照存在哪里？

**Q12.** 快照是 zonal、regional 还是 global 资源？能否用一个 zone 的快照在另一个 region 恢复磁盘？这对跨区容灾/迁移有什么意义？

**Q13.** 什么是 Snapshot Schedule（快照计划）？如何用它做自动定期备份 + 保留策略？和手动快照相比有什么优势？

## 六、加密与安全

**Q14.** GCP 块存储默认加密怎么做？CMEK 和 CSEK 在 PD 上分别是什么？和对象存储(GCS)的加密概念一致吗？

**Q15.** 如果用 CSEK 加密一块 PD，密钥丢了会怎样？创建快照、扩容等操作对 CSEK 加密盘有什么额外要求？

## 七、性能优化与实战

**Q16.** 想给一个数据库工作负载选块存储，pd-ssd / pd-extreme / Hyperdisk Extreme 怎么选？关键考量是什么（IOPS 需求、延迟、成本）？

**Q17.** 为什么小容量的 pd-standard/pd-balanced 性能很差？"性能随容量线性增长"是什么机制？怎么避免小盘性能瓶颈？

**Q18.** Local SSD 如何组建 RAID 提升性能/容量？为什么即使做了 RAID，Local SSD 仍不能替代 PD 存持久数据？

## 八、与 AWS 对照

**Q19.** GCP 的 PD / Hyperdisk / Local SSD 分别对应 AWS 的什么服务？逐一对照（含 gp3/io2/instance store 等）。

**Q20.** Hyperdisk 的"性能与容量解耦"对标 AWS 哪个特性（gp3 独立配置 IOPS/吞吐）？两家在"块存储性能可独立调整"上的演进思路是否一致？

---

## 进度追踪

| 批次 | 题号 | 状态 | 得分/备注 |
|------|------|------|-----------|
| 1 | Q1-Q2 | ✅已批改 | Q1=6 Q2=6 均6 |
| 2 | Q3-Q4 | ✅已批改 | Q3=6.5 Q4=7 均6.75 |
| 3 | Q5-Q6 | ✅已批改 | Local SSD;更正:stop/delete丢,reboot/维护事件可保留 |
| 4 | Q7-Q8 | ✅已批改 | Q7=7.5 Q8=5 均6.25;纠错:regional PD跨zone非跨region |
| 5 | Q9-Q10 | 未开始 | |
| 6 | Q11-Q12 | 未开始 | |
| 7 | Q13-Q14 | 未开始 | |
| 8 | Q15-Q16 | 未开始 | |
| 9 | Q17-Q18 | 未开始 | |
| 10 | Q19-Q20 | 未开始 | |
