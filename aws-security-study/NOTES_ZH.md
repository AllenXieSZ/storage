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

---

## 批次 5：Q9–Q10（2026-09-05）

### Q9. EKS IRSA + Pod Identity + Pod免密钥拿AWS权限 + 机制区别 + 对照GCP Workload Identity
**伟伟答**：Service account映射到IAM role获得权限,EBS CSI driver就是例子;EKS Pod Identity也是通过node IAM授权。

**① 对照**：✅**"SA映射到IAM role获得权限"=IRSA本质,完全对**;✅**"EBS CSI driver是例子"举得准**(集群插件靠IRSA拿AWS权限);❌**核心错:"Pod Identity通过node IAM授权"说反了**——Pod Identity恰恰是为摆脱node IAM"一节点所有Pod共享同一套粗粒度权限/过度授权"而设计,走独立的EKS Auth API+node agent(DaemonSet),给每Pod精细隔离权限,不继承node role;🔶漏IRSA底层(OIDC+AssumeRoleWithWebIdentity)、Pod Identity优势、GCP对照。

**② 参考答案(AWS官方核实)**：
- **共同目标**:让Pod免密钥拿AWS权限。三条演进:①硬编码长期key(最差)②node IAM role(简单但危险,同节点所有Pod共享权限,过度授权)③**IRSA/Pod Identity(每Pod精细隔离+临时凭证+免密钥,best practice)**。
- **IRSA**:集群配OIDC provider→K8s SA加注解`eks.amazonaws.com/role-arn`指向IAM Role→Role的trust policy信任该集群OIDC provider(条件绑namespace+SA)→Pod用SA拿projected OIDC token调STS **AssumeRoleWithWebIdentity**(呼应Q6第三种assume)换临时凭证。EBS CSI driver典型。
- **EKS Pod Identity(更新方案,非node IAM!)**:EKS Pod Identity Association把SA关联IAM Role→集群跑`eks-pod-identity-agent` DaemonSet(node agent)拦截凭证请求、本地校验Pod身份、调**EKS Auth API AssumeRoleForPodIdentity**(STS+session tags)发临时凭证。⚠️不靠node IAM;trust policy统一信任`pods.eks.amazonaws.com`,**跨集群可复用同一Role,不用每集群配OIDC provider**。
- **IRSA vs Pod Identity**:机制=OIDC+AssumeRoleWithWebIdentity vs node agent+EKS Auth API;trust=每集群OIDC ARN vs 统一pods.eks.amazonaws.com(可跨集群复用);配置=每集群配OIDC较繁 vs 装agent addon更省;时间=IRSA早/生态广,Pod Identity 2023底推出/AWS现推荐。两者都=每Pod精细/临时/免密钥。

**③ 概念**:演进=硬编码key→node IAM(粗,危险)→IRSA/Pod Identity(细,临时,免密钥)。伟伟核心错=Pod Identity初衷就是取代node IAM过度授权,绝非"通过node IAM授权",它有独立agent+EKS Auth API通道。IRSA用到Q6的AssumeRoleWithWebIdentity。

**④ AWS↔GCP对照**:让Pod免密钥拿云权限=AWS IRSA/Pod Identity↔**GKE Workload Identity**;绑定=K8s SA↔IAM Role vs K8s SA↔GCP SA;底层=OIDC+AssumeRoleWithWebIdentity/EKS Auth API↔GKE metadata server换SA token;反面粗粒度=node IAM role↔node默认SA(都所有Pod共享)。哲学一致:K8s SA映射云IAM身份,Pod免密钥拿短命凭证,替代整节点共享一套权限。

**⑤ 评分：6/10**。IRSA答得好(SA↔Role+EBS CSI例子准),但Pod Identity说成node IAM是核心错(它恰恰要摆脱node IAM)。记忆点:**IRSA=OIDC provider+SA注解映射IAM Role,Pod拿OIDC token调AssumeRoleWithWebIdentity换临时凭证(EBS CSI典型);EKS Pod Identity=更新方案,eks-pod-identity-agent(DaemonSet)+EKS Auth API AssumeRoleForPodIdentity,trust统一信任pods.eks.amazonaws.com跨集群可复用配置更省;⚠️两者都不是node IAM(Pod Identity正是为摆脱node IAM粗粒度而生);都=每Pod精细/临时/免密钥;对标GKE Workload Identity(K8s SA↔GCP SA)**。

### Q10. Security Group vs NACL(有状态/无状态、allow/deny、层级、规则顺序)
**伟伟答**：Security Group有状态,自动放行回来端口;NACL无状态。Security默认deny,NACL是allow。

**① 对照**：✅**"SG有状态自动放行回程;NACL无状态"完全对**(最重要区别,面试最常考);🔶"SG默认deny"对但要说全——**SG只能写allow(没写即隐式拒绝),根本不能写deny**;🔶**"NACL是allow"不准确——NACL既能allow也能deny(支持显式拒绝,与SG一大区别)**,默认NACL全通/自定义NACL全拒;🔶漏层级(SG=实例/ENI级,NACL=子网级)、NACL按规则号从小到大命中即停(SG无顺序全评估)。

**② 参考答案(AWS官方核实)**：
- 层级:SG=实例/ENI级(挂网卡);NACL=子网级(整subnet)。
- 状态:SG有状态(记出站连接,回程自动放行);NACL无状态(进出各自独立评估,响应要单独开临时端口1024-65535)。
- 规则:SG只能allow(没写=隐式拒绝),不能deny;NACL能allow也能deny(可封恶意IP)。
- 匹配:SG无顺序,所有规则一起评估,一条allow命中即放行;NACL按规则号从小到大命中第一条即停,末尾*默认拒绝。
- 默认:SG默认拒入站/允出站;默认NACL全通,自定义NACL全拒。
- **有状态vs无状态(最重要)**:SG开入站443,响应从443出去自动放行(记住连接);NACL不记连接,开入站443后响应出去还得单独在出站开临时端口(1024-65535)allow否则被挡(NACL最易踩坑)。
- **规则顺序(NACL特有)**:编号100/200/300从小到大逐条匹配,命中(allow或deny)即停;想"先deny坏IP再allow网段",deny号排前。SG无此概念。

**③ 概念**:纵深两层=NACL子网门口粗筛(无状态/可deny/整子网)+SG实例门口精筛(有状态/只allow/精确网卡);包进实例先过子网NACL再过实例SG,出去反之。口诀:SG=实例级/有状态/只allow/无顺序;NACL=子网级/无状态/可allow可deny/按号命中即停。伟伟答对最关键的有状态/无状态,要补:SG不能写deny、NACL能deny、层级、NACL按号命中即停。

**④ AWS↔GCP对照**:实例级有状态防火墙=AWS SG↔GCP VPC Firewall Rules(GCP防火墙本身有状态);子网级过滤=AWS NACL↔⚠️GCP无直接无状态子网ACL(用Firewall Rules带priority+网络标签/SA+Hierarchical firewall policy,GCP防火墙支持allow/deny靠priority排序);规则优先级=NACL规则号↔GCP priority(0-65535越小越优先)。⚠️GCP VPC Firewall默认有状态(像SG)+支持allow/deny+priority(像NACL),相当于合并简化了SG+NACL。

**⑤ 评分：6/10**。有状态/无状态答对(最重要),但"NACL是allow"漏了NACL也能deny(关键),SG没点出"不能写deny只有allow",漏层级和NACL规则顺序。记忆点:**SG=实例/ENI级+有状态(回程自动放行)+只能allow(不能deny)+规则无顺序全评估;NACL=子网级+无状态(进出独立,响应要单开临时端口1024-65535)+可allow可deny(封IP)+按规则号从小到大命中即停;默认NACL全通/自定义全拒;纵深=包先过子网NACL粗筛再过实例SG精筛;对照GCP VPC Firewall(默认有状态+支持allow/deny+priority,合并了SG+NACL)**。

---

**批次 5 小结**：Q9=6、Q10=6,均分6(比前几批好)。重点纠错→**①⚠️EKS Pod Identity不是走node IAM!它正是为摆脱node IAM"所有Pod共享粗粒度权限"而生,走eks-pod-identity-agent(DaemonSet)+EKS Auth API AssumeRoleForPodIdentity;IRSA走OIDC+AssumeRoleWithWebIdentity;都=每Pod免密钥精细临时权限,对标GKE Workload Identity ②SG=实例级/有状态/只allow(不能deny)/无顺序;⚠️NACL=子网级/无状态/可allow可deny/按规则号命中即停——伟伟漏了"NACL也能deny"和"SG不能写deny",有状态/无状态答对(核心)**。

---

## 批次 6：Q11–Q12（2026-09-05）

### Q11. VPC网络隔离与最小暴露(公有/私有子网+IGW/NAT+路由表让私有只出不进)
**伟伟答**：公有子网可互联网访问,私有子网互联网不能直接访问;私有子网通过IGW访问公网;NAT让子网访问公网;路由表不会设置。

**① 对照**：✅"公有可访问/私有不能直接访问"核心方向对;❌**核心错:"私有子网通过IGW访问公网"说反了——私有子网出公网走NAT Gateway不是IGW,恰恰"没有到IGW的路由"才使它成为私有**;🔶后句"NAT让子网访问公网"对但与前句矛盾(正解=私有→NAT→公网);🔶"路由表不会设置"=本题精髓,且公有/私有本质区别就在路由表(有无指向IGW的路由)。

**② 参考答案(AWS官方核实)**：
- **公有vs私有子网靠什么分**:⚠️子网无public/private开关属性,**唯一标准=关联的路由表里有没有`0.0.0.0/0→IGW`**。有=公有(带公网IP实例双向通网);无=私有(外部进不来,自己也不能直接出网)。
- **IGW vs NAT**:IGW=VPC与互联网双向大门(公有子网用);NAT Gateway=单向出口,让私有子网实例主动出网(下载更新/调API)但外部无法主动连入(NAT本身要放在公有子网,它需经IGW出网)。
- **路由表配置(核心)**:公有子网路由表`本地→local`+`0.0.0.0/0→IGW`;私有子网路由表`本地→local`+`0.0.0.0/0→NAT Gateway`(出网走NAT不是IGW!)。
- **"只出不进"原理**:私有子网无IGW路由→外部流量无路径进来(进不来);私有实例出网走NAT(NAT用自己公网IP做source NAT代理,响应沿已建连接回来=出得去);NAT单向(只允许内部发起+外部响应,外部无法用NAT主动连入)。
- **最小暴露三层**:公有子网只放ALB/NAT/堡垒机;私有子网放应用+数据库(无公网IP,出网靠NAT,入站靠ALB转发)。

**③ 概念**:"私有"本质=路由表无IGW路由。伟伟最大坑=把私有出公网归给IGW(实际私有子网碰不到IGW,只能靠NAT)。IGW双向(门)、NAT单向(阀门)。最小暴露=面向互联网组件压到最少。

**④ AWS↔GCP对照**:公网双向大门=IGW↔GCP default-internet-gateway路由+实例外部IP;私有单向出网=NAT Gateway↔**Cloud NAT**;"私有"判定=路由表无IGW路由↔实例无外部IP+靠Cloud NAT出网。核心一致:私有实例不给公网IP+只经NAT单向出网,外部无法主动进。

**⑤ 评分：4/10**。公有/私有基本概念对,但核心错=私有出公网说成IGW(实际NAT),路由表机制(精髓)没答。记忆点:**公有vs私有唯一区别=路由表有没有0.0.0.0/0→IGW;IGW=双向公网大门(公有用),NAT Gateway=单向出口(私有用,放在公有子网);私有子网路由表0.0.0.0/0→NAT,无IGW路由所以外部进不来(只出不进),NAT只允许内部发起+外部响应;最小暴露:公有只放ALB/NAT/堡垒机,业务DB放私有;对照GCP NAT Gateway↔Cloud NAT**。

### Q12. VPC Endpoint(Gateway vs Interface/PrivateLink) + S3不走公网 + 对照GCP
**伟伟答**：VPC endpoint是VPC链接其他访问的端点,是不是kubernetes的Service?gateway endpoint是路由表,interface endpoint是网卡,非VPC范围服务可用;S3通过gateway endpoint和EC2链接。

**① 对照**：✅**"Gateway endpoint是路由表"完全对**(靠路由表加指向endpoint的路由);✅**"Interface endpoint是网卡"完全对**(子网建带私有IP的ENI);✅"S3通过gateway endpoint"对(S3是Gateway典型);🔶**"是不是kubernetes的Service"不对**——K8s Service是集群内服务发现/负载均衡,VPC Endpoint是让VPC内流量私密(不走公网)访问AWS/第三方服务,别混;🔶"VPC链接其他访问端点"大意对但没点核心=流量不出VPC不经公网;🔶漏Gateway只支持S3/DynamoDB、Interface支持100+服务、收费差异、不走公网原理、GCP对照。

**② 参考答案(AWS官方核实)**：
- **VPC Endpoint**=让VPC内资源经AWS内部网络私密访问AWS/第三方服务,流量完全不经公网、不需IGW/NAT(提安全+省NAT流量费)。
- **两类对比**:Gateway Endpoint=**改路由表**(加指向endpoint的前缀列表路由)/**免费**/⚠️**只支持S3和DynamoDB两个**/仅本VPC内路由/不能被本地/跨VPC/TGW访问;Interface Endpoint(PrivateLink)=子网建**ENI(私有IP网卡)**/**收费**(endpoint小时+数据处理)/支持**100+服务**及第三方PrivateLink/配私有DNS原域名自动解析到私有IP/可被VPN/DX/peering/TGW访问。
- **S3不走公网**:方式一(推荐免费)=S3 Gateway Endpoint加进私有子网路由表→VPC内访问S3走私有路由不经NAT/IGW;方式二=S3 Interface Endpoint(收费,走ENI私有IP)用于从本地(DX/VPN)或跨VPC私密访问S3(Gateway做不到)。
- **不走公网原理**:Gateway=路由表把S3目标前缀指向endpoint,流量在AWS骨干网内到S3;Interface=服务域名私有DNS解析到VPC内ENI私有IP,连的是私网地址流量不出VPC。

**③ 概念**:两条分界=Gateway Endpoint(路由表+免费+只S3/DynamoDB+仅本VPC)vs Interface Endpoint/PrivateLink(ENI网卡+收费+100+服务+可跨本地/VPC/TGW)。伟伟机制都答对(路由表vs网卡),要补服务范围/收费/可否外部访问。别用K8s Service类比。

**④ AWS↔GCP对照**:私密访问托管服务(如对象存储)=S3/DynamoDB Gateway Endpoint↔**Private Google Access**(无外部IP的VM私密访问Google API/GCS);私密访问服务/第三方(走私有IP)=Interface Endpoint/PrivateLink↔**Private Service Connect(PSC)**;机制=Gateway路由表/Interface ENI私有IP↔PGA子网开关+私有DNS/PSC内部IP端点。

**⑤ 评分：6/10**。机制答得好(Gateway=路由表/Interface=网卡/S3走Gateway都对),但漏Gateway只支持S3/DynamoDB+免费、Interface 100+服务+收费+可跨本地,K8s Service类比不对。记忆点:**VPC Endpoint=让VPC内资源私密访问AWS/第三方服务(流量不出VPC不经公网,免IGW/NAT);Gateway Endpoint=改路由表+免费+只支持S3和DynamoDB+仅本VPC;Interface Endpoint(PrivateLink)=子网建ENI(私有IP)+收费+支持100+服务及第三方+可被本地/跨VPC/TGW访问;S3不走公网优先用免费S3 Gateway Endpoint(加路由表),跨本地用Interface;对照GCP Gateway↔Private Google Access,Interface/PrivateLink↔PSC;⚠️别和K8s Service混**。

---

**批次 6 小结**：Q11=4、Q12=6,均分5。重点纠错→**①⚠️私有子网出公网走NAT Gateway不是IGW!公有vs私有唯一区别=路由表有没有0.0.0.0/0→IGW;私有路由表0.0.0.0/0→NAT,无IGW路由所以只出不进;IGW双向/NAT单向;对照GCP Cloud NAT ②VPC Endpoint机制伟伟答对(Gateway=路由表/Interface=ENI网卡),要补:Gateway只支持S3/DynamoDB+免费+仅本VPC,Interface(PrivateLink)=ENI+收费+100+服务+可跨本地;对照GCP Private Google Access/PSC;别和K8s Service混**。

---

## 批次 7：Q13–Q14（2026-09-05）

### Q13. WAF + Shield(Standard/Advanced) + 对照Cloud Armor(别和Shielded VM混)
**伟伟答**：WAF是第七层,防SQL注入之类应用;Shield Standard是DDoS防御,advanced可提供人工服务。

**① 对照**：✅**"WAF是L7,防SQL注入"完全对**(应用层Web防火墙);✅"Shield Standard是DDoS防御"对;✅"advanced提供人工服务"对(=SRT响应团队);🔶漏Shield防哪层(L3/4,Advanced扩到L7);🔶漏Standard vs Advanced完整区别(免费vs收费$3000/月、L7检测、cost protection);🔶漏WAF/Shield分工、Cloud Armor对照、别和Shielded VM混。

**② 参考答案(AWS官方核实)**：
- **WAF**=应用层(L7/HTTP)Web防火墙,挂CloudFront/ALB/API GW前,检查每个HTTP请求内容,防SQL注入/XSS/恶意bot/爬虫/速率攻击(rate-based),有Managed Rules(OWASP)。
- **Shield=防DDoS**。**Standard**:免费+所有客户自动开+防L3/4常见DDoS(SYN flood/UDP reflection)。**Advanced**:付费(~$3000/月+数据费),加①L7 DDoS检测②**24/7 SRT(Shield Response Team)专家(=人工服务)**③**Cost Protection**(DDoS致扩容的额外账单可退)④与WAF深度集成+攻击可视化。
- **WAF vs Shield分工**:WAF防应用层内容攻击(看请求内容对不对);Shield防DDoS洪水(看流量是不是异常洪水);实战常一起挂。

**③ 概念**:按OSI层=Shield Standard防L3/4 DDoS,WAF防L7内容攻击,Shield Advanced横跨L3/4/7 DDoS+人工+费用保护。"人工服务"准确=SRT。免费vs付费是另一大区别。

**④ AWS↔GCP对照**:WAF+Shield↔**Cloud Armor**(GCP把WAF功能+DDoS防护合一,L7防SQLi/XSS+L3/4/7 DDoS);托管规则=WAF Managed Rules↔Cloud Armor预配置规则;高级DDoS+人工=Shield Advanced(SRT+cost protection)↔Cloud Armor Managed Protection Plus。⚠️**别和GCP Shielded VM混**:Shielded VM是VM启动/固件层安全(Secure Boot/vTPM/integrity monitoring,防rootkit/bootkit),与网络攻击/DDoS/Web防火墙无关;AWS对应VM启动层安全的是Nitro/NitroTPM/Secure Boot(Q27),不是AWS Shield——面试常设混淆陷阱。

**⑤ 评分：6/10**。WAF准+Shield方向对+答对Advanced人工服务;漏Shield层级(L3/4)、Standard/Advanced完整区别、WAF/Shield分工、GCP对照。记忆点:**WAF=L7 Web防火墙防SQLi/XSS/bot/速率(CloudFront/ALB前,Managed Rules);Shield防DDoS:Standard免费自动L3/4,Advanced付费$3000/月加L7检测+24/7 SRT人工+Cost Protection+WAF集成;分工=WAF防内容攻击/Shield防洪水;对照GCP Cloud Armor(WAF+DDoS合一);⚠️别和Shielded VM混(那是VM启动层安全=Secure Boot/vTPM,AWS对应Nitro/NitroTPM)**。

### Q14. KMS + key三种类型 + Envelope Encryption信封加密
**伟伟答**：KMS用来加密/解密key,可以托管,可以自己管理;envelope encryption不知道。

**① 对照**：✅"KMS加密/解密key"大方向对;✅"可托管/可自己管理"碰到key类型核心(AWS管的vs你自己管的)但没说全三种;🔶漏KMS关键特性:**主密钥永不离开KMS(HSM保护/不可导出),加解密在KMS内完成**;❌Envelope Encryption不会(本题核心+KMS能加密大数据的关键机制)。

**② 参考答案(AWS官方核实)**：
- **KMS**=托管密钥服务,创建/管理/使用加密密钥。⚠️核心=**KMS key(原CMK)主密钥永不离开KMS,由HSM保护、无法导出明文**,所有加解密把数据/密钥发进KMS内部完成;受IAM+key policy双控,CloudTrail审计。
- **三种key类型(控制权递减)**:①**Customer managed**=你自己创建管理,完全控制(轮换/key policy/启停/删除),收费,精细控制审计场景;②**AWS managed**=AWS为某服务自动创建(如aws/s3、aws/ebs),你不能改key policy,密钥免费只收调用费;③**AWS owned**=AWS完全拥有跨账号共享,你看不见管不了,免费。伟伟"可托管/可自管"对应前两类,补AWS owned即全。
- **Envelope Encryption(信封加密)—本题核心**:为何不直接用KMS加密大数据=主密钥不出KMS且单次操作限4KB、大数据来回传慢又贵。解法两层密钥:①向KMS要**Data Key**,KMS用主密钥生成返回两份(明文data key+被主密钥加密的data key密文);②用**明文data key在本地对称加密(AES)大数据**(快、不限大小);③加密后**丢弃明文data key**,只存"加密数据+加密的data key密文";④解密时把加密的data key发回KMS用主密钥解出明文data key再本地解数据。好处=大数据本地快速对称加密+主密钥始终不出KMS+绕过4KB限+每份数据可用不同data key(爆炸半径小)。S3 SSE-KMS/EBS加密底层都用它。

**③ 概念**:KMS安全根基=主密钥永不出KMS(HSM/不可导出,伟伟没点出)。信封加密=两层:主密钥(KMS内管小钥匙)+数据密钥(本地加密大数据);画面=数据锁进信封(data key),信封钥匙(data key)再锁进KMS保险箱(主密钥)。key类型控制权:customer>AWS managed>AWS owned。

**④ AWS↔GCP对照**:托管密钥=KMS↔Cloud KMS;key类型=customer managed/AWS managed/AWS owned↔CMEK/Google-managed default;信封加密原理完全一样=主密钥(GCP叫KEK)加密数据密钥(GCP叫DEK)两层;主密钥不出服务两边一致(GCP还有Cloud HSM/EKM更高等级)。

**⑤ 评分：4/10**。KMS方向对但没点"主密钥不出KMS"核心特性,三种key没说全,Envelope Encryption完全不会(本题核心)。记忆点:**KMS=托管密钥服务,主密钥永不离开KMS(HSM/不可导出)加解密在内部完成,IAM+key policy双控;三种key:customer managed(你全控收费)/AWS managed(AWS替你管某服务key可见不可改)/AWS owned(AWS自有看不见免费),控制权递减;Envelope Encryption=向KMS要Data Key(明文+主密钥加密的密文两份)→明文data key本地对称加密大数据(快不限大小)→丢明文只存加密数据+加密data key→解密发回KMS用主密钥解出;好处=大数据本地快加密+主密钥不出KMS+绕4KB限;对照GCP KMS↔Cloud KMS,主密钥=KEK/数据密钥=DEK**。

---

**批次 7 小结**：Q13=6、Q14=4,均分5。重点纠错→**①WAF=L7防SQLi/XSS,Shield防DDoS(Standard免费L3/4,Advanced付费$3000/月+L7+24/7 SRT人工+Cost Protection);对照Cloud Armor(WAF+DDoS合一);⚠️别和Shielded VM混(VM启动层安全,AWS对应Nitro/NitroTPM) ②⚠️KMS主密钥永不出KMS(HSM不可导出);三种key=customer managed(全控收费)/AWS managed(可见不可改)/AWS owned(看不见免费);Envelope Encryption信封加密=两层密钥,向KMS要data key(明文+密文),明文data key本地加密大数据后丢弃只存密文data key,解密时发回KMS解出——绕过4KB限+主密钥不出KMS**。
