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
        p = ctx.params
        st = p["storageType"]                    # ebs | fsx-ontap
        itype = p.get("instanceType", "c6in.4xlarge")
        # TODO: AMI/subnet/SG 从 params 或默认配置取; 显式 AssociatePublicIpAddress=True
        # inst = ec2.run_instances(ImageId=..., InstanceType=itype, KeyName=DEFAULT_KEY,
        #     MinCount=1, MaxCount=1,
        #     NetworkInterfaces=[{"DeviceIndex":0,"AssociatePublicIpAddress":True,
        #                         "SubnetId":..., "Groups":[...]}],
        #     TagSpecifications=[{"ResourceType":"instance","Tags":[
        #         {"Key":"project","Value":"storage-bench-agent"},
        #         {"Key":"taskId","Value":ctx.task_id}]}])
        # ctx.resources["ec2InstanceId"] = inst["Instances"][0]["InstanceId"]
        #
        # if st == "ebs":   建 gp3 volume -> attach -> (等 SSM online) mkfs+mount /mnt/bench
        # if st == "fsx-ontap":  建/复用 FSx -> SVM/vol -> NFS mount (nconnect=16, 全卸载重挂避免首挂锁定)
        raise NotImplementedError("provision: T3 实现真实起环境 (先跑通 EBS)")

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
