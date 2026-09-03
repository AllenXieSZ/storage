# GCP Compute Engine (GCE) 练习题库（30 题）

> 生成日期：2026-09-03
> 范围：机器类型/机型系列、实例生命周期、镜像与启动、MIG/自动伸缩、Spot/抢占、预留与承诺折扣（CUD/SUD）、计费与优化、元数据/启动脚本、维护与实时迁移、GPU/TPU、Sole-tenant、网络/服务账号/安全、与 AWS EC2 对照
> 用法：伟伟每次过 **2 道**，我逐题完整批改（①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点）。
> 铁律：批改必须完整展开五板块；答完即停，不预告不催。每批改完立即写入 NOTES_ZH.md 并推 GitHub（不再丢批改正文）。
> 回答任何点必须先查 GCP 官方文档核实，不确定标注；"旧缺点"须查最新文档验证是否仍成立。

---

## 一、机器类型与机型系列

**Q1.** GCE 的机型系列（machine family）分哪几大类（通用 general-purpose / 计算优化 compute-optimized / 内存优化 memory-optimized / 加速优化 accelerator-optimized）？各自定位和典型系列（E2/N2/N2D/C2/C3/M1/M2/M3/A2/G2 等）与场景是什么？

**Q2.** 什么是 predefined machine type（预定义机型）和 custom machine type（自定义机型）？自定义机型能任意设 vCPU/内存吗？有什么限制（比例、扩展内存 extended memory）？

**Q3.** E2 系列和 N 系列（N1/N2/N2D）有什么区别？为什么 E2 更便宜？"共享核心（shared-core，如 e2-micro/small/medium）"是什么，适合什么场景？

**Q4.** 什么是 vCPU？GCE 的 vCPU 和物理核（core）、超线程的关系是什么？为什么有的机型支持关闭超线程（如设置每核线程数 threads-per-core=1）？

## 二、实例生命周期与状态

**Q5.** GCE 实例有哪些生命周期状态（PROVISIONING / STAGING / RUNNING / STOPPING / TERMINATED / SUSPENDED 等）？stop、suspend、reset、delete 分别是什么，各自对计费和数据的影响？

**Q6.** stop（停止）一个实例后还会为什么付费、不为什么付费？suspend（挂起）和 stop 有什么区别（内存状态、计费）？

## 三、镜像、启动盘与启动配置

**Q7.** 什么是公共镜像（public image）、自定义镜像（custom image）、机器镜像（machine image）？三者区别和用途是什么？

**Q8.** 什么是实例模板（instance template）？它和 MIG 是什么关系？模板能修改吗？

**Q9.** 什么是启动脚本（startup script）和关机脚本（shutdown script）？它们放在哪里（metadata）？和 cloud-init / OS Login 的关系？

**Q10.** GCE 的实例元数据（instance metadata）是什么？如何在实例内访问 metadata server（169.254.169.254）？有哪些常用元数据（如 service account token）？

## 四、托管实例组（MIG）与自动伸缩

**Q11.** 什么是托管实例组（MIG, Managed Instance Group）？它和非托管实例组（unmanaged IG）区别是什么？MIG 提供哪些能力（自动伸缩、自动修复、滚动更新、多区域分布）？

**Q12.** MIG 的自动伸缩（autoscaling）依据哪些指标（CPU 利用率、负载均衡容量、Cloud Monitoring 自定义指标、schedule）？和 AWS ASG 的伸缩策略如何对照？

**Q13.** 什么是 MIG 的自动修复（autohealing）？它靠什么判断实例"不健康"（health check）？和负载均衡的健康检查是同一个吗？

**Q14.** 什么是 zonal MIG 和 regional MIG？regional MIG 如何跨多个 zone 分布实例提供高可用？默认分布方式是什么？

**Q15.** MIG 的滚动更新（rolling update）和金丝雀（canary）发布怎么做？maxSurge / maxUnavailable 是什么？

## 五、Spot / 抢占式与折扣

**Q16.** 什么是 Spot VM 和（旧的）Preemptible VM？两者区别是什么？Spot VM 会在什么情况下被回收？有最长运行时间限制吗？

**Q17.** Spot VM 被回收前会收到什么通知（preemption notice）？给多长时间优雅关机？如何在实例内监听并做 checkpoint？

**Q18.** 什么是持续使用折扣（SUD, Sustained Use Discount）和承诺使用折扣（CUD, Committed Use Discount）？两者区别、适用场景，和 AWS 的 Savings Plans / Reserved Instances 如何对照？

**Q19.** 什么是预留（reservation）？on-demand reservation 和 CUD 是什么关系？预留能保证容量吗？和 AWS Capacity Reservation 如何对照？

## 六、维护、实时迁移与可用性

**Q20.** 什么是主机维护事件（host maintenance event）？GCE 的实时迁移（live migration）是什么，它如何做到维护时不中断实例？哪些实例不能实时迁移（如 GPU/Spot）？

**Q21.** onHostMaintenance（MIGRATE / TERMINATE）和 automaticRestart 这两个可用性策略分别控制什么？GPU 实例的默认行为是什么？

**Q22.** GCE 有哪些高可用手段（regional MIG 跨 zone、多 region、负载均衡、autohealing）？单个 VM 的 SLA 和分布式部署的 SLA 有什么区别？

## 七、GPU / TPU / 专用硬件

**Q23.** GCE 如何挂载 GPU？GPU 能单独作为一种实例吗，还是附加到 VM？A2/G2 加速优化系列和"给 N1 附加 GPU"有什么区别？

**Q24.** 什么是 Sole-tenant node（单租户节点）？它解决什么问题（合规/许可证 BYOL/物理隔离）？和普通共享宿主机的 VM 有什么区别？

## 八、网络、服务账号与安全

**Q25.** GCE 实例的网络接口、内部 IP / 外部 IP、静态 vs 临时 IP 是怎么回事？一个实例能有多个网络接口（multi-NIC）吗？

**Q26.** 什么是实例的服务账号（service account）？默认服务账号 vs 自定义服务账号，access scopes 和 IAM 角色的关系是什么？为什么推荐"自定义 SA + 最小权限 + cloud-platform scope"？

**Q27.** 什么是 Shielded VM、Confidential VM？它们分别防护什么（安全启动/vTPM/完整性监控 vs 内存加密）？

**Q28.** GCE 的防火墙规则（VPC firewall rules）如何作用到实例？network tags 和 service account 在防火墙规则里怎么用？和 AWS 安全组（Security Group）如何对照？

## 九、计费与优化 + AWS 对照

**Q29.** GCE 实例计费的最小计费单位、按秒计费、SUD 自动生效等规则是什么？如何做成本优化（右型 rightsizing 建议、Spot、CUD、关机不删盘等）？

**Q30.** 综合对照：GCE 与 AWS EC2 在 机型命名、计费模型（按秒 vs 按小时/秒）、折扣（SUD/CUD vs SP/RI）、抢占（Spot vs Spot）、伸缩（MIG vs ASG）、维护（live migration vs 事件通知重启）上的核心异同？

---

## 进度追踪

| 批次 | 题号 | 状态 | 得分/备注 |
|------|------|------|-----------|
| 1 | Q1-Q2 | ✅已批改 | Q1=5 Q2=8 均6.5;纠错:4大family/无Mac实例 |
| 2 | Q3-Q4 | ✅已批改 | Q3≈7 Q4提问为主(已给参考答案) |
| 3 | Q5-Q6 | ✅已批改 | Q5=7.5 Q6=8 均7.75;坑:TERMINATED=停止非删除 |
| 4 | Q7-Q8 | ✅已批改 | Q7=6 Q8=8 均7;纠错:machine image=整机快照非机型相关;template不可变 |
| 5 | Q9-Q10 | ✅已批改 | Q9=5.5 Q10=7 均6.25;纠错:GCP叫metadata非user data;需Metadata-Flavor头 |
| 6 | Q11-Q12 | ✅已批改 | Q11=7.5 Q12=7.5 均7.5;纠错:内存非原生伸缩指标 |
| 7 | Q13-Q14 | ✅已批改 | Q13=4 Q14=7 均5.5;纠错:autohealing用应用级HC非ping/CPU |
| 8 | Q15-Q16 | ✅已批改 | Q15=8 Q16=6 均7;纠错:Preemptible会被回收且有24h硬上限 |
| 9 | Q17-Q18 | ✅已批改 | Q17=7 Q18=4 均5.5;纠错:SUD自动无承诺(非按年购买) |
| 10 | Q19-Q20 | 未开始 | |
| 11 | Q21-Q22 | 未开始 | |
| 12 | Q23-Q24 | 未开始 | |
| 13 | Q25-Q26 | 未开始 | |
| 14 | Q27-Q28 | 未开始 | |
| 15 | Q29-Q30 | 未开始 | |
