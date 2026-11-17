M=/mnt/fsx; D=$M/proj100
echo "### 4.1 mv 进来的 30MiB 文件：等 30s 再看用量"
su quser -c "dd if=/dev/zero of=$M/noproj/m2 bs=1M count=30 oflag=direct" 2>&1 | tail -1
lfs quota -p 100 $M | tail -1
su quser -c "mv $M/noproj/m2 $D/m2"; lfs project $D/m2
for t in 0 10 30 60; do sleep $([ $t = 0 ] && echo 0 || echo $((t - ${last:-0}))); last=$t; echo "t=${t}s $(lfs quota -p 100 $M | tail -1)"; done
rm -f $D/m2; sleep 30
echo "### 4.2 root 写入是否计入用量但不受限：root 在 project 目录写 120MiB（> 硬 100MiB）"
dd if=/dev/zero of=$D/rootbig bs=1M count=120 oflag=direct 2>&1 | tail -1
sleep 30; lfs quota -p 100 $M | tail -1
echo "-- 此时 quser 再写 1MiB"
su quser -c "dd if=/dev/zero of=$D/u1 bs=1M count=1 oflag=direct" 2>&1 | tail -1
rm -f $D/rootbig $D/u1; sleep 30
echo "### 4.3 umount/remount 后配额设置是否保留"
umount $M; mount -t lustre -o relatime,flock ${FS_DNS}@tcp:/${MOUNT_NAME} $M
lfs quota -p 100 $M; lfs quota -t -p $M; lfs project -d $D
