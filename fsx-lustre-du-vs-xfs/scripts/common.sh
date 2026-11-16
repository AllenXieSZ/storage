# 用法：export FS_DNS=<fs-xxx.fsx.<region>.amazonaws.com> MOUNT_NAME=<mountname>；本地 xfs 挂在 /mnt/xfs
LMNT=/mnt/lustre; LD=/mnt/lustre/dutest; XD=/mnt/xfs/dutest
remount() { cd /; sync; umount /mnt/lustre && mount -t lustre -o relatime,flock ${FS_DNS}@tcp:/${MOUNT_NAME} /mnt/lustre; }
st() { stat -c "blocks=%b blksize=%B size=%s" "$1"; }
stable_remount() { sync; sleep 30; remount; sleep 5; remount; }
