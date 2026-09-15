# GCP 数据库 —— 批改归档（NOTES）

> 每批改完一组（2 题）立即追加到此文件并推 GitHub，保留完整五板块批改正文。
> 题库见 `QA_ZH.md`（10 模块 20 题）。

---

## 批次 2 · 第二模块 Cloud SQL 高可用与扩展 · Q3/Q4（2026-09-15）

### Q3 高可用 HA — 评分 2.5/10

**小帅作答**：高可用是通过 regional persistent disk 实现数据复制，提供的是读扩展，需要手动切换。

**逐点对照**
- ✅ 底层是 regional persistent disk —— 对（半对，加分项）
- ❌ 说 HA "提供读扩展" —— 错。HA 提供可用性；standby 实例**不可读**。读扩展是只读副本的活。
- ❌ 说 "需要手动切换" —— 错。failover 全自动（心跳每秒检测，多次丢失自动切）。手动 failover/failback 只是可选运维操作。

**参考答案要点**
1. HA = 区域级实例：同 region 内 主zone(primary)+从zone(standby)。同步复制到两 zone 的 regional persistent disk —— 每笔写要两 zone 都落盘才 commit（RPO≈0）。
2. 自动 failover；primary/standby **共享同一静态 IP**，切换后连接地址不变；RTO 几十秒级。failover 后不自动切回，想切回做 failback。
3. HA 是**跨 zone（同 region）不是跨 region**。跨 region 容灾靠 cross-region read replica + promote。
4. HA=高可用（管活着），standby 不可读不可写；只读副本=读扩展（可读，不自动接管写）。本质区别：同步 vs 异步、可用性 vs 性能扩展。

**概念深入**：同步(HA,RPO0,写延迟略高) vs 异步(副本,有 lag,RPO>0)；共享静态 IP 是 failover 对应用透明的核心；新版 HA 的 standby 不可读（区别于 legacy HA）。

**GCP↔AWS**：Cloud SQL HA ≈ RDS Multi-AZ。都同步+自动failover+备节点不可读（Multi-AZ instance）。差异：GCP 共享 IP 漂移 vs AWS DNS endpoint 切换；AWS Multi-AZ DB Cluster 的 reader 可读、RTO 更短(<35s)。

**记忆点**：HA = 同region跨zone + 同步复制(regional PD) + 自动failover(共享IP,地址不变) + standby不可读 + RPO≈0/RTO几十秒。HA管"活着"，不管"读得快"。

---

### Q4 只读副本与读扩展 — 评分 5/10

**小帅作答**：只读副本是异步复制，可以手动 promote，cascading replica 是外部副本。一个 primary + 读扩展。

**逐点对照**
- ✅ 只读副本异步复制 —— 对
- ✅ 可手动 promote —— 对
- ❌ "cascading replica 是外部副本" —— 错。级联副本 ≠ 外部副本，两个独立概念。
- △ "一主+读扩展" —— 方向对但架构题没展开。

**参考答案要点**
1. 只读副本 = primary 的只读拷贝，异步复制（有 lag），分摊读/分析流量 = 读扩展。
2. 能跨 region（cross-region read replica：就近读/DR/迁移）；能 promote 成独立主实例（不可逆）。
3. **级联副本 cascading** = 副本的副本（primary→副本A→副本B），减 primary 复制分发压力，都在 Cloud SQL 内。**外部副本 external / 从外部源复制** = 跨 Cloud SQL 边界：external read replica，或源库在外部(本地自建)、Cloud SQL 作副本从它复制（上云迁移，配 source representation instance）。两者完全不同，别混。
4. 生产架构 = HA(primary+standby 同步,保可用) + 多个只读副本(异步,分散不同zone,保读扩展) + 跨region只读副本(就近读+DR,可promote)；应用做读写分离(写→primary共享IP，读→副本，副本挂回退primary)。

**概念深入**：异步→复制延迟→读一致性（读己之写要读 primary）；可给只读副本自身开 HA；promote 不可逆。

**GCP↔AWS**：读副本≈RDS读副本(异步/可promote/可跨region)；级联≈RDS read replica of read replica；从外部源复制≈RDS原生复制/DMS CDC。GCP 无 Aurora Reader Endpoint，读写分离要应用自己做。

**记忆点**：只读副本=异步+只读+分摊读+可跨region+可promote(不可逆)。级联=副本的副本(云内副本链)；外部=跨云边界(外部库/迁移,配source representation instance)。生产=HA(同步保可用)+多zone只读副本(异步保读扩展)+跨region副本(就近读+DR)。
