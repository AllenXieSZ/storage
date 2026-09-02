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

---

## 批次 5：Q9–Q10（2026-09-02）

### Q9. 静态加密 默认/CMEK/CSEK

**伟伟答**：数据存硬盘的加密,客户可自己管理密钥,可自己带密钥。

**① 对照**：✅ 落盘加密、能自管密钥、能自带密钥 三个方向对;❌ 没答默认=Google托管(强制零运维);🔶 没点名CMEK(Cloud KMS)/CSEK术语,没讲清密钥存哪谁托管;❌ 没做SSE对照。

**② 参考答案**：
- **默认 Google-managed**：所有对象默认AES-256加密,零操作,Google全管密钥。信封加密:DEK加密数据,KEK加密DEK。
- **CMEK**：密钥存**Cloud KMS**、你创建管理(轮换/禁用/销毁),GCS用你的KMS key当KEK。价值:控制密钥生命周期(禁用key=立即不可解密)+合规审计。密钥仍在Google设施内,管理权归你。
- **CSEK**：你客户端生成key,**每次请求把key传给GCS**(请求头),**Google不存**(只留key的hash校验)。丢key=数据永久无法解密。控制权最高、运维/丢钥风险最大。

**③ 概念**:信封加密本质=谁掌控KEK(默认Google/CMEK你在KMS/CSEK你自带不存)。CMEK vs CSEK:CMEK托管KMS你管理,CSEK你自持每请求带Google不存。

**④ AWS对照(重点,完美一一对应)**:
| | AWS S3 | GCS |
|--|--------|-----|
| 云托管零管理 | SSE-S3 | Google-managed(默认) |
| 云KMS你管理 | SSE-KMS | CMEK(Cloud KMS) |
| 自带密钥云不存 | SSE-C | CSEK |
👉 SSE-S3≈Google-managed, SSE-KMS≈CMEK, SSE-C≈CSEK。

**⑤ 评分：6/10**。记忆点:默认Google-managed(≈SSE-S3);CMEK=KMS你管理(≈SSE-KMS);CSEK=自带每请求带Google不存丢了没救(≈SSE-C)。

### Q10. 防误删/恶意删除机制

**伟伟答**：versioning多版本;soft delete保存7天;retention policy=删除后继续保存多少天;lock=不能删除。

**① 对照**：✅ versioning多版本对;🔶 soft delete默认7天对但可配0-90天;❌ **retention policy语义讲反**(不是删除后保存,是"删除前必须存够最短时长才允许删");🔶 lock不完整(是锁死retention使其不可缩短/移除,不可逆);❌ 漏Object Hold。

**② 参考答案**：
- **可恢复类**：①Object Versioning=覆盖/删除保留旧版本(noncurrent),可翻回。②Soft Delete=bucket级默认开,删除后进保留期可恢复,默认7天可配0-90(0=关)。区别:Soft Delete对"被删对象"兜底(即使没开versioning),Versioning保留覆盖/删除历史版本。
- **禁删类(WORM)**：③Retention Policy=设最短保留时长,**对象存够该时长前任何人不能删/覆盖**(是删除前置门槛,不是删除后宽限)。④Bucket Lock=把retention**锁定/永久化**,锁后不能缩短/移除只能延长,**不可逆**(连owner/Google都解不开)。⑤Object Hold=单对象打hold(event-based/temporary),hold在就不能删/覆盖,无视retention,移除hold才能删。

**③ 概念**:可恢复(Versioning/Soft Delete=删了能捞回) vs 禁删(Retention/Lock/Hold=根本不让删)。**Retention Policy语义纠正**:保留期未满→禁止删除,是前置门槛,与Soft Delete(删后保留可恢复)方向相反。Bucket Lock不可逆(高频考点)。

**④ AWS对照**:
| 机制 | S3 | GCS |
|------|----|----|
| 多版本 | S3 Versioning | Object Versioning |
| 删除兜底 | 无独立soft delete(靠versioning+删除标记) | Soft Delete(默认7天,独立) |
| 最短保留禁删 | Object Lock Retention(Governance/Compliance) | Retention Policy |
| 锁死不可逆 | Compliance mode | Bucket Lock |
| 单对象冻结 | Legal Hold | Object Hold |
👉 Retention+Lock≈S3 Object Lock Compliance;Object Hold≈S3 Legal Hold;Soft Delete是GCS亮点(S3无独立对等)。

**⑤ 评分：5/10**。记忆点:可恢复=Versioning+Soft Delete(默认7天可配0-90);禁删WORM=Retention Policy(存够才可删)→Bucket Lock(锁死不可逆)+Object Hold(单对象冻结无视retention)。

### 批次5 追问：SSE-C demo 实测（撞到企业级安全策略,重要）

写了 ssec_demo.py(workspace)实测SSE-C上传到S3,结果:
- **本账号(allenxie@amazon.com,386094880462)在启用SCP的Org(o-wadx9m1bah)下,SCP全局禁用SSE-C上传**。对s3lambdatest2和全新bucket都报 AccessDenied "this bucket has blocked SSE-C uploads, specify a different SSE type"。
- 根因:SSE-C密钥完全客户自管、AWS侧无审计痕迹,企业安全合规常用SCP强制禁用,要求改SSE-KMS(有CloudTrail审计)。SCP账号/OU级强制,IAM admin也覆盖不了,不可绕过。
- 未改SCP(组织级安全管控,敏感,不擅动)。
- **面试金句**:SSE-C(对标GCS CSEK)在受SCP管控的企业环境常被禁用(客户自管密钥无审计),合规环境强制SSE-KMS(对标CMEK)替代。
- 代码逻辑正确:256-bit key+SSECustomerAlgorithm/Key/KeyMD5三头,读/写/HEAD都要带key,不带/错key→400/403,S3只存key的MD5不存key,丢key数据永久不可解密。

---

**批次 5 小结**：Q9=6、Q10=5,均分5.5。补强→①默认Google-managed+CMEK(KMS)+CSEK,对标SSE-S3/KMS/C②Retention Policy是"删除前必须存够"不是"删除后保存"③Bucket Lock不可逆+Object Hold单对象冻结④SSE-C常被企业SCP禁用。

---

## 批次 6：Q11–Q12（2026-09-02）

### Q11. Object Lifecycle Management

**伟伟答**：多少天后转下一层或删除;管理保存多少个旧version。

**① 对照**：✅ 转类/删除/numNewerVersions(保留N个版本)三个核心对(版本数是加分点);🔶 action漏AbortIncompleteMultipartUpload;❌ condition只提age漏一堆;❌ 漏"SetStorageClass只能变冷""age从创建算起"两坑。

**② 参考答案**：rule=action+condition。
- Action:①Delete ②SetStorageClass(**只能变冷,不能升热**) ③AbortIncompleteMultipartUpload(清未完成分片省钱)。
- Condition:age/createdBefore/matchesStorageClass/matchesPrefix|Suffix/numNewerVersions/isLive/daysSinceNoncurrentTime/customTime。多条件AND。
- "90天转Nearline+365天删"=**两条独立规则**:rule1 SetStorageClass NEARLINE + age90+matchesStorageClass STANDARD;rule2 Delete + age365。age从创建算起(非从转类算)。

**③ 概念**:转类单向变冷,双向升降靠Autoclass;age基准=创建时间;lifecycle异步每天批处理非实时;AbortIncompleteMultipartUpload省残留分片费。

**④ AWS对照**:Transition/Expiration/AbortMPU对应SetStorageClass/Delete/AbortMPU;Days↔age;NewerNoncurrentVersions↔numNewerVersions。差异:**AWS能按object tag过滤lifecycle,GCS不支持(用prefix/suffix)**;两家转类都只能变冷,升热靠Intelligent-Tiering/Autoclass。

**⑤ 评分：6/10**。记忆点:action(Delete/SetStorageClass只变冷/AbortMPU)+condition(age等AND);两层转换=两条规则,age从创建算;升热靠Autoclass。

### Q12. 费用构成 + 冷存储取回贵 + early deletion

**伟伟答**：存储费、读取费、出网费、检索费。

**① 对照**：✅ 四类费用全列对;❌ 没答题目核心"为何冷存储便宜但取回贵";❌ 没答early deletion;🔶 没提操作费分Class A/B(list是贵的A类)。

**② 参考答案**：四费=
1.Storage($/GB月,冷class单价低)
2.Operations(**Class A贵:写/insert/list/compose;Class B便宜:读/get**;冷class操作单价更贵)
3.Network egress(跨region/大洲/出公网收,同region到GCE+ingress免费)
4.Retrieval(**冷class特有**:从Nearline/Coldline/Archive读数据本身按$/GB收,Standard无)。
- **为何冷便宜取回贵(核心)**:定价权衡——冷class假设存多读少,把成本从存储挪到访问:存储单价压低+每次读加retrieval+更贵操作费。频繁读冷数据会吃掉省下的存储费甚至更贵。
- **Early Deletion**:冷class有最低时长(N30/C90/A365),在到期前删/覆盖/转class,要为剩余未存满天数补交存储费。例:Coldline第10天删→补剩余80天存储费。原理=低单价是"承诺存够"换的,提前删=违约补差额。

**③ 概念**:operations分A/B(list是Class A贵,易误以为便宜);retrieval(读动作本身收,同region也收)≠egress(数据离开Google网络/跨区收),冷class跨区读可能两个都收;early deletion三种触发=删/覆盖/转class。

**④ AWS对照**:S3也是存储/请求/egress/retrieval四类+最低时长+early delete费,定价哲学一致。差异:GCS操作分Class A/B(list属贵A);AWS Glacier深层有取回速度分档(加急/标准/批量不同价),GCS冷class无速度分档(都毫秒取回只收retrieval)。

**⑤ 评分：5/10**。记忆点:四费=存储+操作(A写/list贵,B读)+egress+retrieval(冷class特有);"存便宜读贵"=成本从存储挪到访问;early deletion=最低时长(N30/C90/A365)内删/覆盖/转类补剩余天数存储费。

---

**批次 6 小结**：Q11=6、Q12=5,均分5.5。补强→①SetStorageClass只能变冷+age从创建算+AbortMPU②操作费分ClassA/B(list贵)③冷存储"存便宜读贵"权衡原理④early deletion最低时长内删/覆盖/转类补差额。

---

## 📊 总进度（截至 2026-09-02）

| 批次 | 题 | 主题 | Q得分 | 状态 |
|------|-----|------|-------|------|
| 1 | Q1-Q2 | storage class / 分层 | 6.5 / 6 | ✅ |
| 2 | Q3-Q4 | location type / Turbo Replication | 6 / 4 | ✅ |
| 3 | Q5-Q6 | 一致性 / 扁平命名空间 | 6 / 4 | ✅ |
| 4 | Q7-Q8 | IAM+ACL+UBLA / Signed URL | 6 / 5 | ✅ |
| 5 | Q9-Q10 | 加密(默认/CMEK/CSEK) / 防删机制 | 6 / 5 | ✅ |
| 6 | Q11-Q12 | Lifecycle / 费用构成 | 6 / 5 | ✅ |
| 7 | Q13-Q14 | Requester Pays / upload方式 | - | ⏳ 待做 |
| 8 | Q15-Q16 | 性能吞吐 / 数据迁移 | - | ⏳ |
| 9 | Q17-Q18 | Pub/Sub通知 / Autoclass | - | ⏳ |
| 10 | Q19-Q20 | gcloud storage / 静态网站+CDN | - | ⏳ |

**累计均分 ~5.3/10**。高频补强主题:AWS↔GCP术语一一对应(SSE↔CMEK/CSEK、UBLA↔Bucket owner enforced、Turbo↔RTC、Autoclass↔Intelligent-Tiering)、各种"最低时长/天数"数字、语义方向(Retention Policy是删前门槛)。
**下次从 Q13-Q14 继续。**

---

## 批次 7：Q13–Q14（2026-09-02）

### Q13. Requester Pays

**伟伟答**：适合公开数据集,请求者付request费+出网费,requester必须GCP能识别。

**① 对照**：✅ 公开数据集场景、请求者付操作+出网费、请求者必须可识别 三个关键点对(答得好);🔶 没明说"存储费仍归所有者";❌ 漏落地机制userProject;❌ 漏取回费也归请求者。

**② 参考答案**：默认所有费用bucket所有者付。开Requester Pays后:
| 费用 | 谁付 |
|------|------|
| Storage | **仍所有者** |
| Operations | 请求者 |
| egress | 请求者 |
| Retrieval | 请求者 |
- 请求者必须:①已认证GCP身份(非匿名)②请求带计费项目userProject/x-goog-user-project ③对该项目有serviceusage.services.use权限。没带userProject→400拒绝。
- 场景:公开/共享大数据集,所有者愿免费提供数据(自付存储)但不想承担别人下载的巨额egress。

**③ 概念**:存储费永远归所有者(只转嫁访问相关费);userProject=费用记哪个项目的落地机制;开了之后allUsers匿名白嫖失效(匿名无法指定计费项目)。

**④ AWS对照**:两家都叫Requester Pays,机制一致。所有者付存储,请求者付请求+传输。识别:AWS用header `x-amz-request-payer: requester`,GCP用`userProject`。都禁匿名。动机都是公开大数据集让下载者担流量成本。

**⑤ 评分：7/10**。记忆点:所有者只付存储费,请求者付操作+egress+取回费;请求者须认证+带userProject(不能匿名);场景=公开大数据集不被下载流量拖垮;对标AWS(x-amz-request-payer)。

### Q14. 上传方式 simple/multipart/resumable

**伟伟答**：simple小对象,multipart大对象提并发,resumable网络差,S3没有。

**① 对照**：✅ simple小对象、multipart大对象提并发、resumable网络差 场景方向对;❌ **"S3没有"错**(S3用Multipart Upload实现断点续传);🔶 resumable核心价值没点透"从断点续传不从头重传"。

**② 参考答案**：
- Simple:一次请求传完,小对象+网络稳,失败整个重传。
- Multipart(XML API):切多part**并行**上传再合并,大对象/提吞吐,**为兼容S3 multipart语义**(方便迁移工具复用)。
- Resumable:发起session拿URI,分块传,中断后**从已确认字节offset续传**。大文件+弱网。核心价值=**断点续传,不从0重来**,省时省带宽。

**③ 概念**:simple vs resumable按大小分(client库自动选,超阈值走resumable);multipart(求快/并发) vs resumable(求稳/字节级续传)目的不同;resumable靠session URI+Content-Range偏移续传。

**④ AWS对照(纠正"S3没有")**:
| | S3 | GCS |
|--|----|----|
| 小对象 | PutObject | Simple |
| 大对象并发 | Multipart Upload | Multipart(XML,兼容S3) |
| 断点续传 | **Multipart天然支持**(part保留,ListParts查进度,只补缺失part) | Resumable(session+offset) |
👉 S3用一套Multipart同时做"并发分片+断点续传";GCS拆成两套(Multipart管并发/Resumable管续传)。不是S3没续传,是实现不同。

**⑤ 评分：5/10**。记忆点:Simple小对象;Multipart(XML)大对象并发提吞吐(兼容S3);Resumable弱网断点续传(session+offset);S3不是没续传,用Multipart一套干了并发+续传两件事。

### 批次7 追问：GCS 为何 Multipart 之外还要 Resumable + Resumable 是否分片

- **Multipart vs Resumable 是两套独立机制**:
  - Multipart(XML API)=**多part并发**上传再合并,续传粒度=**part级**(重传整个失败part),为兼容S3。
  - Resumable=**单session顺序**分块(chunk)上传,续传粒度=**字节级**(从offset续),GCS原生推荐大文件/弱网。
  - Multipart求"快"(并发),Resumable求"稳"(字节级续传)。S3用一套Multipart同时满足两者,GCS拆成两套。
- **Resumable有分块吗?有**:分chunk顺序上传,每块用Content-Range标字节范围,中断查已确认offset续传。**但chunk是顺序、不能并发**(chunk N传完才N+1),chunk须256KiB整数倍(末块除外)。想并发提速要用Multipart或**parallel composite upload**(拆多独立对象并行传+compose合并,GCS特有,Q15)。
- 结论:Resumable的分块=顺序/字节级/为续传;Multipart的分片=并发/part级/为提速,两者"分片"不是一回事。

---

**批次 7 小结**：Q13=7、Q14=5,均分6。补强→①Requester Pays存储费仍归所有者+userProject机制②"S3没有resumable"是错的(S3用Multipart续传)③GCS拆分:Resumable=顺序字节级续传(稳),Multipart/composite=并发(快)。

---

## 批次 8：Q15–Q16（2026-09-02）

### Q15. 提升吞吐 + 前缀速率

**伟伟答**：设计好前缀,GCS自动扩展分区,跟S3类似。

**① 对照**：✅ 随机前缀+自动扩展+跟S3类似 核心方向对判断准;❌ 漏parallel composite upload(单文件并发提速GCS特有);❌ 漏gcloud storage并行;🔶 没点透GCS无S3那种per-prefix明确数字。

**② 参考答案**：
- 单大文件:**Parallel composite upload**=切多独立小对象并行传+compose服务端合并(gcloud storage cp超阈值自动),单文件也能多连接打满带宽。坑:crc32c组合checksum,某些CMEK场景不支持compose。
- 多对象:gcloud storage cp默认多线程并发(取代gsutil -m);多机/多进程分片对象列表;随机前缀分散到多后端。
- 底层:auto-scaling(初始1000写/5000读自动扩)+ramp-up(每20min翻倍)+随机前缀避字典序索引热点。

**③ 概念**:composite(多独立对象并行+compose,真并发) vs XML multipart(兼容S3并发) vs resumable(顺序不并发)。**GCS是否有per-prefix上限**:不像S3有明确per-prefix数字,GCS是per-bucket初始+全局auto-scaling+key索引范围重分布。但实践建议一致(随机前缀避热点),所以"跟S3类似"方向对,只是GCS无那个明确数字。

**④ AWS对照**:
| | S3 | GCS |
|--|----|----|
| 速率模型 | per-prefix 3500写/5500读 | per-bucket初始1000/5000+auto-scaling |
| 单文件并发 | Multipart | Parallel composite upload/XML Multipart |
| CLI并行 | aws s3 cp | gcloud storage cp(取代gsutil -m) |
👉 都靠前缀分散+自动扩展;S3有per-prefix明确数字,GCS是per-bucket+auto-scaling。

**⑤ 评分：6/10**。记忆点:单文件用parallel composite upload,多对象用gcloud storage并行/多机分片,随机前缀避热点;GCS auto-scaling(要ramp-up);S3有per-prefix数字(3500/5500),GCS是per-bucket初始+全局扩展。

### Q16. PB级迁移方案

**伟伟答**：STS有网络;想更快用appliance;没网络用gcloud storage。

**① 对照**：✅ STS走网络对、appliance用于大数据量方向有;🔶 appliance定位偏(不是"想更快",是数据量太大/带宽不足);❌ **gcloud storage和"没网络"匹配反了**(gcloud storage需要网络;没网络/带宽不足才用appliance离线寄盘)。

**② 参考答案**：按"数据量+带宽"选:
1.**gcloud storage**(CLI走网络):中小规模+有带宽,一次性/脚本化。PB级不现实除非专线。
2.**Storage Transfer Service(STS)**(托管走网络):大规模在线传输,支持S3/Azure/GCS/HTTP/on-prem(装agent)。托管/可调度/增量/续传/带宽调控。有大带宽专线的数据中心大规模迁移。
3.**Transfer Appliance**(物理离线寄送):Google寄物理设备,拷满寄回导入GCS。**数据量极大(百TB~PB)+带宽不足/传输时间过长**时用(网络传输时间>物理寄送时间就寄盘)。

**③ 概念**:选型公式=数据量÷带宽=传输时间,太长就寄物理设备。纠正:gcloud storage需网络(非"没网络用它");没网络/带宽不足才用Transfer Appliance离线寄盘。例1PB/1Gbps≈100天+不可行→必须appliance。

**④ AWS对照**:
| 场景 | AWS | GCS |
|------|-----|-----|
| CLI走网络 | aws s3 cp/sync | gcloud storage cp |
| 托管在线大规模 | DataSync | Storage Transfer Service |
| 离线物理寄送 | Snowball/Snowmobile | Transfer Appliance |
👉 STS≈DataSync;Transfer Appliance≈Snowball/Snowmobile;gcloud storage≈aws s3 cp。选型都看数据量÷带宽。

**⑤ 评分：4/10**。记忆点:gcloud storage(中小量走网络)→STS(大规模走网络托管可增量,≈DataSync)→Transfer Appliance(PB级带宽不足离线寄盘,≈Snowball)。公式:数据量÷带宽=传输时间,太长就寄盘。gcloud storage要网络,别和"没网络"配。

---

**批次 8 小结**：Q15=6、Q16=4,均分5。补强→①parallel composite upload(单文件并发提速)+gcloud storage并行②GCS无S3那种per-prefix数字(per-bucket+auto-scaling)③迁移选型公式数据量÷带宽,gcloud storage需网络/STS托管在线/Appliance离线寄盘,对标aws s3 cp/DataSync/Snowball。
