#!/bin/bash
# 复现"升级到 2.15 后 project quota 不可用"
# 1) 建 P1 2.12（或 2.10）：
#    aws fsx create-file-system --file-system-type LUSTRE --file-system-type-version 2.12 --storage-type SSD \
#      --storage-capacity 1200 --subnet-ids <SUBNET> --security-group-ids <SG> \
#      --lustre-configuration DeploymentType=PERSISTENT_1,PerUnitStorageThroughput=50
# 2) 所有客户端 umount + lustre_rmmod（只 umount 会导致升级失败 "clients are currently connected"）
# 3) aws fsx update-file-system --file-system-id <FS_ID> --file-system-type-version 2.15
# 4) 升级完成后在 2.15 客户端以 root 执行本脚本：
#    export FS_DNS=<fs-xxx.fsx.<region>.amazonaws.com> MOUNT_NAME=<mountname>
: "${FS_DNS:?set FS_DNS}" "${MOUNT_NAME:?set MOUNT_NAME}"
M=/mnt/fsx; D=$M/proj29017; mkdir -p $M
mountpoint -q $M || mount -t lustre -o relatime,flock ${FS_DNS}@tcp:/${MOUNT_NAME} $M
id quser >/dev/null 2>&1 || useradd -u 2001 quser
echo "client: $(lctl get_param -n version)"; lctl get_param -n mdc.*.import | grep -m1 target_version
mkdir -p $D; chmod 777 $D
echo '$ lfs project -sp 29017'; lfs project -sp 29017 $D; echo rc=$?; lfs project -d $D
echo '$ lfs setquota -p 29017 -B 1G'; lfs setquota -p 29017 -B 1G $M; echo rc=$?
echo '$ lfs quota -p 29017'; lfs quota -p 29017 $M; echo rc=$?
echo '--- 只设继承标志、projid=0（对照）'; mkdir -p $M/p0; lfs project -s $M/p0; echo rc=$?; lfs project -d $M/p0
echo '--- strace'; command -v strace >/dev/null || dnf install -y strace >/dev/null 2>&1
strace -e trace=ioctl lfs project -sp 29017 $D 2>&1 | grep FSSETXATTR
echo '--- 生效验证：quser 写 1.5GiB'; su quser -c "dd if=/dev/zero of=$D/big bs=1M count=1536 oflag=direct" 2>&1 | tail -1
rm -f $D/big; dmesg | grep -E "quotactl|rc = -95|rc: -95" | tail -5
