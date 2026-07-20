# 自建 Lustre 集群 + HSM 归档到 S3 完整部署指南

在 AWS EC2 上自建 Lustre 并行文件系统，并通过开源 HSM copytool（Estuary）将文件归档到 Amazon S3，实现分层存储（archive / release / restore / remove）。

> 环境：AWS us-east-2，AlmaLinux 8.10，Lustre 2.15.8，实例 i7i.2xlarge。
> 本文所有 AK/SK、密码、公网 IP 均已用占位符脱敏，请替换为你自己的值。

---

## 目录
1. [架构概览](#1-架构概览)
2. [集群拓扑](#2-集群拓扑)
3. [Part A — 自建 Lustre 集群](#part-a--自建-lustre-集群)
4. [Part B — HSM 归档到 S3（Estuary copytool）](#part-b--hsm-归档到-s3estuary-copytool)
5. [运维与排错](#5-运维与排错)

---

## 1. 架构概览

```
                    ┌──────────────┐
                    │   MDS/MGS    │  管理 + 元数据 (MGT+MDT 合一)
                    │  /mnt/mdt    │
                    └──────┬───────┘
                           │ LNet (tcp)
          ┌────────────────┼────────────────┐
   ┌──────┴──────┐  ┌──────┴──────┐   ┌──────┴──────┐
   │    OSS1     │  │    OSS2     │   │   Client    │
   │ OST0 / OST1 │  │ OST2 / OST3 │   │ /mnt/lustre │
   └─────────────┘  └─────────────┘   └──────┬──────┘
                                             │ Estuary copytool
                                             ▼
                              ┌───────────────────────────┐
                              │  S3: <BUCKET>/lustre-hsm/ │
                              └───────────────────────────┘
```

- **MGS/MDT**：管理服务 + 元数据目标（本部署合并在一个 MDS 节点）。
- **OST**：对象存储目标，实际数据落地。每个 OSS 挂 2 个 OST。
- **Client**：挂载 `/mnt/lustre`，同时作为 HSM Agent 跑 copytool。
- **底层盘**：每个 target 用 mdadm RAID1（两块 EBS 镜像）做数据冗余。
- **HSM**：`lfs hsm_archive` 触发 → MDT 上的 Coordinator 派发 → Client 上的 Estuary copytool 把数据 PUT 到 S3。

---

## 2. 集群拓扑

每套集群 = 1×MDS + 2×OSS + 1×Client，全部 i7i.2xlarge / us-east-2a / AlmaLinux 8.10。

| 角色 | 挂载点 | 底层设备 | 说明 |
|------|--------|----------|------|
| MDS  | /mnt/mdt  | /dev/md0 (RAID1, 2×50G) | MGS+MDT 合一 |
| OSS1 | /mnt/ost0, /mnt/ost1 | /dev/md0, /dev/md1 (各 RAID1 2×100G) | OST index 0,1 |
| OSS2 | /mnt/ost2, /mnt/ost3 | /dev/md0, /dev/md1 (各 RAID1 2×100G) | OST index 2,3 |
| Client | /mnt/lustre | — | `<MDS_IP>@tcp:/lustrefs` |

- 文件系统名（fsname）：`lustrefs`
- LNet 网络：`tcp0(eth0)`，NID 形如 `<内网IP>@tcp`

---

## Part A — 自建 Lustre 集群

### A.0 前提

- 所有节点在同一 VPC/子网，安全组放行内部 LNet 通信（TCP 988 + 相关端口）与 SSH。
- 每台按角色额外挂 EBS 卷：MDS 2×50G（做 MDT RAID1）；每个 OSS 每个 OST 2×100G。
- 用同一版本的 Lustre（本文 2.15.8 / el8.10）。

### A.1 配置 Lustre 官方源（所有节点）

`/etc/yum.repos.d/lustre.repo`：

```ini
[lustre-server]
name=lustre-server
baseurl=https://downloads.whamcloud.com/public/lustre/latest-release/el8.10/server/
gpgcheck=0
enabled=0

[lustre-client]
name=lustre-client
baseurl=https://downloads.whamcloud.com/public/lustre/latest-release/el8.10/client/
gpgcheck=0
enabled=0

[e2fsprogs-wc]
name=e2fsprogs-wc
baseurl=https://downloads.whamcloud.com/public/e2fsprogs/latest/el8/
gpgcheck=0
enabled=1
```

> `enabled=0` 的 repo 用 `--enablerepo=` 临时启用，避免与系统内核冲突。

### A.2 安装 Lustre（服务端：MDS + OSS）

服务端需要 patched 内核 + ldiskfs（ZFS 后端可选，本文用 ldiskfs）：

```bash
# 装 e2fsprogs（whamcloud 版）
sudo dnf install -y --enablerepo=e2fsprogs-wc e2fsprogs

# 装 Lustre 服务端（含 patched kernel + osd-ldiskfs）
sudo dnf install -y --enablerepo=lustre-server \
  kernel kernel-devel kernel-modules \
  lustre lustre-osd-ldiskfs-mount kmod-lustre kmod-lustre-osd-ldiskfs

sudo reboot   # 重启进入 patched kernel
```

重启后确认：`uname -r` 应含 `_lustre`（如 `4.18.0-553.82.1.el8_lustre.x86_64`）。

### A.3 安装 Lustre（客户端）

客户端用 DKMS，不需要换内核：

```bash
sudo dnf install -y --enablerepo=lustre-client \
  lustre-client lustre-client-dkms
```

### A.4 配置 LNet（所有节点）

`/etc/modprobe.d/lnet.conf`：

```
options lnet networks=tcp0(eth0)
```

启用并确认 NID：

```bash
sudo modprobe lnet
sudo lctl network up
sudo lctl list_nids        # 输出 <内网IP>@tcp
```

### A.5 底层盘做 mdadm RAID1（所有 target）

以 MDS 的 MDT 为例（两块 50G EBS：nvme1n1 + nvme2n1）：

```bash
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/nvme1n1 /dev/nvme2n1
# 持久化 RAID 配置
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm.conf
# 例: ARRAY /dev/md0 metadata=1.2 UUID=a3103dbf:8a01ffc7:7bbdff07:ffec6eee
sudo dracut -f    # 让 initramfs 认识 RAID（重启后自动组装）
```

OSS 同理，每个 OST 一个 RAID1（md0=nvme1n1+nvme4n1, md1=nvme2n1+nvme3n1，两块 100G 一组）。

> ⚠️ **血泪教训**：改 fstab 换设备/换设备名后，务必 `systemctl daemon-reload`，否则 systemd 的 generated mount unit 仍绑旧设备，旧设备一消失就自动卸载挂载点。

### A.6 格式化 target（mkfs.lustre）

**MDS（MGT+MDT 合一，先做，index=0）：**

```bash
sudo mkfs.lustre --fsname=lustrefs --mgs --mdt --index=0 /dev/md0
sudo mkdir -p /mnt/mdt
sudo mount -t lustre /dev/md0 /mnt/mdt
```

**OSS1（OST index 0、1，指向 MGS）：**

```bash
MGS=<MDS内网IP>@tcp     # 例 <PRIVATE_IP>@tcp
sudo mkfs.lustre --fsname=lustrefs --ost --index=0 --mgsnode=$MGS /dev/md0
sudo mkfs.lustre --fsname=lustrefs --ost --index=1 --mgsnode=$MGS /dev/md1
sudo mkdir -p /mnt/ost0 /mnt/ost1
sudo mount -t lustre /dev/md0 /mnt/ost0
sudo mount -t lustre /dev/md1 /mnt/ost1
```

**OSS2（OST index 2、3）：**

```bash
MGS=<MDS内网IP>@tcp
sudo mkfs.lustre --fsname=lustrefs --ost --index=2 --mgsnode=$MGS /dev/md0
sudo mkfs.lustre --fsname=lustrefs --ost --index=3 --mgsnode=$MGS /dev/md1
sudo mkdir -p /mnt/ost2 /mnt/ost3
sudo mount -t lustre /dev/md0 /mnt/ost2
sudo mount -t lustre /dev/md1 /mnt/ost3
```

### A.7 客户端挂载

```bash
sudo mkdir -p /mnt/lustre
sudo mount -t lustre <MDS内网IP>@tcp:/lustrefs /mnt/lustre
lfs df          # 应看到 1 个 MDT + 4 个 OST
lfs df -i       # inode 视图
```

### A.8 开机自动挂载（fstab，所有节点）

```
# MDS /etc/fstab
/dev/md0 /mnt/mdt lustre _netdev,defaults 0 0

# OSS1 /etc/fstab
/dev/md0 /mnt/ost0 lustre _netdev,defaults 0 0
/dev/md1 /mnt/ost1 lustre _netdev,defaults 0 0

# OSS2 /etc/fstab
/dev/md0 /mnt/ost2 lustre _netdev,defaults 0 0
/dev/md1 /mnt/ost3 lustre _netdev,defaults 0 0

# Client /etc/fstab
<MDS内网IP>@tcp:/lustrefs /mnt/lustre lustre _netdev,defaults 0 0
```

改完执行 `sudo systemctl daemon-reload`。启动顺序：MGS/MDT → OST → client。

---

## Part B — HSM 归档到 S3（Estuary copytool）

Lustre 原生 HSM 只定义框架（Coordinator/Agent/Copytool），copytool 需自选。
本文用 **ICHEC Estuary**（`git.ichec.ie/performance/storage/estuary`，ComputeCanada lustre-obj-copytool 的现代后继，CMake + libs3 + curl）。

> 方案选型教训：
> - ❌ ComputeCanada 老 `lustre-obj-copytool`：2016 年代码，对 Lustre 2.15 头文件/链接不兼容。
> - ❌ `lhsmtool_posix` + s3fs 当后端：s3fs 会掉载，掉载后 copytool 无感知写本地目录 → **数据静默丢失**。淘汰。
> - ✅ Estuary：需改 3 处源码（见下），可用。

### B.1 准备 S3 权限（专用 IAM user，最小权限）

Estuary 用 **AK/SK**（不支持 IAM role）。建专用 user 只授归档前缀读写：

```bash
aws iam create-user --user-name lustre-hsm-copytool

cat > policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid":"ListBucket","Effect":"Allow",
      "Action":["s3:ListBucket","s3:GetBucketLocation"],
      "Resource":"arn:aws:s3:::<YOUR_BUCKET>" },
    { "Sid":"ObjectRW","Effect":"Allow",
      "Action":["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:GetObjectAttributes"],
      "Resource":"arn:aws:s3:::<YOUR_BUCKET>/lustre-hsm/*" }
  ]
}
EOF
aws iam put-user-policy --user-name lustre-hsm-copytool \
  --policy-name estuary-lustre-hsm-rw --policy-document file://policy.json

aws iam create-access-key --user-name lustre-hsm-copytool
# 记下 AccessKeyId / SecretAccessKey，填进 config（勿提交到 git）
```

### B.2 在 Client（HSM Agent）编译 Estuary

```bash
# 依赖
sudo dnf install -y git cmake gcc gcc-c++ make \
  libcurl-devel libxml2-devel openssl-devel libconfig-devel lz4-devel libbsd-devel
# cmake 需 >3.24（AlmaLinux 8.10 自带 3.26.5 够用）

git clone https://git.ichec.ie/performance/storage/estuary.git
cd estuary
```

**改源码 3 处（关键，见 patches/ 说明）：**

1. **加 S3 key 前缀**（让对象落进 `<bucket>/lustre-hsm/`）：
   `src/lhsmtool_s3.c` 中 6 处生成 object key 的 `snprintf`（行约 659/718/836/939/1203/1228），
   把 `"%s.%i"` / `"%s.0"` / `"%s.%llu"` 前面加上 `"lustre-hsm/"`。

2. **启用 SigV4 + VirtualHost**（否则 AWS us-east-2 拒绝 PUT，报 `S3Error ErrorUnknown: I/O error(5)`）：
   `src/lhsmtool_s3.h` 里 `bucketContext` 静态初始化，`S3UriStylePath` → `S3UriStyleVirtualHost`，
   并补齐 `securityToken=NULL, authRegion="us-east-2"`（authRegion 非空才启用 SigV4）：
   ```c
   S3BucketContext bucketContext = { host, bucket_prefix, S3ProtocolHTTP,
                                     S3UriStyleVirtualHost, access_key, secret_key,
                                     NULL, "us-east-2" };
   ```

3. **修 restore 数据损坏 bug**（原作者疑似只测过压缩路径）：
   restore 写回时 `uncompress_buf` 只在 `if(use_compression)` 里 malloc，无压缩时
   `pwrite(dst_fd, uncompress_buf=NULL, decompressed_size=object_chunk_size, ...)` 数据源+长度全错。
   修法：无压缩时写 `data.buffer`、长度用 `data.contentLength`（两处 pwrite + 对应 write_total/file_offset 累加）。
   参见 `patches/restore-uncompressed-fix.md`。

**编译（需指定 Lustre 源码树头文件路径）：**

```bash
BASE=/usr/src/lustre-client-2.15.8
INCS="-I$BASE/lustre/include/uapi -I$BASE/lustre/include -I$BASE/lnet/include/uapi -I$BASE/libcfs/include"

# liblustreapi 缺开发软链
sudo ln -sf /usr/lib64/liblustreapi.so.1.0.0 /usr/lib64/liblustreapi.so

mkdir build; cd build
cmake ../ -DCMAKE_C_FLAGS="$INCS" -DCMAKE_CXX_FLAGS="$INCS"
make
# 产物: build/bin/estuary_s3copytool
```

> ⚠️ 改源码后**别重跑 cmake**（会触发 libs3 FetchContent 重验证失败）。
> 只需重编单个 .o 并按 `build/src/CMakeFiles/estuary_s3copytool.dir/link.txt` 手动 link。

安装：
```bash
sudo cp build/bin/estuary_s3copytool /usr/sbin/
```

### B.3 config 文件

`/etc/estuary/config.cfg`（`chmod 600`）：

```
access_key = "<YOUR_ACCESS_KEY>";
secret_key = "<YOUR_SECRET_KEY>";
host = "s3.us-east-2.amazonaws.com";
bucket_prefix = "<YOUR_BUCKET>";
bucket_count = 1;
chunk_size = 104857600;
ssl = true
```

- `bucket_count = 1` 时，bucket 名直接 = `bucket_prefix`（单 bucket）。
- 对象在 S3 里命名为 `lustre-hsm/<FID编码>_..._....<chunk号>`（如 `0000000200001b71_00000009_00000000.0`），
  非原文件名；原始 size/chunk_size 存在对象的 x-amz-meta（totallength/chunksize），restore 靠它还原。

### B.4 MDS 上启用 HSM Coordinator（并固化开机自启）

临时启用：
```bash
sudo lctl set_param mdt.lustrefs-MDT0000.hsm_control=enabled
sudo lctl set_param mdt.lustrefs-MDT0000.hsm.default_archive_id=1
sudo lctl set_param mdt.lustrefs-MDT0000.hsm.max_requests=6
```

> `max_requests` = HSM Coordinator 每个 MDT 的并发派发上限，影响 archive/restore 并发（preload 速度）。
> 托管 FSx Lustre 上这个参数用户改不了（无 MDS shell）；自建可自由调。

固化（重启 MDS 后自动恢复）—— `/etc/systemd/system/lustre-hsm-coordinator.service`：
```ini
[Unit]
Description=Enable Lustre HSM Coordinator on MDT
After=lnet.service
RequiresMountsFor=/mnt/mdt

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sh -c 'until lctl get_param -N mdt.lustrefs-MDT0000.hsm_control >/dev/null 2>&1; do sleep 3; done'
ExecStart=/usr/sbin/lctl set_param mdt.lustrefs-MDT0000.hsm_control=enabled mdt.lustrefs-MDT0000.hsm.default_archive_id=1 mdt.lustrefs-MDT0000.hsm.max_requests=6

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lustre-hsm-coordinator.service
```

### B.5 Client 上 copytool 开机自启

`/etc/systemd/system/estuary-copytool.service`：
```ini
[Unit]
Description=Estuary Lustre HSM S3 Copytool
After=network-online.target remote-fs.target
Wants=network-online.target
RequiresMountsFor=/mnt/lustre

[Service]
Type=simple
ExecStartPre=/bin/sh -c 'until mountpoint -q /mnt/lustre; do echo waiting for /mnt/lustre; sleep 3; done'
ExecStart=/usr/sbin/estuary_s3copytool -c /etc/estuary/config.cfg --archive=1 /mnt/lustre
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/estuary.log
StandardError=append:/var/log/estuary.log

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now estuary-copytool.service
```

### B.6 验证 HSM 闭环

```bash
F=/mnt/lustre/test.bin
dd if=/dev/urandom of=$F bs=1M count=8
md5sum $F                                  # 记原始 md5

lfs hsm_archive $F                          # Lustre → S3
lfs hsm_state $F                            # 应显示 exists archived
aws s3 ls s3://<YOUR_BUCKET>/lustre-hsm/ --recursive   # 看到数据对象

lfs hsm_release $F                          # 释放本地(降为 stub)
du -h $F                                    # ≈512 字节
lfs hsm_restore $F                          # S3 → Lustre
md5sum $F                                   # 与原始一致 ✓

lfs hsm_remove $F                           # 删 Lustre 联动删 S3
```

已验证：单 chunk（8MB）+ 多 chunk（250MB 切成 100+100+50MB）restore 后 md5 均一致。

---

## 5. 运维与排错

- **查 HSM 状态**：`lfs hsm_state <file>`；`lctl get_param mdt.*.hsm_control mdt.*.hsm.*`（MDS 上）。
- **copytool 日志**：`/var/log/estuary.log`；`journalctl -u estuary-copytool`。
- **换 copytool 二进制前**：先 `pkill` 干净（残留会 "Text file busy"）。`pkill -9` 偶发时序不生效，改逐个 `kill -9 <pid>`，避免多 daemon 并存。
- **archive PUT 报 I/O error(5)**：99% 是 SigV4 没启用（检查 B.2 第 2 处改动的 authRegion）。用 `aws s3 cp` 同 AK/SK 手动 PUT 能成功即证明是 libs3 签名问题而非权限。
- **restore md5 不符**：检查 B.2 第 3 处 restore 写回修复。
- **改 fstab 换设备后**：务必 `systemctl daemon-reload`，否则 systemd generated mount unit 绑旧设备，旧设备消失即自动卸载。
- **RAID1 换盘**：重建速度受单盘 gp3 ~120MB/s 限制；`speed_limit_min` 默认 1000(KB/s) 会让重建极慢，可临时 `echo 200000 > /proc/sys/dev/raid/speed_limit_min` 提速。

---

*生成于 2026-07-20。所有凭证已脱敏。*
