"""本地端到端跑一次真实 EBS 实验 (验证 provision->run->analyze->plot->archive)"""
import plugin_fio  # 注册
from core import TaskStore, orchestrate

params = {
    "testType": "fio",
    "storageType": "ebs",
    "instanceType": "c6in.4xlarge",
    "az": "us-east-2c",
    "region": "us-east-2",
    "storageSpec": {"size": 500, "volumeType": "gp3", "throughput": 1000, "iops": 16000},
    "fio": {"rw": "randread", "bs": "4k", "iodepth": 32, "numjobs": 4, "runtime": 120, "size": "10G"},
}
store = TaskStore()
tid = store.create(params)
print("TASK_ID", tid)
orchestrate(tid, store)
print("FINAL", store.get(tid).get("status"), store.get(tid).get("resultUrl"))
