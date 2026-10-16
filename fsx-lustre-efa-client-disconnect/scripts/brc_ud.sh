#!/bin/bash
exec > /var/log/ud.log 2>&1
dnf install -y fio unzip python3 iperf3 jq >/dev/null
cd /root; curl -sO https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/install-fsx-lustre-client.zip; unzip -oq install-fsx-lustre-client.zip
cd install-fsx-lustre-client && ./bin/install-fsx-lustre-client.sh --install-lustre --install-efa
cd /root; curl -sO https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/configure-efa-fsx-lustre-client.zip; unzip -oq configure-efa-fsx-lustre-client.zip
cd /root/configure-efa-fsx-lustre-client && ./setup.sh > /root/setup.log 2>&1
mkdir -p /fsx
touch /root/UD_DONE
