# 方向B 命令速查(脱敏)

## 建环境(1HA FlexVol 起点)
```bash
aws fsx create-file-system --file-system-type ONTAP --storage-capacity 2048 \
  --subnet-ids <SUBNET> --security-group-ids <SG> --storage-type SSD \
  --ontap-configuration '{"DeploymentType":"SINGLE_AZ_2","ThroughputCapacityPerHAPair":384,"HAPairs":1,"PreferredSubnetId":"<SUBNET>","FsxAdminPassword":"<PW>"}'
aws fsx create-storage-virtual-machine --file-system-id <FSID> --name mfsvm --root-volume-security-style UNIX
aws fsx create-volume --volume-type ONTAP --name mfvol \
  --ontap-configuration '{"StorageVirtualMachineId":"<SVM>","JunctionPath":"/mfvol","SizeInMegabytes":1843200,"SecurityStyle":"UNIX","StorageEfficiencyEnabled":false,"TieringPolicy":{"Name":"NONE"}}'
```

## 就地升级链路
```bash
# ① 先升 throughput(必须先做)
aws fsx update-file-system --file-system-id <FSID> --ontap-configuration '{"ThroughputCapacityPerHAPair":1536}'
# ② 再扩 HA + storage(storage 必须翻倍)
aws fsx update-file-system --file-system-id <FSID> --storage-capacity 4096 \
  --ontap-configuration '{"HAPairs":2,"ThroughputCapacityPerHAPair":1536}'
# ③ FlexVol → FlexGroup(需 diag 权限;卷必须干净=没接过 DataSync)
ssh fsxadmin@<MGMT_IP>
  set -privilege diagnostic -confirmations off
  volume conversion start -vserver mfsvm -volume mfvol -foreground false
  job show -id <jobid>            # 期望 Success
# ④ expand 跨 aggr(每 aggr 4 个 constituent)
  volume expand -vserver mfsvm -volume mfvol -aggr-list aggr1,aggr2 -aggr-list-multiplier 4
```

## 测分布
```bash
# 每档写文件后:
volume show -vserver mfsvm -volume mfvol_* -fields aggregate,used
storage aggregate show -fields node,usedsize
```

## 造文件(真实非稀疏,16 进程并行)
```bash
seq 0 499 | xargs -P 16 -I{} sh -c 'dd if=/dev/urandom of=/mfvol/data/f{}.bin bs=1M count=1024 status=none && sync'
```
