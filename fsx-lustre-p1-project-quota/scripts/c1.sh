# 用法：export FS_DNS=<fs-xxx.fsx.<region>.amazonaws.com> MOUNT_NAME=<mountname>；以 root 运行，脚本内用普通用户 quser 写入
set -x
mkdir -p /mnt/fsx
mount -t lustre -o relatime,flock ${FS_DNS}@tcp:/${MOUNT_NAME} /mnt/fsx
mount | grep lustre
lctl get_param version
lctl get_param -n osc.*.import | grep -m1 target_version
lctl get_param -n mdc.*.import | grep -m1 target_version
lfs df -h /mnt/fsx
lfs df -i /mnt/fsx
# quota infrastructure
lfs quota -u root /mnt/fsx
lfs quota -p 100 /mnt/fsx
lctl get_param -n mdc.*.import | grep -iE "connect_flags" | head -2
lctl get_param -n osc.*.import | grep -iE "connect_flags" | head -1
# test users
useradd -u 2001 quser 2>/dev/null; id quser
