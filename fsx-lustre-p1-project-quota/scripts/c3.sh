M=/mnt/fsx; D=$M/proj100
echo "### 3.0 当前目录内容 + 等 30s 后 usage（检查删除后的统计）"
ls -la $D; du -sk $D; sleep 30; lfs quota -p 100 $M
echo "### 3.1 block 硬限制报错原文（quser 写 150MiB）"
su quser -c "dd if=/dev/zero of=$D/big2 bs=1M count=150 oflag=direct" 2>&1
echo "exit=$?"; ls -l $D/big2
su quser -c "echo hello > $D/small.txt" 2>&1; echo "small write exit=$?"
rm -f $D/big2 $D/small.txt; sync; sleep 30; lfs quota -p 100 $M
echo "### 3.2 inode 硬限制：quser 在 project 目录建 2500 个文件（硬 2000）"
su quser -c "mkdir -p $D/many; cnt=0; for i in \$(seq 1 2500); do touch $D/many/f\$i 2>/tmp/terr || { echo \"failed at #\$i: \$(cat /tmp/terr)\"; break; }; cnt=\$i; done; echo created=\$cnt"
ls $D/many | wc -l; lfs quota -p 100 $M
rm -rf $D/many; sync; sleep 20; lfs quota -p 100 $M
echo "### 3.3 soft limit + grace：block grace 改成 60s"
lfs setquota -t -p -b 60 -i 60 $M; lfs quota -t -p $M
lfs setquota -p 100 -b 51200 -B 102400 -i 1024 -I 2000 $M
su quser -c "dd if=/dev/zero of=$D/soft1 bs=1M count=70 oflag=direct" 2>&1 | tail -1
lfs quota -p 100 $M
echo "-- 在 grace 内（超软限未超硬限）继续写 10MiB"
su quser -c "dd if=/dev/zero of=$D/soft2 bs=1M count=10 oflag=direct" 2>&1 | tail -1
echo "-- 等 90s 让 grace 过期后再写 10MiB（预期被拒）"
sleep 90; lfs quota -p 100 $M
su quser -c "dd if=/dev/zero of=$D/soft3 bs=1M count=10 oflag=direct" 2>&1
ls -l $D/
rm -f $D/soft*; sync
echo "### 3.4 把已有的非 project 文件 mv 进来是否计入（rename 同 FS）"
su quser -c "dd if=/dev/zero of=$M/noproj/m1 bs=1M count=30 oflag=direct" 2>&1 | tail -1
lfs project $M/noproj/m1
su quser -c "mv $M/noproj/m1 $D/m1" 2>&1; echo "mv exit=$?"; lfs project $D/m1 2>&1; sleep 10; lfs quota -p 100 $M
rm -f $D/m1 $M/noproj/*
