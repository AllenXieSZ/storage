"""
plugin_fio.py — 第一个测试插件: fio 存储性能压测
支持 storageType: ebs (gp3 本地块) / fsx-ontap (NFS 挂载)
其余测试类型(iperf3/sysbench/s3-throughput) 照此模板新增即可.

坑规避(来自 TOOLS.md/MEMORY.md 实测笔记):
- EC2 默认不分配公网IP -> run-instances 显式 AssociatePublicIpAddress
- FSx nconnect 首挂锁定; NFS rsize/wsize 可能被钳到 64K
- fio group_reporting 是累计平均, 要瞬时须 diff 相邻快照
- 改 fstab 换设备后 daemon-reload
"""
from __future__ import annotations
import json
import time

import boto3

from core import TestPlugin, TestContext, register, REGION, DEFAULT_KEY

ec2 = boto3.client("ec2", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)


@register
class FioPlugin(TestPlugin):
    test_type = "fio"

    # ---- provision -------------------------------------------------------
    def provision(self, ctx: TestContext) -> None:
        import config
        p = ctx.params
        st = p["storageType"]                    # ebs | fsx-ontap
        itype = p.get("instanceType", config.DEFAULT_INSTANCE)
        subnet = p.get("subnet", config.DEFAULT_SUBNET)
        az = p.get("az", "us-east-2c")

        # 起 EC2 (显式 AssociatePublicIpAddress — default subnet 未必自动分配)
        inst = ec2.run_instances(
            ImageId=config.AMI_X86, InstanceType=itype, KeyName=config.KEY_NAME,
            MinCount=1, MaxCount=1,
            NetworkInterfaces=[{
                "DeviceIndex": 0, "AssociatePublicIpAddress": True,
                "SubnetId": subnet, "DeleteOnTermination": True,
            }],
            IamInstanceProfile={"Name": p.get("instanceProfile", config.INSTANCE_PROFILE)},
            TagSpecifications=[{"ResourceType": "instance", "Tags": config.tags(ctx.task_id)}],
        )
        iid = inst["Instances"][0]["InstanceId"]
        ctx.resources["ec2InstanceId"] = iid
        ec2.get_waiter("instance_running").wait(InstanceIds=[iid])

        if st == "ebs":
            sp = p.get("storageSpec", {})
            vol = ec2.create_volume(
                AvailabilityZone=az, Size=int(sp.get("size", 500)),
                VolumeType=sp.get("volumeType", "gp3"),
                Throughput=int(sp.get("throughput", 1000)), Iops=int(sp.get("iops", 16000)),
                TagSpecifications=[{"ResourceType": "volume", "Tags": config.tags(ctx.task_id)}],
            )
            vid = vol["VolumeId"]
            ctx.resources["volumeId"] = vid
            ec2.get_waiter("volume_available").wait(VolumeIds=[vid])
            ec2.attach_volume(VolumeId=vid, InstanceId=iid, Device="/dev/sdf")
            time.sleep(15)  # 等 SSM agent online + 设备可见
            # mkfs + mount (NVMe: /dev/sdf 常映射为 /dev/nvme1n1)
            self._ssm_run(iid, [
                "DEV=$(lsblk -dpno NAME | grep -E 'nvme[1-9]' | head -1)",
                "mkfs.xfs -f $DEV",
                "mkdir -p /mnt/bench && mount $DEV /mnt/bench",
                "df -h /mnt/bench",
            ])
        elif st == "fsx-ontap":
            # FSx ONTAP: 阶段一先支持"复用已有 FSx"(传 nfsEndpoint+junction), 建新 FSx 留 T8
            nfs = p["storageSpec"]["nfsEndpoint"]      # e.g. 172.31.35.226:/mfvol
            self._ssm_run(iid, [
                "yum install -y nfs-utils || true",
                "mkdir -p /mnt/bench",
                # 全卸载重挂避免 nconnect 首挂锁定; nconnect=16
                f"umount /mnt/bench 2>/dev/null; mount -t nfs -o nfsvers=3,nconnect=16 {nfs} /mnt/bench",
                "mount | grep /mnt/bench",
            ])
        else:
            raise ValueError(f"unsupported storageType={st}")

    # ---- run -------------------------------------------------------------
    def run(self, ctx: TestContext) -> dict:
        f = ctx.params["fio"]
        target = "/mnt/bench"
        fio_cmd = (
            f"fio --name=bench --directory={target} "
            f"--rw={f['rw']} --bs={f['bs']} --iodepth={f['iodepth']} "
            f"--numjobs={f['numjobs']} --runtime={f['runtime']} --time_based "
            f"--size={f['size']} --direct=1 --group_reporting "
            f"--output-format=json"
        )
        return self._ssm_run(ctx.resources["ec2InstanceId"], [
            "which fio || (yum install -y fio || apt-get install -y fio)",
            fio_cmd,
        ])

    # ---- analyze ---------------------------------------------------------
    def analyze(self, ctx: TestContext, raw: dict) -> dict:
        """从 fio JSON 抽 read/write 的 bw/iops/clat_p99."""
        out = raw.get("stdout", "")
        # fio JSON 在 stdout 里 (可能前面有 apt 输出, 取最后一个 { ... })
        start = out.find("{")
        data = json.loads(out[start:]) if start >= 0 else {}
        jobs = data.get("jobs", [{}])
        j = jobs[0]
        def side(k):
            d = j.get(k, {})
            return {
                "bw_MBps": round(d.get("bw", 0) / 1024, 2),   # fio bw=KB/s
                "iops": round(d.get("iops", 0)),
                "clat_p99_us": d.get("clat_ns", {}).get("percentile", {}).get("99.000000", 0) / 1000,
            }
        return {"read": side("read"), "write": side("write"),
                "params": ctx.params}

    # ---- plot ------------------------------------------------------------
    def plot(self, ctx: TestContext, metrics: dict) -> list[str]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        pngs = []
        # 吞吐柱状图 read vs write
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(["read", "write"],
               [metrics["read"]["bw_MBps"], metrics["write"]["bw_MBps"]],
               color=["#0067C5", "#F58220"])
        ax.set_ylabel("Throughput (MB/s)")
        ax.set_title(f"fio {ctx.params['fio']['rw']} {ctx.params['fio']['bs']}")
        path = f"{ctx.workdir}/throughput.png"
        fig.savefig(path, dpi=90, bbox_inches="tight")
        pngs.append(path)
        return pngs

    # ---- cleanup ---------------------------------------------------------
    def cleanup(self, ctx: TestContext) -> None:
        iid = ctx.resources.get("ec2InstanceId")
        if iid:
            ec2.terminate_instances(InstanceIds=[iid])
        # FSx/EBS 卷按 params/习惯: 默认保留(伟伟习惯), 由网页 cleanup 显式触发删

    # ---- helper ----------------------------------------------------------
    @staticmethod
    def _ssm_run(instance_id: str, commands: list[str], timeout: int = 3600) -> dict:
        r = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
            TimeoutSeconds=timeout,
        )
        cid = r["Command"]["CommandId"]
        while True:
            time.sleep(5)
            inv = ssm.get_command_invocation(CommandId=cid, InstanceId=instance_id)
            if inv["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
                return {"status": inv["Status"],
                        "stdout": inv.get("StandardOutputContent", ""),
                        "stderr": inv.get("StandardErrorContent", "")}
