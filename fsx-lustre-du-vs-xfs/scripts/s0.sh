: "${FS_DNS:?set FS_DNS}" "${MOUNT_NAME:?set MOUNT_NAME}"
set -x
dnf install -y lustre-client >/dev/null 2>&1; rpm -qa | grep -i lustre
lsblk
DEV=$(lsblk -dpno NAME,SIZE | awk '$2=="250G"{print $1}')
mkfs.xfs -f $DEV && mkdir -p /mnt/xfs && mount $DEV /mnt/xfs
mkdir -p /mnt/lustre && mount -t lustre -o relatime,flock ${FS_DNS}@tcp:/${MOUNT_NAME} /mnt/lustre
lctl get_param version
mount | grep -E 'lustre|xfs'
lfs getstripe -d /mnt/lustre/
df -Th / /mnt/xfs /mnt/lustre
lfs df -h /mnt/lustre
cat /proc/fs/lustre/llite/*/dom_read_open 2>/dev/null; lctl get_param llite.*.dom_read_open 2>/dev/null
uname -r
xfs_info /mnt/xfs
ls -la /mnt/lustre
lctl get_param mdc.*.max_easize lov.*.stripesize lov.*.stripecount 2>/dev/null
