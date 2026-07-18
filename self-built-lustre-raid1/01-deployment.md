# 自建 Lustre 2.15 集群部署记录（Ohio us-east-2）

**部署日期：** 2026-07-17
**方式：** lustre.org / Whamcloud 官方预编译 RPM + ldiskfs OSD（最主流方案）

## 架构

| 角色 | 实例 | 私网 IP | 公网 IP | 存储 |
|---|---|---|---|---|
| MGS+MDS | REDACTED (lustre-mds) | <PRIVATE_IP> | <PUBLIC_IP> | 50G gp3 → MGT+MDT (index 0) |
| OSS1 | REDACTED (lustre-oss1) | <PRIVATE_IP> | <PUBLIC_IP> | 2×100G gp3 → OST 0,1 |
| OSS2 | REDACTED (lustre-oss2) | <PRIVATE_IP> | <PUBLIC_IP> | 2×100G gp3 → OST 2,3 |
| Client | REDACTED (lustre-client) | <PRIVATE_IP> | <PUBLIC_IP> | 挂载点 /mnt/lustre |

- **实例类型：** i7i.2xlarge (8 vCPU / 64 GiB / up to 12 Gbps)
- **OS：** AlmaLinux 8.10 (REDACTED)
- **EBS：** 全部 gp3（root 30G + 数据盘）
- ⚠️ i7i 自带 1.7T 本地 NVMe（instance store）**未使用**，按要求全部用 EBS gp3
- **文件系统名：** `lustrefs`（4 OST，总容量 ~390 GB）
- **网络：** LNet tcp0(eth0)，VPC 私网；SG=REDACTED，REDACTED (us-east-2a)
- **Key：** <KEY>.pem（workspace 内）

## 软件版本
- **Lustre：** 2.15.8-1.el8（lustre.org / downloads.whamcloud.com latest-release/el8.10）
- **服务端 patched kernel：** 4.18.0-553.82.1.el8_lustre
- **e2fsprogs：** 1.47.3-wc2.el8（Whamcloud 专用版，服务端必需）
- **OSD：** ldiskfs（最主流方式，非 ZFS）
- **客户端：** lustre-client-dkms 2.15.8（DKMS 编译，对应 stock kernel 4.18.0-553.124.4）

## 安装踩坑记录
1. **patched kernel 被 distro kernel 盖掉**：`dnf install kernel` 会装 AlmaLinux 更高版本号的 stock kernel（.144.1），不是 lustre patched（.82.1）。必须**按完整 NVR 显式安装** `kernel-4.18.0-553.82.1.el8_lustre` 并 `grubby --set-default`，再在 dnf.conf 加 exclude 防止升级覆盖。装完 reboot 进 patched kernel 才能装 kmod-lustre。
2. **客户端 DKMS 缺依赖**：`dkms` 在 EPEL；`libyaml-devel`/`libmount-devel` 在 PowerTools/CRB 仓库。装 DKMS 前先 `dnf install epel-release` + `dnf config-manager --set-enabled powertools`。
3. **EBS 设备名 NVMe 重映射**：EBS 挂进去变 /dev/nvmeXn1，顺序不固定。**按 MODEL="Amazon Elastic Block Store" + 容量识别**，别抓到 "Amazon EC2 NVMe Instance Storage"（本地临时盘）。
4. **SELinux**：Lustre 要求关闭，脚本已 setenforce 0 + 改 config。

## 关键命令
### 服务端格式化
```
# MGS+MDT（combined）
mkfs.lustre --fsname=lustrefs --mgs --mdt --index=0 --reformat /dev/nvme1n1
# OST（mgsnode 指向 MDS 私网 NID）
mkfs.lustre --fsname=lustrefs --ost --mgsnode=<PRIVATE_IP>@tcp --index=N --reformat /dev/nvmeXn1
```
### 挂载顺序（重启后）：先 MGS/MDT → 再 OST → 最后 client
```
# MDS:  mount -t lustre /dev/nvme1n1 /mnt/mdt
# OSS:  mount -t lustre /dev/nvmeXn1 /mnt/ostN
# 客户端: mount -t lustre <PRIVATE_IP>@tcp:/lustrefs /mnt/lustre
```
LNet 配置：`/etc/modprobe.d/lnet.conf` = `options lnet networks=tcp0(eth0)`
已写入 /etc/fstab（_netdev），重启自动挂载。

## 验证结果
- 4 个 OST 全部 ACTIVE，MDT 正常注册
- `lfs df -h`：390G 总容量
- stripe -c 4 文件的对象跨 OST 0/1/2/3 分布正常
- 单流 dd ~143 MB/s；4 并行流各 ~143 MB/s（聚合 ~572 MB/s，符合 4×gp3 基线 125MB/s + burst）

## 成本提示
4 台 i7i.2xlarge 持续运行有成本；不用时 `aws ec2 stop-instances`（EBS 数据保留，本地 NVMe 会丢但未使用）。
彻底删除：terminate 4 实例（DeleteOnTermination=true，EBS 会一起删）。
