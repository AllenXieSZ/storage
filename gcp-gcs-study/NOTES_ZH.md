# GCP GCS 练习题 —— 批改与知识点沉淀

> 配套题库：`./QA_ZH.md`
> 每批（2 题）批改后追加到本文件并推送 GitHub。
> 每题批改结构：①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP 对照 ⑤评分。

---

## 批次 1：Q1–Q2（2026-09-02）

### Q1. GCS storage class 定位 / 最低存储时长 / 场景

**伟伟答**：standard 频繁 / nearline 温每月一次 / cold 每季度 / archive 合规存档；最低时长不知道；所有都是毫秒级取回。

**对照**：
- ✅ 四种 class 定位全对。
- ✅✅ "所有 class 毫秒级取回" 答得非常好——这是 GCS 相对 AWS 的核心差异。
- ❌ 最低存储时长没答（必背考点）。

**参考答案（表）**：

| Class | 访问频率 | 最低存储时长 | 取回延迟 | 场景 |
|-------|---------|------------|---------|------|
| Standard | 频繁/热 | 无（0 天）| 毫秒 | 网站、流媒体、活跃数据 |
| Nearline | 约每月一次 | **30 天** | 毫秒 | 备份、月报 |
| Coldline | 约每季度一次 | **90 天** | 毫秒 | 灾备、季度归档 |
| Archive | ≤ 每年一次/合规 | **365 天** | 毫秒 | 合规长期存档、磁带替代 |

**原理**：越冷单价越低，用"最低存储时长承诺"换低价；在最低时长内删除/覆盖/改 class 会收 **early deletion 提前删除费**（补差额天数的存储费）。

**概念**：GCS 所有 class 都是**毫秒级 first-byte 取回**，冷热差别只在**价格结构**（存储单价 + 取回费 + 最低时长），不在速度。

**AWS↔GCP 对照**：

| | AWS S3 | GCP GCS |
|--|--------|---------|
| 热 | S3 Standard | Standard |
| 温 | Standard-IA（30 天）| Nearline（30 天）|
| 冷（毫秒取回）| Glacier Instant Retrieval（90 天）| Coldline（90 天）|
| 深冷 | Glacier Flexible / Deep Archive（**取回分钟~12h，需解冻 restore**）| Archive（365 天，**仍毫秒取回**）|

👉 **黄金记忆点**：GCS 冷 class 收"最低时长 + 取回费"，但**取回永远毫秒级、无 Glacier 式解冻等待**。

**评分：6.5 / 10**（定位+毫秒取回好；最低时长 30/90/365 必背）。

---

### Q2. storage class 设在哪级 / 如何自动降级 / 与 AWS 不同

**伟伟答**：storage class 是 object 级别？可以用生命周期移动。

**对照**：
- ✅ object 级——对。
- 🔶 漏了 bucket 有 default storage class 这层。
- ✅ 用 Lifecycle 自动降级——对；🔶 漏了 Autoclass。
- ❌ 没做 AWS 对照。

**参考答案**：
- **层级**：bucket 有 default storage class；每个 object 有自己的 class，不指定则继承 bucket 默认。**最终作用在 object 级**。
- **自动降级两法**：
  1. **Object Lifecycle Management**：手动规则，如 age>90 → SetStorageClass Nearline。精细但要自己设计。
  2. **Autoclass**：bucket 开关，按对象实际访问**自动双向升降级**（没访问降冷、被访问升回 Standard），无需规则、无取回费。适合访问模式不确定。

**概念**：Lifecycle 常用于**单向变冷**，不能自动升回热；**只有 Autoclass 双向自动**。手动改单对象 class 会触发 rewrite。

**AWS↔GCP 对照**：

| | AWS S3 | GCP GCS |
|--|--------|---------|
| class 级别 | object 级（bucket 无 default class）| object 级 + **bucket 有 default class** |
| 规则降级 | S3 Lifecycle transition | Object Lifecycle Management |
| 智能自动分层 | **S3 Intelligent-Tiering**（收监控费）| **Autoclass**（无取回费/无监控费）|

👉 **记忆点**：Autoclass ≈ Intelligent-Tiering（都自动分层），区别在计费细节。

**评分：6 / 10**（object 级 + Lifecycle 对；漏 bucket default class、Autoclass、AWS 对照）。

---

**批次 1 小结**：均分 ~6.25。重点补强 → ①最低存储时长 30/90/365；②Autoclass（双向自动分层，对标 Intelligent-Tiering）；③bucket default class 层级。

---

## 批次 2：Q3–Q4（2026-09-02，完整展开版）

### Q3. location type：region / dual-region / multi-region

**伟伟答**：region 成本低/可用性低/延迟低；dual & multi 成本高，multi 最高。

**① 对照**：
- ✅ region 成本低、延迟低 —— 对。
- ❌ **"region 可用性低"错** —— 单 region 内部跨多 zone 冗余，抗 zone 故障，SLA 仍 99.99%；缺的是 region 级冗余（不抗区域灾难），不是可用性低。
- ✅ multi 最贵 —— 对。
- ❌ 漏 dual-region "你指定的两个具体 region" 核心特征；❌ 没区分 zone 冗余 vs region 冗余。

**② 参考答案**：

| type | 数据放哪 | 冗余 | 可用性SLA | 延迟 | 成本 | 场景 |
|------|---------|------|----------|------|------|------|
| Region | 单region内跨多zone | zone级 | 99.99% | 最低 | 最低 | 数据计算同区、低延迟、大数据 |
| Dual-region | **你指定的两个region**(如nam4) | region级 | 99.95% | 低 | 中 | 跨区容灾+低延迟+数据驻留可控 |
| Multi-region | 大区内Google自选多region(US/EU/ASIA) | region级(大范围) | 99.95% | 略高 | 最高 | 全球分发、高可用读、CDN源 |

**原理**：单region天然跨zone冗余(副本在多zone)→抗zone故障、可用性不低；短板=不抗整个region灾难。dual/multi异步复制到地理分离的region→抗区域灾难。dual=你明确指定两region(data residency可控)；multi=选一个大区、具体region由Google定。

**③ 概念**：zone=region内隔离故障域(独立供电/网络)；region=完整地理区域(含多zone)。region给zone冗余，dual/multi再加region冗余。data residency=法规要求数据存某地理边界内，dual能精确满足。

**④ AWS对照**：

| | AWS S3 | GCP GCS |
|--|--------|---------|
| 单区域(跨AZ/zone) | S3标准bucket(跨AZ) | Region(跨zone) |
| 明确双区域 | 无原生单bucket；用CRR复制到另一独立bucket | Dual-region(原生单bucket) |
| 广域多区域 | Multi-Region Access Points(多bucket+路由) | Multi-region(原生单bucket) |

👉 **金句**：GCS dual/multi 是"单bucket原生跨区"(一个endpoint)；AWS 靠 CRR(多独立bucket)或 MRAP(多bucket+路由)拼装。

**⑤ 评分：6/10**。记忆点：Region=zone冗余(延迟成本最低、不抗区域灾难)；Dual=你指定两region(region冗余+低延迟+驻留可控)；Multi=Google大区自选(覆盖最广最贵)。

---

### Q4. Turbo Replication

**伟伟答**：用于 multi-region live replication，RPO 15 分钟 99.9%。

**① 对照**：
- ✅ 跨区持续复制方向对。
- ❌ **用于 multi-region 错(关键)** —— Turbo **只支持 dual-region**，multi-region 不支持。
- 🔶 15min/99.9% 数字对，但那是 **Turbo 开启后的 SLO**，不是默认行为(默认 dual-region 复制无此保证)。
- ✅ 99.9% 对(勿与 AWS RTC 的 99.99% 混)。

**② 参考答案**：
- Turbo Replication = **dual-region bucket 可选开启**的功能，**SLO：99.9% 新写入对象 15 分钟内完成跨region复制**。
- 解决问题：默认 dual-region 复制是异步 best-effort、无时间上限；大对象/高峰复制滞后 → 若此时主region灾难，未复制的新数据丢失、RPO 不可控。Turbo 收紧到 15min/99.9% 强SLO → RPO 更小更可预期。**按复制数据量额外收费**。
- **仅 dual-region**(硬限制)。

**③ 概念**：RPO(Recovery Point Objective)=灾难时可容忍丢失的数据时间窗口，RPO=15min≈最坏丢最近15分钟未复制的新写入。区别 RTO(多久恢复服务)——Turbo 优化 RPO 不是 RTO。异步复制永有窗口，Turbo 是统计SLO 非同步零RPO。

**④ AWS对照**：

| | AWS S3 | GCP GCS |
|--|--------|---------|
| 默认跨区复制 | CRR(异步无强RPO) | dual-region默认异步 |
| 强RPO复制SLA | **S3 Replication Time Control(RTC)**:15min复制99.99% | **Turbo Replication**:15min复制99.9% |
| 作用对象 | 两个独立bucket间(CRR) | 原生dual-region单bucket内 |

👉 **金句**：Turbo ≈ AWS S3 RTC(都是15min强RPO+额外收费)。三区别：①Turbo=单bucket dual-region，RTC=CRR两独立bucket；②99.9% vs 99.99%；③Turbo 只能 dual-region。

**⑤ 评分：4/10**。记忆点：Turbo=dual-region专属，SLO=15min复制99.9%新对象(缩RPO)，额外收费，对标 AWS RTC(15min/99.99%)。

---

**批次 2 小结**：均分 5。补强 → ①region=zone冗余(可用性不低,只是不抗区域灾难)②dual=你指定两region+驻留可控③Turbo 只用于 dual-region、15min/99.9% 是SLO、对标 RTC。

### 批次2 追问补充（伟伟提问）

**Q: multi-region 贵是因为跨region复制流量费吗？**
→ 不是。主因是**存储单价本身更高**（维护多地副本）。GCS 内部跨region复制流量**对用户免费**(含在存储单价里)，不单独计费。唯一例外=Turbo Replication 按复制数据量额外收费。**对照 AWS：CRR 的跨区复制流量是能看到一笔明确 inter-region Data Transfer 费的；GCS 把这成本打包进存储单价。**

**Q: GCE 和 GCS 跨 region，收流量费吗？**
→ 收。规则：
- 同 region（GCE 与 GCS 同区）→ **免费**
- 同大洲跨 region → 收 egress（较低费率）
- 跨大洲 → 收 egress（更贵）
- 出公网/别的云 → 最贵
- 写入(ingress)通常免费；egress 是"从GCS读出去"方向计费。
- multi-region bucket 特例：**大区内的 GCE 访问它一般免 egress**（GCE 落在该 multi-region 地理范围内）。
- **对照 AWS 高度一致**：同region免费、跨region/出公网收egress、上传免费。差别在 multi-region"大区内免费"概念 AWS 无原生等价。
- 省钱：GCE 与高频访问的 bucket 放同 region → 流量费归零。

---

## 批次 3：Q5–Q6（2026-09-02）

### Q5. 一致性模型

**伟伟答**：GCS 强一致(写后读一样)；以前最终一致、传播到其他region才一致；S3也强一致。

**① 对照**：✅ GCS强一致、写后读一致、S3也强一致对；🔶 "以前最终一致"错安到GCS头上(那是S3的历史,2020-12才转强一致；GCS对象操作一直强一致)；❌ 没区分哪些强/哪些最终一致。

**② 参考答案**：
- 强一致(大部分对象操作)：新对象write后读、覆盖写、删除、**list**、metadata、ACL/IAM读取——全部立即一致、全球一致。
- 最终一致(少数)：**权限撤销传播**(有缓存,短暂延迟)、**CDN/浏览器缓存的公开对象**(TTL过期前读旧版本)——这是缓存/传播层,非存储本身。

**③ 概念**：read-after-write/update/delete GCS都保证立即一致。易混：dual/multi-region的跨区副本复制是异步(有延迟),但那是数据冗余复制,不改变"你对bucket读写强一致"。别把跨区异步复制与对象操作一致性混。

**④ AWS对照**：S3 **2020-12前最终一致**(覆盖/删除/list有延迟,著名list延迟坑),之后全面强一致；GCS一直强一致。现在两家对象操作都强一致,残留最终一致都在CDN缓存+权限传播。👉金句:"最终一致的历史是S3的故事,GCS生来强一致"。

**⑤ 评分：6/10**。记忆点:GCS对象操作一直强一致(写后读/覆盖/删除/list立即一致);最终一致只剩权限撤销传播+CDN缓存;S3是2020-12才转强一致。

### Q6. 扁平命名空间 vs 目录结构

**伟伟答**：有architectural架构,对list有提升,bucket级开启,S3没有。

**① 对照**：🔶 答的是HNS(Hierarchical Namespace)新功能,跑题了——题目问GCS**默认**命名空间(答案=扁平)+文件夹怎么模拟。HNS描述本身基本对(bucket级开启、提升list)但没答主干；❌"S3没有"不准(S3有Express directory bucket)；❌没讲扁平下rename慢的原理。

**② 参考答案**：
- GCS**默认扁平命名空间**:无真目录,对象名是扁平key,`/`只是名字里普通字符。
- "文件夹"是**prefix+delimiter模拟**:list时按前缀过滤+按`/`归组显示成文件夹,底层无目录实体。
- 影响:rename"文件夹"=对该前缀下每个对象copy+delete(O(N)),大量对象慢且贵。
- **HNS(可选)**:建bucket时开启(不可改),真目录(folder是实体),目录级原子rename+更快list+初始QPS×8,适合大数据/AI。

**③ 概念**:flat namespace=扁平字符串key,目录靠prefix/delimiter视觉模拟;prefix过滤+delimiter(`/`)归组=假文件夹;扁平下rename慢因无目录指针只能逐对象copy+delete。

**④ AWS对照**:两家默认都扁平、都prefix+delimiter模拟文件夹、rename目录都O(N)。真目录方案:GCS=HNS bucket,AWS=**S3 Express One Zone directory bucket**。👉"S3没有"错,S3有directory bucket。

**⑤ 评分：4/10**。记忆点:GCS默认扁平命名空间,`/`是假目录,rename=O(N) copy+delete;HNS=可选真目录(原子rename/更快list),对标S3 directory bucket。

### 批次3 追问补充：GCS bucket TPS/吞吐上限（查GCP官方文档 request-rate）

- **初始容量(每bucket)**：约 **1000 写/秒**(upload/update/delete) + **5000 读/秒**(list/读数据/读metadata)。对1MB对象≈每月写2.5PB/读13PB。
- **关键:auto-scaling,无公布硬上限**。请求率上升→GCS自动把负载分散到更多服务器,自动提升该bucket容量。官方不给单bucket最大TPS数字。
- **扩展例子(官方唯一具体数)**：1字符随机十六进制前缀(16值)→有效扩展到 **~80,000 读/秒 + 16,000 写/秒**(16倍)。前缀越长扩越高。
- **两规则**:①Ramp-up:超1000写/5000读要从阈值起步、每20分钟翻倍,冲太快撞408/429/5xx要指数退避。②避免顺序命名:GCS按字典序维护key索引,顺序名(时间戳/自增)热点集中→加随机前缀(如MD5前6位)打散。
- **HNS加成**:开HNS的bucket初始QPS上限最多×8(读写都是)。
- **S3对照**:S3是**per-prefix** 3500写/5500读;GCS是**per-bucket初始值+全局auto-scaling**。两家都靠前缀分散冲高、都要ramp-up。真目录高IOPS:S3 Express directory bucket vs GCS HNS。
- ⚠️存疑:第三方站点称GCS默认"5000写/50000读per bucket"与官方1000/5000初始值不符,以官方为准。

---

**批次 3 小结**：Q5=6、Q6=4,均分5。补强→①最终一致历史是S3不是GCS②GCS默认扁平命名空间+prefix/delimiter模拟文件夹③GCS初始1000写/5000读、auto-scaling无硬上限、靠随机前缀+ramp-up冲高。

---

## 批次 4：Q7–Q8（2026-09-02）

### Q7. 访问控制 IAM / ACL / UBLA

**伟伟答**：IAM是用户,ACL是每个对象object,bucket-level access是不是S3 bucket policy。

**① 对照**：✅ IAM用户/项目级、ACL对象级 两个定位对；❌ UBLA类比错(不是bucket policy,是"禁用ACL统一用IAM"的开关,对标S3 Bucket owner enforced);❌ 漏 IAM∪ACL 并集优先级;❌ 漏为何推荐UBLA。

**② 参考答案**：
- **IAM**(推荐主力):project级+bucket级(**不能到单对象**),role绑principal,集中/可继承/可审计/支持Conditions。
- **ACL**(传统):bucket级+**单对象级**(唯一比IAM强处),每对象带(entity,permission)列表,分散难审计易误公开。
- **优先级**:IAM与ACL是**并集(union),任一放行即放行**→ACL可能意外公开,是安全隐患。
- **UBLA**:bucket开关,**开启后禁用ACL、全部只用IAM**。推荐因:消除ACL/IAM双轨泄露风险+集中可审计+安全最佳实践。代价:失去对象级ACL,需差异化授权改用IAM Conditions/Signed URL。

**③ 概念**:principal=用户/组/服务账号/域/allUsers;role(一组permission) vs ACL单permission(READER/WRITER/OWNER);union语义=IAM∪ACL,UBLA消除ACL这一路。

**④ AWS对照**:S3 bucket policy≈**GCS bucket级IAM**(不是UBLA!);S3 Object/Bucket ACL≈GCS ACL;**UBLA≈S3 Bucket owner enforced(禁用ACL)**。S3有显式Deny优先,GCS是并集无ACL Deny。👉纠正:UBLA不是bucket policy,是关ACL的开关。

**⑤ 评分：6/10**。记忆点:IAM(project/bucket级,role绑principal,主力)+ACL(能到对象级,传统易泄露),两者并集放行;UBLA=关ACL只用IAM(对标S3 Bucket owner enforced)。

### Q8. Signed URL

**伟伟答**：临时签名,拿URL指定时间内可访问,给不能登录认证/动态变化的客户端,如匿名浏览。

**① 对照**：✅ 临时签名、限时、给无身份客户端 对;🔶 "匿名浏览"易与"公开对象"混(Signed URL是限时定向授权,非永久公开);❌ 漏与IAM区别;❌ 漏能授权上传(PUT)+最长7天+绑定HTTP方法。

**② 参考答案**：
- Signed URL=URL查询参数带**加密签名+过期时间**,任何人拿到在有效期内按签名限定操作访问,**无需自身身份认证**。
- 机制:用有权凭证(服务账号私钥 或 IAM signBlob)对"对象+HTTP方法+过期时间"签名;GCS验签名有效+未过期即放行,**验的是URL是被授权者签发的,不是访问者身份**。
- 场景:给外部/匿名用户临时下载私有对象(如7天下载链接不建账号);让外部用户**直传上传**(签PUT,客户端直传GCS不过你服务器);前端不便存凭证时后端签发。
- 有效期:签发时定,**V4最长7天**,过期403不可续。权限:绑定具体方法**GET/PUT/DELETE**+指定对象,只能干签的那件事。

**③ 概念**:与"公开对象"区别——allUsers:objectViewer是永久公开,Signed URL是限时/限操作/会过期的定向授权(更安全)。签名靠服务账号私钥或signBlob(不落地私钥更安全)。过期硬性,只能重签。

**④ AWS对照**:**Signed URL≈S3 Presigned URL**,都是带签名+过期的临时URL让无身份者限时限操作访问,常用于外部临时下载/客户端直传。区别在签名凭证来源(GCS服务账号/signBlob vs S3 IAM凭证)。

**⑤ 评分：5/10**。记忆点:Signed URL=带签名+过期的临时URL,拿到即用无需认证,绑定对象+方法(GET/PUT)+时限(最长7天);对标S3 Presigned URL;≠公开对象(那是永久匿名)。

---

**批次 4 小结**：Q7=6、Q8=5,均分5.5。补强→①UBLA=禁用ACL统一IAM(对标S3 Bucket owner enforced),不是bucket policy②IAM∪ACL并集放行③Signed URL能授权上传、最长7天、绑定HTTP方法,≠公开对象。
