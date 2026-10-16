#!/bin/bash
# 挂载并检查 OST 连接状态
systemctl is-active configure-efa-fsx-lustre-client.service; lctl list_nids
mountpoint -q /fsx || mount -t lustre -o relatime,flock <FS_DNS>@tcp:/<MOUNT_NAME> /fsx; sleep 15
lctl get_param -n osc.*.import | awk '/state:/{print $2}' | sort | uniq -c
