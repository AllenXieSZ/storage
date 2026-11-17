# FSx for Lustre Persistent 1（Lustre 2.15）设置 Project Quota 实测

测试时间：2026-11-17（us-east-2）。结论：**可以设置，且 limit 生效**（block 硬限、inode 硬限、soft limit + grace 均实测生效）。

## 0. 结论速览（全部已实测）

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

## 1. 环境

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

## 2. 配额设置命令
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

## 3. 原始输出

### 3.1 挂载与环境（c1）
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

### 3.2 设置配额 + block 硬限制 + 对照（c2）
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

### 3.3 报错原文 + inode 硬限 + soft/grace + mv（c3）
```
[SSM status=Success]
### 3.0 当前目录内容 + 等 30s 后 usage（检查删除后的统计）
total 59
drwxrwxrwx. 3 quser quser 25600 Nov 17 01:46 .
drwxr-xr-x. 6 root  root  33280 Nov 17 01:46 ..
-rw-r--r--. 1 quser quser     0 Nov 17 01:46 b
drwxr-xr-x. 2 quser quser  1024 Nov 17 01:46 sub
51	/mnt/fsx/proj100
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
### 3.1 block 硬限制报错原文（quser 写 150MiB）
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
### 3.2 inode 硬限制：quser 在 project 目录建 2500 个文件（硬 2000）
failed at #1996: touch: cannot touch '/mnt/fsx/proj100/many/f1996': Disk quota exceeded
created=1995
1995
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   17288   51200  102400       -    1999*   1024    2000 6d23h59m57s
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx      66   51200  102400       -       4    1024    2000       -
### 3.3 soft limit + grace：block grace 改成 60s
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
### 3.4 把已有的非 project 文件 mv 进来是否计入（rename 同 FS）
31457280 bytes (31 MB, 30 MiB) copied, 0.0668827 s, 470 MB/s
    0 - /mnt/fsx/noproj/m1
mv exit=0
  100 - /mnt/fsx/proj100/m1
Disk quotas for prj 100 (pid 100):
     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace
       /mnt/fsx   13420   51200  102400       -       5    1024    2000       -


```

### 3.4 mv 延迟、root 写入、remount 保留（c4）
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

## 4. 观察与注意事项

1. **硬限制是"写到接近 limit 时拒绝"，不是精确到字节**：100 MiB 硬限写到 99 MiB 被拒；inode 2000 硬限到 1999 被拒（Lustre 配额按 qunit 分配给 OST/MDT）。
2. **超限后小写入的表现**：block 硬限触发后 `dd` 1 MiB 直接写入 0 字节；但 `echo hello > file`（几字节、走客户端缓存）在 3.1 中 exit=0——推测（未实测）：小写入先进 page cache，返回成功，回写时才可能失败；应用侧应检查 `close()/fsync()` 返回值。
3. **root 不受限但会占用 project 配额**：root 写入后 project 用量超限，普通用户随即被拒。运维用 root 拷数据进 project 目录时要注意。
4. **mv 进来的文件**：rename 后 projid 自动继承为 100，用量约 10 秒后才更新（t=0 未计入，t=10s 计入 30 MiB）。
5. **统计延迟**：删文件后 `lfs quota` 用量需数十秒才回落（2.8 删除后 10s 仍显示 51283 KiB，3.0 中再过 30s 回落到 66 KiB）。
6. **grace 字段**：超软限后显示剩余 grace（如 `1m`、`6d23h59m55s`），过期后显示 `none`，此时软限变硬限。
7. Project quota 只支持 Lustre 2.15（FSx 文档："Project quotas are only supported on Lustre version 2.15 on FSx for Lustre file systems"）。P1 默认版本是 2.10，**必须在创建时指定 `--file-system-type-version 2.15`**（或从 2.10/2.12 升级到 2.15）。

## 5. 资源清理
测试目录已删除并卸载；客户端 EC2 已 terminate；文件系统已删除（SkipFinalBackup）。

参考：[FSx for Lustre Storage quotas](https://docs.aws.amazon.com/fsx/latest/LustreGuide/lustre-quotas.html)

## 6. 复现脚本
[`scripts/`](./scripts/)：`c0` 安装客户端 → `c1` 挂载/环境/建用户 → `c2` 设置配额 + block 硬限 + 对照 → `c3` 报错原文 + inode 硬限 + soft/grace + mv → `c4` mv 延迟 + root 写入 + remount 保留。按顺序以 root 执行。
