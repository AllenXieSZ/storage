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

---

## 批次 2：Q3–Q4（2026-09-04）

### Q3. Permissions Boundary + 与SCP/identity/session关系 + 有效权限取交集
**伟伟答**：不知道。

**② 参考答案(AWS官方核实)**：
- **Permissions Boundary**=附加到User/Role的托管策略,设"该身份能被授予的最大权限上限(ceiling)";⚠️**自己不授予任何权限**,只封顶;最终权限=**identity policy ∩ permissions boundary**(取交集,两边都allow才生效)。
- 典型用途:**安全委派权限管理**——让开发者自助创建角色/用户,但创建出的身份权限不能超过boundary(防提权)。
- **四类策略关系**:授权层(identity-based/resource-based,真正grant,取并集)+上限层(SCP组织级/Permissions Boundary身份级/Session Policy会话级,都不授权只砍权限,取交集)。**有效权限=SCP∩boundary∩session∩(identity∪resource),任一层显式Deny一票否决**。

**③ 概念**:AWS权限两种力=授权(+,只identity/resource能grant)+设上限护栏(-,SCP/boundary/session都不授权只封顶)。最终=所有天花板之内+被某授权策略allow+无显式Deny。多层护栏给不同人管(组织管理员SCP/委派管理员boundary/临时会话session)。

**④ AWS↔GCP对照**:SCP≈GCP Org Policy(组织护栏);⚠️**Permissions Boundary GCP无精确对应**(AWS更精细的身份级上限);授权:AWS identity/resource policy ↔ GCP IAM allow policy。

**⑤ 评分**:未作答(讲解)。记忆点:**Permissions Boundary=User/Role的最大权限上限(托管策略),不授权只封顶,最终=identity∩boundary;用途=安全委派(自建角色不超边界防提权);四类策略=授权层(identity/resource并集)+上限层(SCP/boundary/session交集),显式Deny一票否决;GCP无精确对应(AWS特色),SCP↔Org Policy**。

### Q4. SCP是什么+作用于谁+能否授权+与IAM如何生效
**伟伟答**：scp定义整个org安全策略,作用于整个org。

**① 对照**：✅"组织级安全策略"方向对;🔶"作用于整个org"不精确(可挂Root/OU/账号层层继承);🔶没答"能否授权"(核心:不能);🔶没答与IAM取交集;🔶漏"不影响管理账号"。

**② 参考答案(AWS官方核实)**：
- **SCP**=AWS Organizations组织策略,集中控制成员账号"最大可用权限"(护栏)。**附加层级**:Root(全组织)/OU(该OU及下)/单账号——挂哪层对该层及以下所有账号的所有IAM身份生效,层层继承。**⚠️例外:不影响管理账号(management account)+不影响service-linked role**→别在管理账号跑负载。
- **⚠️能授权吗:不能**。SCP绝不授予权限,只设"最多能用哪些权限"上限;写Allow也只是allowlist(表示"在上限内"),真正权限靠账号内IAM policy授予。
- **与IAM一起**:最终权限=**SCP允许 ∩ IAM授予**(取交集);操作要生效=SCP允许+IAM显式allow+无显式Deny;SCP的Deny压过IAM Allow。两种写法:Deny list(FullAWSAccess+Deny危险操作,常用)/Allow list(删FullAWSAccess只列白名单,严格)。

**③ 概念**:SCP=组织级护栏,站在所有IAM之上先划红线。与Permissions Boundary同类(都上限/不授权/取交集/显式Deny优先),区别=SCP组织级(账号/OU)、boundary身份级。典型:禁关CloudTrail/限region/禁公网S3,再大的账号IAM管理员也越不过组织红线(多账号治理核心)。

**④ AWS↔GCP对照**:**SCP≈GCP Organization Policy**(都组织级/层层继承/只护栏不授权/与IAM取交集);层级AWS Root/OU/Account↔GCP Organization/Folder/Project。

**⑤ 评分：4/10**。⚠️没答"SCP不授权"(核心)+"作用整个org"不精确+没答取交集。记忆点:**SCP=Organizations组织护栏,挂Root/OU/账号层层继承;⚠️不授予权限(只设上限,Allow也只是allowlist);最终=SCP∩IAM,显式Deny压IAM Allow;常用Deny list(FullAWSAccess+Deny危险操作);⚠️不影响管理账号+service-linked role;同Permissions Boundary(SCP组织级/boundary身份级);对标GCP Org Policy,Root/OU/Account↔Org/Folder/Project**。

---

**批次 2 小结**：Q3(讲解)、Q4=4,重点→**①Permissions Boundary=身份级最大权限上限(不授权,identity∩boundary),用途=安全委派防提权;GCP无精确对应 ②SCP=组织级护栏(挂Root/OU/账号继承,不授权,SCP∩IAM,显式Deny优先,不管管理账号),对标GCP Org Policy ③核心规律:授权层(identity/resource,grant,并集)+上限层(SCP/boundary/session,不授权,交集)+显式Deny一票否决——这是IAM权限计算总公式**。

---

## 批次 3：Q5–Q6（2026-09-05）

### Q5. IAM policy 结构 + 哪个字段只有 resource-based 才有 + Condition 键 + 显式 Deny 优先
**伟伟答**：IAM 是谁(principal),能够 allow 做什么 action,在什么 condition 下。

**① 对照**：✅抓住骨架"谁+允许+action+condition"方向对;❌**最大坑:把 Principal 当成 IAM policy 通用字段——答反了!Principal 只有 resource-based policy 有且必须有,identity-based(挂 User/Role 那种)恰恰不写 Principal**(核心考点);🔶漏 Resource 字段;🔶只说 allow,没提 Effect 有 Deny、没答"显式 Deny 优先"(核心);🔶Condition 键没举例。

**② 参考答案(AWS官方核实)**：
- 五字段:**Effect**(Allow/Deny)、**Action**(哪些API操作如s3:GetObject)、**Resource**(对哪些资源ARN)、**Condition**(可选,什么条件才生效)、**Principal**(谁)。
- **⚠️Principal:只有 resource-based policy 才有且必须写**(S3 bucket policy / Role trust policy),因为资源不知道谁来访问,必须声明"允许谁动我",且能**跨账号**授权;**identity-based 不写 Principal**(挂在身份上,"谁"已明确)。官方(reference_policies_elements_principal)："You must use the Principal element in resource-based policies"。
- **Condition 常用键**:aws:SourceIp(限来源IP)、aws:PrincipalOrgID(限本Organization内账号,跨账号授权省事)、aws:MultiFactorAuthPresent(要求MFA)、aws:SecureTransport(强制HTTPS)、aws:RequestedRegion(限region)、s3:prefix(限S3路径)。
- **显式 Deny 优先=是,一票否决**:①默认隐式拒绝→②任一显式Allow放行→③**任何显式Deny压倒所有Allow**。设计理由:拒绝必须比允许强,一条Deny兜底(如SCP禁关CloudTrail)无论下面怎么Allow都堵死。

**③ 概念**:policy=判定一次API请求是否放行的规则集=Effect×Action×Resource×Condition×Principal(仅资源侧)。identity-based答"这身份能干啥"(无Principal);resource-based答"谁能动我"(必带Principal,可跨账号)。伟伟核心错=Principal记反。

**④ AWS↔GCP对照**:AWS Effect/Action/Resource/Condition/Principal ↔ GCP IAM binding(role+members+condition);"谁"=AWS Principal(仅resource-based)↔GCP member;条件=AWS Condition block↔GCP IAM Condition(CEL);显式Deny=AWS核心机制↔GCP传统只allow后加Deny policy(也deny优先);跨账号=AWS resource-based带Principal↔GCP资源上直接绑他项目member。

**⑤ 评分：4/10**。⚠️Principal记反(核心)+漏Resource/Effect的Deny/显式Deny优先。记忆点:**IAM policy五要素=Effect(Allow/Deny)+Action+Resource+Condition+⚠️Principal(只resource-based有且必须,identity-based不写);Condition常用aws:SourceIp/aws:PrincipalOrgID/aws:MultiFactorAuthPresent;评估三铁律=默认拒绝→任一Allow放行→显式Deny一票否决**。

### Q6. STS + 三种AssumeRole场景 + 临时凭证字段 + 能否撤销
**伟伟答**：STS是临时授权,比如Backup运行时assume role,运行状态授权。

**① 对照**：✅"STS=临时授权"核心对;✅**"Backup运行时assume role"是很好的真实例子**(AWS Backup用service role,运行时STS发临时凭证代操作资源);✅"运行状态授权"抓住临时/运行时才拿凭证的精髓;🔶太简:三种AssumeRole没区分(重点)、临时凭证字段(SessionToken)没答、"能否撤销"(核心)没答。

**② 参考答案(AWS官方核实)**：
- **STS**=发临时凭证的服务(短命15min~12h自动过期,用完即弃)。Backup例子=服务用role+运行时拿临时凭证的标准范式。
- **三种assume**:①**AssumeRole**=AWS内部身份互扮(跨账号/EC2/Lambda用role/服务如Backup用service role);②**AssumeRoleWithSAML**=企业SAML 2.0 IdP联合(AD/ADFS/Okta员工SSO进AWS);③**AssumeRoleWithWebIdentity**=OIDC/Web身份联合(Google/Facebook/Cognito登录的移动Web app,**EKS IRSA**也走这个)。一句话:内部/跨账号→AssumeRole,企业SAML员工→WithSAML,OIDC/Web/K8s→WithWebIdentity。
- **临时凭证字段**:AccessKeyId(**ASIA**开头,长期是AKIA)+SecretAccessKey+⚠️**SessionToken(临时独有!长期key没有,是区分标志)**+Expiration。
- **能撤销吗**:⚠️**不能直接吊销单份已发临时凭证**(过期前本身有效)。但两个实际手段:①**改Role权限/加显式Deny**(每次API调用实时重评Role当前policy,泄露凭证下次调用被拒,间接但立即生效);②**AWS官方"Revoke active sessions"**(Role上加带aws:TokenIssueTime条件的内联policy,控制台一键,Deny掉某时刻前签发的所有session,旧凭证瞬间全失效、新的不受影响)。③兜底=短命自动过期,爆炸半径限几小时内。

**③ 概念**:STS哲学=机器/临时访问不拿长期密钥。申请assume role→拿短命凭证(带SessionToken)→到期自动重assume续期。泄露也只是几小时内失效的临时钥匙,且可Revoke sessions一键全撤。

**④ AWS↔GCP对照**:AssumeRole↔GCP SA impersonation(generateAccessToken);WithSAML↔Workforce Identity Federation(SAML);WithWebIdentity↔Workload Identity Federation(OIDC);临时凭证含SessionToken↔短命OAuth2 token;Revoke sessions↔撤销/禁用SA或改权限。

**⑤ 评分：5/10**。核心定义对+Backup例子好,但太简。记忆点:**STS=发临时凭证服务(短命自动过期);三种assume=AssumeRole(内部/跨账号/服务如Backup)/WithSAML(企业SAML)/WithWebIdentity(OIDC/Web/EKS IRSA);临时凭证=AccessKeyId(ASIA)+Secret+⚠️SessionToken(临时独有)+Expiration;⚠️不能直接吊销单份,靠①改Role policy/Deny间接立即失效②Revoke active sessions(aws:TokenIssueTime)③短命过期兜底;对标GCP SA impersonation/Workforce+Workload Identity Federation**。

---

**批次 3 小结**：Q5=4、Q6=5,均分4.5。重点纠错→**①⚠️Principal只有resource-based policy有且必须(identity-based不写)——伟伟答反了;policy五要素Effect/Action/Resource/Condition/Principal;显式Deny一票否决 ②STS临时凭证含SessionToken(标志);三种assume分内部/SAML/OIDC;⚠️临时凭证不能直接吊销,靠改policy或Revoke sessions或自动过期**。

---

## 批次 4：Q7–Q8（2026-09-05）

### Q7. 跨账号访问(Role trust policy + AssumeRole + ExternalId) + ExternalId解决什么(confused deputy)
**伟伟答**：对端account授权,本账号授权,ExternalId不知道是什么。

**① 对照**：✅**"对端account授权+本账号授权"抓住双向握手核心**(资源方trust policy允许你assume+发起方identity policy允许自己assume);🔶不够精确:哪边trust policy、哪边identity policy的`sts:AssumeRole`没说清;❌ExternalId不会(核心考点);🔶漏confused deputy、ExternalId须"不可猜测的秘密"。

**② 参考答案(AWS官方核实)**：
- **跨账号双向握手(A访问B)**:①**B(资源方/对端)**建Role,挂访问B资源的权限,并在**trust policy(resource-based,必带Principal)**声明"允许A账号assume":`Principal:{AWS:arn:...:<A>:root}, Action:sts:AssumeRole`;②**A(访问方/本账号)**给自己身份挂identity policy允许`sts:AssumeRole` Resource=B的roleARN;③运行时A调sts:AssumeRole→STS两层校验(A允许assume+B trust允许A)→发临时凭证→A操作B资源。
- **confused deputy(混淆代理人)**:deputy=被信任有权限的中间方(典型=第三方SaaS如Acme代多客户干活)。你建Role信任Acme账号;Acme服务很多客户若用同一账号,攻击者可诱骗Acme用其受信任身份去assume你的Role→Acme成"被搞糊涂的代理人"(有权限但被利用访问了不该访问的账号)。
- **ExternalId堵洞**:=只有你和该第三方之间知道的秘密串,加在trust policy的`Condition:{StringEquals:{sts:ExternalId:"专属秘密"}}`。Acme代你干活带你的ExternalId→通过;别的客户/攻击者不知道你的ExternalId→assume失败。⚠️官方(id_roles_common-scenarios_third-party):ExternalId须**不可猜测**(可用发票号等唯一标识,别用客户名这类易猜的)。只要第三方SaaS跨账号访问你资源就该用ExternalId。

**③ 概念**:跨账号=双向握手(对端trust policy信任+本账号identity policy允许assume,正好用上identity vs resource-based)。ExternalId=第三方多租户下的隔离锁——光信任其账号ID不够(它也服务别人),再加"只有你俩知道的暗号"确认"它这次真代表你来"。

**④ AWS↔GCP对照**:跨账号=AWS Role trust policy+sts:AssumeRole↔GCP资源上绑他项目SA/SA impersonation(roles/iam.serviceAccountTokenCreator);**防混淆代理人=AWS ExternalId条件↔GCP无同名机制**(靠Workload Identity严格audience/subject绑定、per-customer SA)。ExternalId是AWS跨账号(尤其第三方SaaS)特色。

**⑤ 评分：4/10**。抓住双向授权方向,但没说清trust vs identity policy,ExternalId不会。记忆点:**跨账号=双向握手(对端Role trust policy带Principal允许你assume+本账号identity policy允许sts:AssumeRole)→STS两层校验发临时凭证;ExternalId=你与第三方SaaS间"只有彼此知道的秘密串",放trust policy Condition防confused deputy(防服务多客户的第三方被诱骗越权访问你账号),须不可猜测;GCP无精确对应**。

### Q8. IAM Identity Center(原AWS SSO) + 与联合身份/IdP关系 + 与Cognito区别(内部员工vs外部用户)
**伟伟答**：IAM Identity Center是外部授权,需要创建账号,然后可访问AWS资源。Cognito不知道。

**① 对照**：✅"Identity Center→访问AWS资源"方向对;🔶**"外部授权"说反了——Identity Center主要面向组织内部员工**;"需要创建账号"含糊(可内置目录建,也可接外部IdP不必单独建);❌Cognito不会;🔶漏核心区别"内部员工vs外部终端用户"。

**② 参考答案(AWS官方核实)**：
- **IAM Identity Center(原AWS SSO)**=集中管理**组织内部人员**访问多个AWS账号和应用的服务。①SSO:员工登一次进Organization下多个AWS账号(按permission set分权)+各SAML/云应用;②身份来源灵活:内置目录建用户,或**接外部IdP(Okta/Entra ID/AD/Ping,SAML+SCIM)**做联合登录=AWS侧联合登录枢纽;③permission set定义"某组人在某账号有什么权限",登录自动assume角色。与联合身份/IdP关系:它是把企业IdP接进来、统一分发到多账号/多应用那一层,**面向内部员工**。
- **Amazon Cognito**=面向**你app的外部终端用户(客户)**的身份服务(你自己开发的移动/Web app的注册登录+用户目录)。①**User Pool**:管终端用户注册/登录/MFA/社交登录(Google/Facebook/Apple)+企业IdP;②**Identity Pool**:把登录用户换成AWS临时凭证(走**AssumeRoleWithWebIdentity**)让app用户访问S3/DynamoDB等。一句话=给你的应用装一套用户登录系统,对象是海量外部客户。
- **核心区别(内部员工vs外部用户)**:Identity Center=内部员工SSO到多AWS账号/内部应用(员工数量级);Cognito=外部终端用户登录你的app(可百万级)。拿AWS权限:Identity Center靠permission set assume账号角色;Cognito靠Identity Pool的AssumeRoleWithWebIdentity换临时凭证。

**③ 概念**:分界线=员工进公司AWS/内部系统→Identity Center;客户登录你做的App→Cognito。伟伟把Identity Center说成"外部授权"反了——它管内部;真正管外部终端用户的是Cognito(这是本题核心考点)。

**④ AWS↔GCP对照**:内部员工SSO多账号=AWS Identity Center↔GCP Cloud Identity/Workspace+Workforce Identity Federation;外部app用户登录=AWS Cognito↔GCP Firebase Auth/Identity Platform;app用户换云临时凭证=Cognito Identity Pool(WithWebIdentity)↔Identity Platform+STS token交换。记:Identity Center↔Workforce(员工),Cognito↔Firebase Auth(app外部用户)。

**⑤ 评分：3/10**。Identity Center方向沾边但把"内部"说成"外部";Cognito不会;核心分工没答。记忆点:**IAM Identity Center(原AWS SSO)=面向组织内部员工的SSO中枢(一次登录进多AWS账号/应用,可接企业IdP统一分发,permission set分权);Amazon Cognito=面向app外部终端用户的身份服务(User Pool管注册登录+Identity Pool用AssumeRoleWithWebIdentity换AWS临时凭证);核心分界:内部员工→Identity Center,外部app用户→Cognito;对标GCP Workforce Identity/Firebase Auth-Identity Platform**。

---

**批次 4 小结**：Q7=4、Q8=3,均分3.5(本批偏弱)。重点纠错→**①跨账号=双向握手(对端trust policy带Principal+本账号identity policy允许sts:AssumeRole);ExternalId=第三方SaaS专属秘密串,防confused deputy(混淆代理人),须不可猜测,GCP无对应 ②⚠️Identity Center管「内部员工」SSO多账号(不是外部!),Cognito管「外部app终端用户」注册登录——这是最易混的核心分界,伟伟这次把Identity Center说成外部授权,记牢:内部员工=Identity Center,外部用户=Cognito**。
