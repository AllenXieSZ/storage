# GCP Cloud Storage (GCS) 面试题库（20 题）

> 生成日期：2026-09-02
> 用法：伟伟每次过 **2 道**，答完我逐题批改（对照答案 + 完整参考答案原理 + 概念详解 + AWS↔GCP 对照 + 评分）。
> 进度记录见文件末尾「进度追踪」。
> 铁律：批改必须完整展开，每题含 ①对照 ②参考答案+原理 ③概念详解 ④AWS对照 ⑤评分。答完即停，不预告不催。

---

## 一、基础与存储类别（Storage Classes）

**Q1.** GCS 有哪几种 storage class？分别的定位、最低存储时长（minimum storage duration）和典型使用场景是什么？

**Q2.** GCS 的 storage class 是设在 bucket 级还是 object 级？如果一个对象长期不访问，如何让它自动降级到更便宜的存储类别？和 AWS S3 的做法有什么不同？

---

## 二、位置与冗余（Location & Redundancy）

**Q3.** GCS 的 location type 有哪三种（region / dual-region / multi-region）？它们在可用性、延迟、跨区冗余、成本上分别有什么区别？

**Q4.** 什么是 GCS 的 Turbo Replication？它解决什么问题、用在哪种 location type 上、RPO 目标是多少？

---

## 三、一致性与命名（Consistency & Naming）

**Q5.** GCS 对象操作的一致性模型是什么（强一致 / 最终一致）？哪些操作是强一致、哪些是最终一致？和 S3 现在的一致性模型对比。

**Q6.** GCS 是扁平命名空间（flat namespace）还是真有目录结构？"文件夹"是怎么实现的？这对 list 操作和性能有什么影响？

---

## 四、访问控制与安全（IAM / ACL / Security）

**Q7.** GCS 有哪两套访问控制机制（IAM 与 ACL）？两者的区别、优先级、以及 Uniform bucket-level access 是什么、为什么推荐开启？

**Q8.** 什么是 Signed URL？它和 IAM 授权有什么区别？典型使用场景是什么？签名 URL 的有效期与权限如何控制？

**Q9.** GCS 静态加密（encryption at rest）默认怎么做？CMEK 和 CSEK 分别是什么、区别在哪？对应 AWS S3 的 SSE-S3 / SSE-KMS / SSE-C 是什么关系？

**Q10.** 如何防止 GCS bucket 数据被误删或恶意删除？列举 Object Versioning、Soft Delete、Retention Policy、Bucket Lock、Object Hold 各自的作用和区别。

---

## 五、生命周期与成本（Lifecycle & Cost）

**Q11.** GCS Object Lifecycle Management 支持哪些 action 和 condition？举例一条"90 天后转 Nearline、365 天后删除"的规则逻辑。

**Q12.** GCS 的费用由哪几部分构成（storage / network egress / operations / retrieval)？为什么 Coldline/Archive 存储便宜但取回可能更贵？early deletion 费用是怎么回事？

**Q13.** 什么是 Requester Pays？开启后谁付哪部分钱？适用于什么场景？

---

## 六、性能与传输（Performance & Data Transfer）

**Q14.** GCS 单个对象上传，simple upload / multipart(XML API) / resumable upload 分别适用什么场景？resumable upload 的核心价值是什么？

**Q15.** 大规模上传/下载时如何提升 GCS 吞吐？（并行 composite upload、gcloud storage 并行、请求分散到多前缀等）GCS 是否像 S3 那样有"每前缀请求速率上限"需要打散 key 前缀？

**Q16.** 把本地数据中心 PB 级数据迁移到 GCS，有哪些方案？（Storage Transfer Service、Transfer Appliance、gcloud storage）各自适用规模和场景。

---

## 七、集成与高级特性（Integration & Advanced）

**Q17.** 什么是 GCS 的 Pub/Sub notifications（Object change notifications）？典型用途是什么？对应 AWS S3 Event Notifications 的关系。

**Q18.** GCS 的 Autoclass 是什么？它和手动配置 Lifecycle 规则相比有什么优劣？适合什么客户？

**Q19.** 什么是 gsutil vs gcloud storage？为什么 Google 现在推荐用 gcloud storage？在性能上有区别吗？

**Q20.** GCS 如何作为静态网站托管 / CDN 源？和 Cloud CDN、Load Balancer 怎么配合？公开访问一个 bucket 要注意什么（尤其在开了 Uniform bucket-level access 之后）？

---

## 进度追踪

| 批次 | 题号 | 状态 | 得分/备注 |
|------|------|------|-----------|
| 1 | Q1-Q2 | 未开始 | |
| 2 | Q3-Q4 | 未开始 | |
| 3 | Q5-Q6 | 未开始 | |
| 4 | Q7-Q8 | 未开始 | |
| 5 | Q9-Q10 | 未开始 | |
| 6 | Q11-Q12 | 未开始 | |
| 7 | Q13-Q14 | 未开始 | |
| 8 | Q15-Q16 | 未开始 | |
| 9 | Q17-Q18 | 未开始 | |
| 10 | Q19-Q20 | 未开始 | |
