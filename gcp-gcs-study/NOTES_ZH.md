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
