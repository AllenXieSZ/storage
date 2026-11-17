# FSx for Lustre Project Quota：新建 2.15 支持，升级到 2.15 不支持（实测）

测试时间：2026-11-17，us-east-2，FSx for Lustre Persistent 1（SSD 50 MB/s/TiB，1200 GiB），客户端 AL2023 + `lustre-client 2.15.6`。

## ⭐ 关键结论（全部已实测）

| 文件系统来源 | 服务端版本 | `lfs project -sp` | `lfs setquota -p` | `lfs quota -p` | limit 是否生效 |
|---|---|---|---|---|---|
| **新建时指定 2.15** | 2.15.8.0 | ✅ | ✅ | ✅ | ✅ **生效** |
| **2.12 创建 → 升级到 2.15** | 2.15.8.0 | ❌ Operation not supported | ❌ rc=95 | ❌ rc=95 | ❌ **不生效** |
| **2.10 创建 → 升级到 2.15** | 2.15.8.0 | ❌ Operation not supported | ❌ rc=95 | ❌ rc=95 | ❌ **不生效** |
| 升级后的 FS → backup → restore 成新 FS（2.15） | 2.15.8.0 | ❌ | ❌ rc=95 | ❌ rc=95 | ❌ 不生效 |
| 2.12 服务端（未升级） | 2.12.9.0 | ⚠️ rc=0 但 projid 仍为 0（**假成功**） | ❌ rc=95 | ❌ rc=95 | ❌ |
| 新建 2.15 + **2.12.8 客户端** | 2.15.8.0 | ✅ | ✅ | ✅ | ✅ 生效（客户端 2.12 不是原因） |

- **升级上来的 FS，`describe-file-systems` 显示 `FileSystemTypeVersion=2.15`、服务端 `target_version: 2.15.8.0`，客户端完全看不出区别**（MDC connect_flags 与新建 2.15 完全一致），但 project quota 不可用。
- **user / group quota 在升级上来的 FS 上正常**，只有 project quota 不可用。
- **客户端无法修复**：umount/remount、`lustre_rmmod` 重载模块、换客户端版本、升级后等 20 分钟、再执行一次 `update-file-system`（no-op）、backup→restore，全部无效。
- **唯一已实测可行的方案：新建一个创建时就指定 `--file-system-type-version 2.15` 的 FS，再迁移数据。**
- FSx 文档（[Storage quotas](https://docs.aws.amazon.com/fsx/latest/LustreGuide/lustre-quotas.html)）只写了 *"Project quotas are only supported on Lustre version 2.15"*，**没有说明升级到 2.15 的 FS 不支持**（2026-11-17 查阅）。

## 1. 升级上来的 FS 报错原文（2.12 → 2.15，客户端 2.15.6）

```
client: 2.15.6
server:        target_version: 2.15.8.0
$ lfs project -sp 29017 /mnt/fsx/proj29017
lfs: failed to set xattr for '/mnt/fsx/proj29017': Operation not supported
rc=1
$ lfs project -d /mnt/fsx/proj29017
    0 - /mnt/fsx/proj29017
rc=0
$ lfs setquota -p 29017 -B 1G /mnt/fsx
setquota failed: Operation not supported
rc=95
$ lfs quota -p 29017 /mnt/fsx
Unexpected quotactl error: Operation not supported
Disk quotas for prj 29017 (pid 29017):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx     [0]     [0]     [0]       -     [0]     [0]     [0]       -
Some errors happened when getting quota info. Some devices may be not working or deactivated. The data in "[]" is inaccurate.
rc=95
$ lfs quota -u quser /mnt/fsx
uid 2001 is using default file quota setting
rc=0
--- dmesg
Lustre: Unmounted <MOUNT_NAME>-client
Lustre: Mounted <MOUNT_NAME>-client
LustreError: (osc_quota.c:309:osc_quotactl()) ptlrpc_queue_wait failed, rc: -95
LustreError: (mdc_request.c:2111:mdc_quotactl()) <MOUNT_NAME>-MDT0000-mdc-<id>: ptlrpc_queue_wait failed: rc = -95
LustreError: (lmv_obd.c:4049:lmv_quotactl()) getquota on mdt 0 failed. -95
```

> 普通用户写 1.5 GiB（project 硬限 1 GiB）**全部写入成功**，limit 没有生效。

### 升级前（服务端 2.12.9.0）对照
```
client: 2.15.6
server:        target_version: 2.12.9.0
$ lfs project -sp 29017 /mnt/fsx/proj29017
rc=0
$ lfs project -d /mnt/fsx/proj29017
    0 - /mnt/fsx/proj29017
rc=0
$ lfs setquota -p 29017 -B 1G /mnt/fsx
setquota failed: Operation not supported
rc=95
$ lfs quota -p 29017 /mnt/fsx
Unexpected quotactl error: Operation not supported
Disk quotas for prj 29017 (pid 29017):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx     [0]     [0]     [0]       -     [0]     [0]     [0]       -
Some errors happened when getting quota info. Some devices may be not working or deactivated. The data in "[]" is inaccurate.
rc=95
$ lfs quota -u quser /mnt/fsx
```
注意：2.12 上 `lfs project -sp` **返回 rc=0，但 `lfs project -d` 显示 projid 仍是 0**，容易误以为设置成功。

### 用 backup restore 出的新 FS（2.15）——仍然报错
```
server:        target_version: 2.15.8.0
$ lfs project -sp 29017
lfs: failed to set xattr for '/mnt/fsx/proj29017_r': Operation not supported
rc=1
    0 - /mnt/fsx/proj29017_r
$ lfs setquota -p 29017 -B 1G
setquota failed: Operation not supported
rc=95
$ lfs quota -p 29017
Unexpected quotactl error: Operation not supported
Disk quotas for prj 29017 (pid 29017):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx     [0]     [0]     [0]       -     [0]     [0]     [0]       -
Some errors happened when getting quota info. Some devices may be not working or deactivated. The data in "[]" is inaccurate.
rc=95
--- 已有（升级前）目录 proj29017 打 projid
lfs: failed to set xattr for '/mnt/fsx/proj29017': Operation not supported
```

## 2. 根因（Lustre 官方手册 + 源码 + 实测）

**MDT/OST 的 ldiskfs 磁盘没有开启 `PROJECT` feature。版本升级只替换 Lustre 软件，不会自动开启这个磁盘特性。**

### 2.1 Lustre 官方手册（[lustre-manual](https://github.com/lustre/lustre-manual) `ConfiguringQuotas.xml` / `UpgradingLustre.xml`）
- *"For ldiskfs backends, mkfs.lustre now creates empty quota files and enables the QUOTA feature flag in the superblock ... **The project quota feature is disabled by default, and tune2fs needs to be run to enable every target manually.**"*
- *"Lustre filesystems formatted with a Lustre release prior to 2.10 ... will not have project quota usage reporting functional until 2.15.0 or **`tune2fs -O project` is run against all ldiskfs backend targets**. This command sets the PROJECT feature flag in the superblock and runs e2fsck (**as a result, the target must be offline**)."*
- 升级章节：*"to enable the project quota feature enter the following on every ldiskfs backend target while unmounted: `tune2fs -O project /dev/dev`"*，enforcement 在 MGS 上通过 `lctl set_param -P osd-*.<fs>*.quota_slave*.enabled=ugp` 开启。

### 2.2 Lustre 源码（[lustre-release](https://github.com/lustre/lustre-release) master）：三条报错同一根因
| 命令 | 服务端代码 | 触发条件 |
|---|---|---|
| `lfs project -sp` | `lustre/osd-ldiskfs/osd_handler.c` `osd_transfer_project()`：`if (!ldiskfs_has_feature_project(sb)) { ... if (projid != LDISKFS_DEF_PROJID) return -EOPNOTSUPP; }` | ldiskfs 无 PROJECT feature 且 projid≠0 |
| `lfs setquota -p` / `lfs quota -p` | `lustre/osd-ldiskfs/osd_quota.c`：`case PRJQUOTA: if (ldiskfs_has_feature_project(sb)) ... else RETURN(-ENOENT)` → `lustre/quota/lquota_lib.c` `acct_obj_lookup()` 失败 → `RETURN(-EOPNOTSUPP)` | 同上，project accounting 对象不存在 |

### 2.3 客户端实测佐证
```
--- lfs project -p 29017 (no -s) on file
lfs: failed to set xattr for '/mnt/fsx/p2/f': Operation not supported
rc=1
--- lfs project -s (inherit flag only, projid 0)
rc=0
    0 P /mnt/fsx/p2
--- strace errno of lfs project
ioctl(3, FS_IOC_FSGETXATTR, {fsx_xflags=FS_XFLAG_PROJINHERIT, fsx_extsize=32695, fsx_nextents=1416958012, fsx_projid=0, fsx_cowextsize=1131230656}) = 0
ioctl(3, FS_IOC_FSSETXATTR, {fsx_xflags=FS_XFLAG_PROJINHERIT, fsx_extsize=32695, fsx_projid=0x7159, fsx_cowextsize=1131230656}) = -1 EOPNOTSUPP (Operation not supported)
```
- `ioctl(FS_IOC_FSSETXATTR, projid=0x7159)` 返回 **EOPNOTSUPP**；
- 只设继承标志、projid=0 的 `lfs project -s` **成功**（`0 P`）——与源码 `if (projid != LDISKFS_DEF_PROJID) return -EOPNOTSUPP` 精确对应；
- user/group quota 正常 → QUOTA feature 存在，只缺 PROJECT feature。

> 推测（未实测）：FSx 的版本升级流程未对 MDT/OST 执行 `tune2fs -O project`；FSx 新建 2.15 时 mkfs 已带 PROJECT feature（由新建 2.15 project quota 可用反推，FSx 内部参数未公开）。`tune2fs` 需要服务端块设备 root 权限且目标离线，客户无法执行。

## 3. 遇到 rc=95 时的排查顺序

```bash
id -u                                                        # 非 root 报 "Operation not permitted"（EPERM），不是 rc=95
stat -f -c %T <dir>                                          # 必须是 lustre；tmpfs/ext4 上 lfs project 也会报 "Operation not supported"
lctl get_param -n mdc.*.import | grep target_version         # 服务端实际版本
aws fsx describe-file-systems --file-system-ids <FS_ID> \
  --query 'FileSystems[0].[FileSystemTypeVersion,CreationTime,AdministrativeActions[?AdministrativeActionType==`FILE_SYSTEM_UPDATE`]]'
dmesg | grep -E "quotactl|rc = -95|rc: -95"
```

| 现象 | 判断 |
|---|---|
| 三条都报 `Operation not supported`，服务端 2.15，**有过 FILE_SYSTEM_UPDATE 升级记录** | 升级上来的 FS，磁盘缺 PROJECT feature → 新建 2.15 FS 迁移，或开 AWS Support case |
| `lfs project` rc=0 但 projid 仍为 0，setquota/quota rc=95 | 服务端还是 2.10/2.12 |
| `Operation not permitted` | 没用 root |
| `lfs project` not supported，setquota/quota `No such device (rc=19)` | 路径不在 Lustre 上 |

## 4. 升级 Lustre 版本的坑（已实测）
- **只 umount 不够**：umount 后 LNet（TCP 988）连接仍在，`update-file-system` 约 10 分钟后失败：
  *"Amazon FSx is unable to update the Lustre version of your file system because clients are currently connected to the file system."*
  所有客户端执行 `lustre_rmmod` 后重试成功（2.10→2.15 约 11.5 分钟，2.12→2.15 约 15 分钟）。
- 2.15.6 客户端无法挂载 2.10 服务端：*"Server MGS version (2.10.5.0) refused connection from this client with an incompatible version (2.15.6)"*。
- **想用 project quota，就不要走"建 2.10/2.12 再升级"这条路，创建时直接指定 2.15**（P1 CLI 默认是 2.10）。

---

# 附：新建 2.15 FS 的 project quota 完整实测（支持且生效）


测试时间：2026-11-17（us-east-2）。结论：**可以设置，且 limit 生效**（block 硬限、inode 硬限、soft limit + grace 均实测生效）。

## A0. 结论速览（全部已实测）

| 测试项 | 结果 |
|---|---|
| P1 创建时指定 2.15 | ✅ `FileSystemTypeVersion=2.15`，服务端 `target_version: 2.15.8.0` |
| 客户端 2.15 | ✅ AL2023 `lustre-client-2.15.6`，`lfs 2.15.6` |
| `lfs project -p 100 -r -s <dir>` 绑定目录 | ✅ rc=0，目录显示 `100 P`（P=继承标志） |
| `lfs setquota -p 100 ...` | ✅ rc=0，`lfs quota -p 100` 显示设置值 |
| 新建子目录/文件自动继承 projid | ✅ 子目录 `100 P`，文件 `100 -` |
| **block 硬限制 100 MiB** | ✅ 普通用户写 150 MiB，写到 99 MiB 报 `Disk quota exceeded`，dd exit=1 |
| **inode 硬限制 2000** | ✅ 第 1996 个文件 `touch` 报 `Disk quota exceeded`（目录内已有 4 个 inode，合计 1999） |
| **soft limit + grace** | ✅ grace=60s：超软限未超硬限时可继续写；grace 过期后（显示 `none`）再写被拒 |
| 对照：不属于 project 的目录 | ✅ 同一用户写 150 MiB 成功，不受限 |
| root 用户 | ⚠️ 不受限（写 120 MiB 超过硬限成功），但**用量计入 project**，计入后普通用户写入被拒 |
| mv 非 project 文件进 project 目录 | ⚠️ 文件 projid 自动变为 100，用量**约 10 秒后**才计入 |
| 删除文件后 | ✅ 用量下降，恢复可写（统计有数十秒延迟） |
| umount/remount 后 | ✅ 配额、grace 设置、目录 projid 均保留（存在服务端） |

## A1. 环境

| 项 | 值 |
|---|---|
| 文件系统 | PERSISTENT_1，SSD，50 MB/s/TiB，1200 GiB，Lustre 2.15（创建约 7.5 分钟） |
| 服务端版本 | MDT/OST `target_version: 2.15.8.0` |
| 客户端 | m6i.large，Amazon Linux 2023，kernel 6.18.62，`lustre-client-2.15.6-35.amzn2023` |
| 挂载 | `mount -t lustre -o relatime,flock <FS_DNS>@tcp:/<MOUNT_NAME> /mnt/fsx` |
| 测试用户 | `quser`（uid 2001，非 root）——FSx 文档：root 写入不受配额限制 |

### 创建命令
```bash
aws fsx create-file-system --region us-east-2 --file-system-type LUSTRE \
  --file-system-type-version 2.15 --storage-type SSD --storage-capacity 1200 \
  --subnet-ids <SUBNET> --security-group-ids <SG> \
  --lustre-configuration DeploymentType=PERSISTENT_1,PerUnitStorageThroughput=50
```
客户端：`sudo dnf install -y lustre-client`（AL2023 默认 2.15.6）

## A2. 配额设置命令
```bash
# 绑定目录到 project 100（-r 递归，-s 设置继承标志）
lfs project -p 100 -r -s /mnt/fsx/proj100
lfs project -d /mnt/fsx/proj100            # 查看: "100 P /mnt/fsx/proj100"
# block 软 50 MiB / 硬 100 MiB，inode 软 1024 / 硬 2000
lfs setquota -p 100 -b 51200 -B 102400 -i 1024 -I 2000 /mnt/fsx
lfs quota -p 100 /mnt/fsx
# grace 改为 60 秒（默认 1 周）
lfs setquota -t -p -b 60 -i 60 /mnt/fsx
```
注：`-i 1024` 时 lfs 给出 warning `inode softlimit '1024' smaller than minimum qunit size`，但设置成功且生效。

## A3. 原始输出

### A3.1 挂载与环境（c1）
```
[SSM status=Success]
+ mkdir -p /mnt/fsx
+ mount -t lustre -o relatime,flock <FS_DNS>@tcp:/<MOUNT_NAME> /mnt/fsx
+ mount
+ grep lustre
<IP>@tcp:/<MOUNT_NAME> on /mnt/fsx type lustre (rw,relatime,seclabel,checksum,flock,nouser_xattr,lruresize,lazystatfs,nouser_fid2path,verbose,encrypt)
+ lctl get_param version
version=2.15.6
+ grep -m1 target_version
+ lctl get_param -n 'osc.*.import'
       target_version: 2.15.8.0
+ grep -m1 target_version
+ lctl get_param -n 'mdc.*.import'
       target_version: 2.15.8.0
+ lfs df -h /mnt/fsx
UUID                       bytes        Used   Available Use% Mounted on
<MOUNT_NAME>-MDT0000_UUID       32.7G        8.8M       32.7G   1% /mnt/fsx[MDT:0]
<MOUNT_NAME>-OST0000_UUID        1.1T        7.8M        1.1T   1% /mnt/fsx[OST:0]

filesystem_summary:         1.1T        7.8M        1.1T   1% /mnt/fsx

+ lfs df -i /mnt/fsx
UUID                      Inodes       IUsed       IFree IUse% Mounted on
<MOUNT_NAME>-MDT0000_UUID     6072479         374     6072105   1% /mnt/fsx[MDT:0]
<MOUNT_NAME>-OST0000_UUID   215071365         358   215071007   1% /mnt/fsx[OST:0]

filesystem_summary:      6072479         374     6072105   1% /mnt/fsx

+ lfs quota -u root /mnt/fsx
Disk quotas for usr root (uid 0):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   16641       0       0       -     369       0       0       -
+ lfs quota -p 100 /mnt/fsx
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx       0       0       0       -       0       0       0       -
pid 100 is using default block quota setting
pid 100 is using default file quota setting

```

### A3.2 设置配额 + block 硬限制 + 对照（c2）
```
[SSM status=Success]
### 2.1 创建目录、绑定 project 100（继承标志 -s，递归 -r）
rc=0
  100 P /mnt/fsx/proj100
### 2.2 设置 project 100 配额：block 软 50MiB / 硬 100MiB，inode 软 1024 / 硬 2000
lfs setquota: warning: inode softlimit '1024' smaller than minimum qunit size
See 'lfs help setquota' or Lustre manual for details
rc=0
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx       0   51200  102400       -       0    1024    2000       -
       /mnt/fsx       0   51200  102400       -       0    1024    2000       -
<MOUNT_NAME>-MDT0000_UUID
                      0       -       0       -       0       -       0       -
<MOUNT_NAME>-OST0000_UUID
                      0       -       0       -       -       -       -       -
Total allocated inode limit: 0, total allocated block limit: 0
### 2.3 子目录/新文件是否继承 projid
  100 P /mnt/fsx/proj100/sub
  100 - /mnt/fsx/proj100/sub/a
  100 - /mnt/fsx/proj100/b
### 2.4 block 硬限制：quser 写 150MiB（硬 100MiB），预期 Disk quota exceeded
100+0 records in
99+0 records out
103809024 bytes (104 MB, 99 MiB) copied, 1.30458 s, 79.6 MB/s
-rw-r--r--. 1 quser quser 103809024 Nov 17 01:46 /mnt/fsx/proj100/big
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx  101475*  51200  102400 6d23h59m55s       5    1024    2000       -
### 2.5 超限后再写 1 个小文件
0+0 records out
0 bytes copied, 0.0231888 s, 0.0 kB/s
### 2.6 对照：同 FS 上不属于 project 的目录，quser 写 150MiB，预期成功
    0 - /mnt/fsx/noproj
157286400 bytes (157 MB, 150 MiB) copied, 0.277922 s, 566 MB/s
### 2.7 对照：root 在 project 目录写 50MiB（文档说 root 不受限）
52428800 bytes (52 MB, 50 MiB) copied, 0.107295 s, 489 MB/s
  100 - /mnt/fsx/proj100/rootfile
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx  101476*  51200  102400 6d23h59m54s       5    1024    2000       -
### 2.8 删文件后恢复写入
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   51283*  51200  102400 6d23h59m44s       4    1024    2000       -
20971520 bytes (21 MB, 20 MiB) copied, 0.272597 s, 76.9 MB/s


```

### A3.3 报错原文 + inode 硬限 + soft/grace + mv（c3）
```
[SSM status=Success]
### 0 当前目录内容 + 等 30s 后 usage（检查删除后的统计）
total 59
drwxrwxrwx. 3 quser quser 25600 Nov 17 01:46 .
drwxr-xr-x. 6 root  root  33280 Nov 17 01:46 ..
-rw-r--r--. 1 quser quser     0 Nov 17 01:46 b
drwxr-xr-x. 2 quser quser  1024 Nov 17 01:46 sub
51	/mnt/fsx/proj100
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
### 1 block 硬限制报错原文（quser 写 150MiB）
dd: error writing '/mnt/fsx/proj100/big2': Disk quota exceeded
100+0 records in
99+0 records out
103809024 bytes (104 MB, 99 MiB) copied, 1.31906 s, 78.7 MB/s
exit=1
-rw-r--r--. 1 quser quser 103809024 Nov 17 01:47 /mnt/fsx/proj100/big2
small write exit=0
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
### 2 inode 硬限制：quser 在 project 目录建 2500 个文件（硬 2000）
failed at #1996: touch: cannot touch '/mnt/fsx/proj100/many/f1996': Disk quota exceeded
created=1995
1995
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   17288   51200  102400       -    1999*   1024    2000 6d23h59m57s
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
### 3 soft limit + grace：block grace 改成 60s
Block grace time: 1m; Inode grace time: 1m
lfs setquota: warning: inode softlimit '1024' smaller than minimum qunit size
See 'lfs help setquota' or Lustre manual for details
73400320 bytes (73 MB, 70 MiB) copied, 0.881711 s, 83.2 MB/s
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   68691*  51200  102400      1m       4    1024    2000       -
-- 在 grace 内（超软限未超硬限）继续写 10MiB
10485760 bytes (10 MB, 10 MiB) copied, 0.149038 s, 70.4 MB/s
-- 等 90s 让 grace 过期后再写 10MiB（预期被拒）
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   82036*  51200  102400    none       6    1024    2000       -
dd: error writing '/mnt/fsx/proj100/soft3': Disk quota exceeded
4+0 records in
3+0 records out
3145728 bytes (3.1 MB, 3.0 MiB) copied, 0.0443038 s, 71.0 MB/s
total 85067
-rw-r--r--. 1 quser quser        0 Nov 17 01:46 b
-rw-r--r--. 1 quser quser 73400320 Nov 17 01:48 soft1
-rw-r--r--. 1 quser quser 10485760 Nov 17 01:48 soft2
-rw-r--r--. 1 quser quser  3145728 Nov 17 01:49 soft3
drwxr-xr-x. 2 quser quser    25600 Nov 17 01:46 sub
### 4 把已有的非 project 文件 mv 进来是否计入（rename 同 FS）
31457280 bytes (31 MB, 30 MiB) copied, 0.0668827 s, 470 MB/s
    0 - /mnt/fsx/noproj/m1
mv exit=0
  100 - /mnt/fsx/proj100/m1
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   13420   51200  102400       -       5    1024    2000       -


```

### A3.4 mv 延迟、root 写入、remount 保留（c4）
```
[SSM status=Success]
### 4.1 mv 进来的 30MiB 文件：等 30s 再看用量
31457280 bytes (31 MB, 30 MiB) copied, 0.0527908 s, 596 MB/s
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
  100 - /mnt/fsx/proj100/m2
t=0s        /mnt/fsx      66   51200  102400       -       4    1024    2000       -
t=10s        /mnt/fsx   30811   51200  102400       -       5    1024    2000       -
t=30s        /mnt/fsx   30811   51200  102400       -       5    1024    2000       -
t=60s        /mnt/fsx   30811   51200  102400       -       5    1024    2000       -
### 4.2 root 写入是否计入用量但不受限：root 在 project 目录写 120MiB（> 硬 100MiB）
125829120 bytes (126 MB, 120 MiB) copied, 1.30956 s, 96.1 MB/s
       /mnt/fsx  122996*  51200  102400       -       5    1024    2000       -
-- 此时 quser 再写 1MiB
0 bytes copied, 0.00321668 s, 0.0 kB/s
### 4.3 umount/remount 后配额设置是否保留
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
Block grace time: 1m; Inode grace time: 1m
  100 P /mnt/fsx/proj100


```

## A4. 观察与注意事项

1. **硬限制是"写到接近 limit 时拒绝"，不是精确到字节**：100 MiB 硬限写到 99 MiB 被拒；inode 2000 硬限到 1999 被拒（Lustre 配额按 qunit 分配给 OST/MDT）。
2. **超限后小写入的表现**：block 硬限触发后 `dd` 1 MiB 直接写入 0 字节；但 `echo hello > file`（几字节、走客户端缓存）在 3.1 中 exit=0——推测（未实测）：小写入先进 page cache，返回成功，回写时才可能失败；应用侧应检查 `close()/fsync()` 返回值。
3. **root 不受限但会占用 project 配额**：root 写入后 project 用量超限，普通用户随即被拒。运维用 root 拷数据进 project 目录时要注意。
4. **mv 进来的文件**：rename 后 projid 自动继承为 100，用量约 10 秒后才更新（t=0 未计入，t=10s 计入 30 MiB）。
5. **统计延迟**：删文件后 `lfs quota` 用量需数十秒才回落（2.8 删除后 10s 仍显示 51283 KiB，3.0 中再过 30s 回落到 66 KiB）。
6. **grace 字段**：超软限后显示剩余 grace（如 `1m`、`6d23h59m55s`），过期后显示 `none`，此时软限变硬限。
7. Project quota 只支持 Lustre 2.15（FSx 文档："Project quotas are only supported on Lustre version 2.15 on FSx for Lustre file systems"）。P1 默认版本是 2.10，**必须在创建时指定 `--file-system-type-version 2.15`**（或从 2.10/2.12 升级到 2.15）。

## A5. 资源清理
测试目录已删除并卸载；客户端 EC2 已 terminate；文件系统已删除（SkipFinalBackup）。

参考：[FSx for Lustre Storage quotas](https://docs.aws.amazon.com/fsx/latest/LustreGuide/lustre-quotas.html)

## A6. 复现脚本
[`scripts/`](./scripts/)：`upgrade_test.sh` 复现升级后不可用；`c0` 安装客户端 → `c1` 挂载/环境/建用户 → `c2` 设置配额 + block 硬限 + 对照 → `c3` 报错原文 + inode 硬限 + soft/grace + mv → `c4` mv 延迟 + root 写入 + remount 保留。按顺序以 root 执行。
