# 敏感信息提交防护 (pre-commit hook)

`scripts/pre-commit` 是一个 git pre-commit 钩子，在每次 `git commit` 前扫描**本次暂存的新增内容**，拦截疑似敏感信息，防止泄露到 GitHub。

## 拦截规则

| 类型 | 模式 |
|---|---|
| AWS Access Key ID | `AKIA` + 16 位大写字母数字 |
| AWS Secret Access Key | `aws_secret_access_key`/`SecretAccessKey` 后跟 40 位真实值 |
| 阿里云 AccessKey | `LTAI` + 12-20 位 |
| AWS 账号 ID | ARN 中的 12 位账号号，或 `account_id`/`owner_id` 字段 |
| 真实测试密码 | `#2026` / `FsxOntap#` / `OpenCart#2026` / `AuroraBk#` / `Admin#2026`（非 REDACTED） |
| 私钥 | `BEGIN ... PRIVATE KEY` |
| GitHub / Slack token | `ghp_...` / `xox...` |

## 安装（二选一）

**方式 A（推荐，跟仓库走）：**
```bash
git config core.hooksPath scripts
```
让 git 直接用 `scripts/` 目录下的 `pre-commit`。克隆仓库后每人执行一次。

**方式 B（拷到本地 hooks）：**
```bash
cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## 使用

- 正常 `git commit`，若命中敏感模式会**拦截并列出文件与类型**，退出码非 0。
- 把敏感值替换为占位符（`REDACTED` / `<PASSWORD>` / `<ACCOUNT_ID>`）后再提交。
- 确认是误报时可绕过：`git commit --no-verify`。

## 说明

- 只扫**新增/修改的行**（`git diff --cached`），不扫历史，性能好。
- 规则偏保守，宁可误报也不漏报；误报用 `--no-verify` 放行。
- 已在 2026-08-21 全仓扫描确认当前仓库无真实泄露。
