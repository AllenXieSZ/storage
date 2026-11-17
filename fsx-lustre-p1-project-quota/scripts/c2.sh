M=/mnt/fsx; D=$M/proj100
echo "### 2.1 创建目录、绑定 project 100（继承标志 -s，递归 -r）"
mkdir -p $D; chown quser:quser $D; chmod 777 $D
lfs project -p 100 -r -s $D; echo "rc=$?"
lfs project -d $D
echo "### 2.2 设置 project 100 配额：block 软 50MiB / 硬 100MiB，inode 软 1024 / 硬 2000"
lfs setquota -p 100 -b 51200 -B 102400 -i 1024 -I 2000 $M; echo "rc=$?"
lfs quota -p 100 $M
lfs quota -p 100 -v $M | tail -6
echo "### 2.3 子目录/新文件是否继承 projid"
su quser -c "mkdir $D/sub && touch $D/sub/a && touch $D/b"
lfs project -d $D/sub; lfs project $D/sub/a $D/b
echo "### 2.4 block 硬限制：quser 写 150MiB（硬 100MiB），预期 Disk quota exceeded"
su quser -c "dd if=/dev/zero of=$D/big bs=1M count=150 oflag=direct 2>&1 | tail -3"
ls -l $D/big; sync; sleep 5
lfs quota -p 100 $M
echo "### 2.5 超限后再写 1 个小文件"
su quser -c "dd if=/dev/zero of=$D/after bs=1M count=1 oflag=direct 2>&1 | tail -2"
echo "### 2.6 对照：同 FS 上不属于 project 的目录，quser 写 150MiB，预期成功"
mkdir -p $M/noproj; chmod 777 $M/noproj; lfs project -d $M/noproj
su quser -c "dd if=/dev/zero of=$M/noproj/big bs=1M count=150 oflag=direct 2>&1 | tail -1"
echo "### 2.7 对照：root 在 project 目录写 50MiB（文档说 root 不受限）"
dd if=/dev/zero of=$D/rootfile bs=1M count=50 oflag=direct 2>&1 | tail -1
lfs project $D/rootfile; lfs quota -p 100 $M
echo "### 2.8 删文件后恢复写入"
rm -f $D/big $D/rootfile $D/after; sync; sleep 10
lfs quota -p 100 $M
su quser -c "dd if=/dev/zero of=$D/again bs=1M count=20 oflag=direct 2>&1 | tail -1"
rm -f $D/again
