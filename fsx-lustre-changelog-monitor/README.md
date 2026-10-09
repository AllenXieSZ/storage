# 用 Lustre Changelog 监控 FSx for Lustre 文件变化（实测）

Lustre 的 Changelog 是元数据服务器（MDT）上的变更日志，记录创建、删除、重命名、改属性等操作。
在 FSx for Lustre 客户端上可以用 `lfs changelog` 读取。

> ⚠️ FSx for Lustre 官方文档**没有** Changelog 相关说明，以下全部为实测结果，不是 AWS 支持的功能，行为可能随服务更新变化。

## 1. 测试环境

| 项目 | 配置 |
|---|---|
| 区域 | us-east-2 |
| 文件系统 | PERSISTENT_2，1200 GiB，Lustre 2.15 |
| 客户端 | AL2023，lustre-client 2.15.6，root |
| 对比 | 4 个文件系统：双向 DRA / 仅自动导出 DRA / 仅自动导入 DRA / 无 DRA |

## 2. 结论

| 文件系统类型 | 有无 Changelog 记录 |
|---|---|
| 双向 DRA（自动导入 + 自动导出） | ✅ 有 |
| 仅自动导出 DRA | ✅ 有 |
| 仅自动导入 DRA | ❌ 无 |
| 无 DRA | ❌ 无 |

**只有配置了自动导出的文件系统才有 Changelog 记录**，并且整个文件系统的变更都会记录（不限 DRA 路径）。

## 3. 使用步骤

### 步骤 1：找到 MDT 名称
```bash
lfs mdts /mnt/lustre
# 0: divrbb4v-MDT0000_UUID ACTIVE    → MDT 名称为 divrbb4v-MDT0000
```
（多 MDT 的文件系统每个 MDT 都要单独读取）

### 步骤 2：持续读取（必须用 --follow）
```bash
lfs changelog --follow divrbb4v-MDT0000 >> /var/log/lustre-changelog.log
```
- 必须以 **root** 运行，普通用户报 `Permission denied`
- **必须持续运行**：记录在几秒内就会被清掉（见限制 2），事后用 `lfs changelog <MDT>` 查询基本是空的

### 步骤 3：（可选）把 FID 转成路径
```bash
lfs fid2path /mnt/lustre '[0x200000403:0x1c:0x0]'
# /mnt/lustre/cl3/keep.txt
```
文件被删除后 FID 无法再解析，但删除记录本身已带路径（见下文）。

### 步骤 4：做成常驻服务（示例）
```ini
# /etc/systemd/system/lustre-changelog.service
[Unit]
After=network-online.target remote-fs.target
[Service]
ExecStart=/bin/sh -c 'exec /usr/bin/lfs changelog --follow divrbb4v-MDT0000 >> /var/log/lustre-changelog.log'
Restart=always
[Install]
WantedBy=multi-user.target
```
再用 CloudWatch Agent 把 `/var/log/lustre-changelog.log` 送到 CloudWatch Logs。

## 4. 记录内容

### 实测样例（一组操作逐条对应）

| 操作 | Changelog 记录 |
|---|---|
| `mkdir cl8` | `12955 02MKDIR 05:55:15.024429670 2026.10.09 0x0 t=[0x200000403:0x1928:0x0] ef=0xf u=0:0 nid=172.31.39.207@tcp p=[0x200000007:0x1:0x0] cl8` |
| `echo a > a.txt` | `12957 01CREAT 05:55:18.028357979 2026.10.09 0x0 t=[0x200000403:0x1929:0x0] ef=0xf u=0:0 nid=172.31.39.207@tcp p=[0x200000403:0x1928:0x0] a.txt` |
| `echo more >> a.txt` | `12958 12LYOUT ... t=[0x200000403:0x1929:0x0] ef=0xf u=0:0 nid=0@<0:0> ...` |
| `truncate -s 1 a.txt` | `12959 13TRUNC ... t=[0x200000403:0x1929:0x0] ...` |
| `chmod` / `chown` / `touch` | `12960 14SATTR ...` 、`12961 14SATTR ...`（3 个操作只产生 2 条） |
| `ln -s a.txt lnk` | `12962 04SLINK ... lnk` |
| `ln a.txt hard` | `12963 03HLINK ... hard` |
| `mv a.txt b.txt` | `12964 08RENME ... p=[...] b.txt s=[0x200000403:0x1929:0x0] sp=[...] /cl8/a.txt` |
| `cat b.txt` | **无记录** |
| `rm lnk` / `rm hard` / `rm b.txt` | `06UNLNK ... /cl8/lnk`、`06UNLNK ... /cl8/hard`、`06UNLNK ... /cl8/b.txt` |
| `rmdir cl8` | `12968 07RMDIR ... /cl8` |
| 普通用户 ec2-user 删除 | `4148 06UNLNK 05:51:36.321249230 2026.10.09 0x1 t=[...] ef=0xf u=1000:1000 nid=172.31.39.207@tcp p=[...] /cl5/user_slow.txt` |

### 字段说明

| 字段 | 示例 | 含义 |
|---|---|---|
| 序号 | `12967` | 记录编号，递增 |
| 类型 | `06UNLNK` | 操作类型（见下表） |
| 时间 | `05:55:21.970213014 2026.10.09` | UTC，纳秒精度 |
| 标志 | `0x1` | UNLNK 中 `0x1` = 最后一个链接被删（文件真正删除）；`0x0` = 只删了一个硬链接 |
| `t=` | `[0x200000403:0x1929:0x0]` | 目标文件 FID |
| `u=` | `1000:1000` | **操作者 uid:gid** |
| `nid=` | `172.31.39.207@tcp` | **发起操作的客户端 IP** |
| `p=` | `[0x200000403:0x1928:0x0]` | 父目录 FID |
| 名称 / 路径 | `a.txt` 或 `/cl8/b.txt` | CREAT/MKDIR 只有文件名；**UNLNK/RMDIR/RENME 带从文件系统根开始的完整路径** |
| `s=` `sp=` | — | RENME 的源文件 FID 和源父目录 FID |

### 实测出现的类型

| 类型 | 操作 |
|---|---|
| `01CREAT` | 创建文件 |
| `02MKDIR` | 创建目录 |
| `03HLINK` | 创建硬链接 |
| `04SLINK` | 创建软链接 |
| `06UNLNK` | 删除文件 / 链接 |
| `07RMDIR` | 删除目录 |
| `08RENME` | 重命名 / 移动 |
| `12LYOUT` | 文件布局变化（首次写入数据时出现） |
| `13TRUNC` | 截断 |
| `14SATTR` | 改权限 / 属主 / 时间 |

## 5. 性能与完整性测试

| 测试 | 操作数 | 记录数 | 丢失 |
|---|---|---|---|
| 慢速创建+删除 | 200 + 200 | 200 CREAT + 200 UNLNK | 0 |
| 快速创建+删除 | 200 + 200 | 200 + 200 | 0 |
| 批量创建 1000 → `rm -rf` | 1000 + 1000 | 1000 + 1000 | 0 |
| 批量创建 3000 → `rm -rf` | 3000 + 3000 | 3000 + 3000 | 0 |
| 批量创建 2000 → `rm -rf`（首次测试） | 2000 + 2000 | 949 CREAT + 1149 UNLNK | **有丢失**（序号中断 1915 条） |

同一个文件系统、类似操作，其中一次出现丢失，原因未确认（推测为读取跟不上、记录已被清除）。**不能保证 100% 不漏**。

## 6. 限制

1. **非官方支持**：FSx for Lustre 文档未提及 Changelog，属于底层 Lustre 能力，行为可能变化。
2. **记录保留时间极短**：写入后几秒内即被清除（实测 5 秒后 `lfs changelog` 已为空），只能用 `--follow` 实时读取；读取程序停止期间的变更**会丢失，无法补回**。
3. **只有开了自动导出 DRA 的文件系统才有记录**；无 DRA 或仅自动导入的文件系统没有任何记录。
4. **无法自行注册 / 配置**：客户端不能执行 `changelog_register`，也不能修改记录哪些类型（mask）。
5. **需要 root 权限**读取。
6. **不记录读取**：`cat` / 打开文件不产生记录。
7. **不记录每次数据写入**：只有首次写入时的 `LYOUT`、截断时的 `TRUNC`，追加写入/覆盖内容没有对应记录。
8. **属性修改不是一一对应**：chmod / chown / touch 3 个操作只得到 2 条 `SATTR`。
9. **可能丢记录**：批量操作测试中出现过一次丢失（见第 5 节）。
10. **CREAT 只有文件名没有完整路径**，需要用父目录 FID 通过 `lfs fid2path` 解析（父目录被删后无法解析）。
11. **每个 MDT 单独读取**，多 MDT 文件系统需要每个 MDT 一个读取进程。
12. **建议只在一个客户端上运行读取程序**，避免重复记录。

## 7. 与 S3 EventBridge 方案对比

| 对比项 | Changelog | S3 EventBridge |
|---|---|---|
| 覆盖范围 | 整个文件系统 | 仅 DRA 路径 |
| 是谁操作的（uid、客户端 IP） | ✅ 有 | ❌ 无 |
| 延迟 | 实时（毫秒级） | 约 5–10 秒 |
| 官方支持 | ❌ 无文档 | ✅ 有 |
| 可靠性 | 读取程序停止会丢；实测出现过丢失 | 至少一次投递 |
| 部署 | 需要常驻进程（root） | 无需部署客户端 |
| 前提 | 文件系统开了自动导出 | 有 DRA + 自动导出 |

定时导出到 S3 + Athena 查询见：[EXPORT_TO_S3.md](EXPORT_TO_S3.md)

S3 方案见：[fsx-lustre-dra-eventbridge](../fsx-lustre-dra-eventbridge/README.md)
