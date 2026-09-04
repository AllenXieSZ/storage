# AWS 安全练习题 —— 批改与知识点沉淀

> 配套题库：`./QA_ZH.md`（30 题，每批 2 题）
> 目的：伟伟云安全薄弱点强化训练（承接 GCE 题库暴露的安全类弱项：SA/权限、防火墙、启动/机密计算、检测审计）。
> 结构：①逐点对照 ②参考答案+原理 ③概念详解 ④AWS↔GCP对照 ⑤评分+记忆点。
> 铁律：批改必须完整展开五板块；答完即停，不预告不催。每批改完立即写入本文件并推 GitHub。
> 回答先查 AWS 官方文档核实；不确定标注；旧限制须查最新文档验证。

（批改从批次 1 开始追加。）

---

## 批次 1：Q1–Q2（2026-09-04）

### Q1. IAM User/Group/Role/Policy + identity vs resource-based + 请求评估逻辑
**伟伟答**：user是登录用户,role是权限,Policy=什么资源什么权限给谁;identity从用户角度限制资源,resource based从resource角度。

**① 对照**：✅User=登录用户✓;❌**"Role是权限"错——Role是「身份」(可临时扮演),Policy才是权限**;🔶Policy三要素方向对但"给谁"(Principal)只有resource-based才有;🔶Group漏答;🔶identity/resource"用户角度/资源角度"直觉对但没点resource-based必须带Principal/可跨账号;🔶请求allow/deny评估逻辑没答(核心)。

**② 参考答案(AWS官方核实)**：
- User=长期身份(密码/AKIA);Group=User集合(仅管理容器,非principal不能assume);Role=可临时扮演的身份(assume后STS发临时凭证,**Role是身份不是权限**);Policy=权限本身(JSON:Effect/Action/Resource/Condition)。
- identity-based=挂身份上(无Principal,"这身份能干啥");resource-based=挂资源上(**必须带Principal,能跨账号授权**,"谁能动我")。
- **请求评估三铁律**:①默认隐式拒绝(root除外)②identity或resource任一Allow即放行(**并集union**)③**任何显式Deny压倒一切(explicit deny overrides allow)**。完整链SCP→resource→identity→permission boundary→session policy取交集,显式Deny优先。

**③ 概念**:IAM=身份(谁)+权限(能干啥)两层。身份=User(长期)/Role(临时可扮演);Group只是打包非身份;Policy=权限,可挂身份(identity)或资源(resource)。伟伟最大错=Role当权限(实为身份);评估记"默认拒绝/并集allow/显式deny优先"。

**④ AWS↔GCP对照**:AWS User/Role=身份、**Policy=权限**;GCP SA=身份、**role=权限**(⚠️命名正相反,AWS role是身份/GCP role是权限,最大混淆点,这次踩了)。AWS resource-based policy(带Principal)常用跨账号;GCP靠资源上绑member→role。评估:AWS有显式Deny,GCP传统只allow(后加deny policy)。

**⑤ 评分：5/10**。⚠️Role当权限(实为身份)+评估逻辑没答。记忆点:**User=长期身份/Group=集合(非principal)/Role=临时身份(非权限!)/Policy=权限;identity-based(无Principal)vs resource-based(必带Principal可跨账号);评估三铁律=默认拒绝+任一allow并集+显式Deny压倒;⚠️AWS Role=身份Policy=权限,GCP正相反role=权限SA=身份**。

### Q2. Role vs User本质 + 为何EC2/Lambda用Role + STS AssumeRole拿临时凭证
**伟伟答**：Lambda用access key不能轮转容易泄密;role通过STS拿到token。

**① 对照**：✅"access key不能轮转易泄密"抓住核心痛点✓;✅"role通过STS拿token"机制方向对✓;🔶太简,漏Role vs User本质对比、临时凭证三要素(尤其SessionToken)+自动过期轮转、EC2靠instance profile+IMDS自动取、AssumeRole trust policy两层校验。

**② 参考答案(AWS官方核实)**：
- **Role vs User本质**:User=长期身份+长期凭证(密码/AKIA,长期有效少轮转易泄);Role=临时身份+**无长期凭证**,被assume时STS发**临时凭证(ASIA,15min~12h自动过期)**;Role可被多实体扮演,谁能assume由**trust policy**控。
- **为何EC2/Lambda用Role**:①不落地长期key(代码/镜像/Git泄露=长期钥匙外流)②临时凭证短命+自动续期(爆炸半径小)③免人工轮转④trust policy精细可控可审计。
- **STS AssumeRole链路**:①调sts:AssumeRole②两层校验(调用方identity policy allow sts:AssumeRole + 目标Role trust policy允许该Principal)③返回**三要素AccessKeyId+SecretAccessKey+⚠️SessionToken(临时凭证独有,长期key没有)+过期时间**;到期SDK自动重assume续期。**EC2**靠instance profile(包Role)+IMDS(169.254.169.254)自动取续期;**Lambda**靠execution role自动注入。

**③ 概念**:核心=机器身份不该拿长期钥匙。Role=临时借身份/短命凭证/用完即弃/自动轮转,被攻破也只泄露几小时失效的临时凭证。STS=发临时凭证的机构,AssumeRole=申请临时扮演;临时凭证多一个SessionToken是与长期key的标志区别。与GCE Q10/Q26一脉相承。

**④ AWS↔GCP对照**:AWS IAM Role(instance profile挂EC2)+IMDS取临时凭证(含SessionToken)+STS AssumeRole ↔ GCP Service Account(附加VM)+metadata取OAuth token+SA impersonation。**完全同一设计哲学:机器免密/凭证短命/不落地长期密钥**。长期密钥:AWS长期Access Key / GCP SA JSON key,都不推荐给工作负载。

**⑤ 评分：5/10**。抓住痛点+机制方向但太简。记忆点:**User=长期身份+长期key vs Role=临时身份+STS临时凭证(ASIA,15min~12h自动过期);用Role=不落地长期key+短命自动轮转+trust policy可控;AssumeRole返回三要素含⚠️SessionToken(临时独有);EC2靠instance profile+IMDS自动取,Lambda靠execution role;对标GCP SA+metadata+OAuth token(同哲学:机器免密/凭证短命/不落地长期密钥)**。

---

**批次 1 小结**：Q1=5、Q2=5,均分5。重点纠错→**①⚠️Role是「身份」不是「权限」(Policy才是权限);User=长期身份/Group=集合(非principal)/Role=临时身份/Policy=权限;identity-based(无Principal)vs resource-based(必带Principal可跨账号);评估三铁律=默认拒绝+任一allow并集+显式Deny压倒;AWS Role=身份而GCP role=权限(命名正相反,易混) ②Role vs User=临时凭证vs长期key;用Role不落地长期密钥+短命自动轮转;STS AssumeRole返三要素含SessionToken(临时独有);EC2 instance profile+IMDS自动取;对标GCP SA+metadata+OAuth token同哲学**。
