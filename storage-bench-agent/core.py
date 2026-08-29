"""
storage-bench-agent — 核心框架 (阶段一)
插件化设计: 每种测试类型 = 一个 TestPlugin, 骨架(起环境/收指标/画图/归档/清理)全通用.
fio 只是第一个插件; 后续 iperf3/sysbench/s3-throughput 只需新增插件, 不改骨架.

依赖: boto3, matplotlib (画图在 collect 阶段)
region 默认 us-east-2; EC2 默认 ohio key.
"""
from __future__ import annotations
import abc
import json
import time
import uuid
import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Any

import boto3

REGION = "us-east-2"
TASK_TABLE = "storage-bench-tasks"
DEFAULT_KEY = "ohio"

# ---------------------------------------------------------------------------
# 任务状态 (与 DynamoDB status 字段一致)
# ---------------------------------------------------------------------------
class Status:
    QUEUED = "QUEUED"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    ARCHIVING = "ARCHIVING"
    DONE = "DONE"
    FAILED = "FAILED"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 任务台账 (DynamoDB 读写)
# ---------------------------------------------------------------------------
class TaskStore:
    def __init__(self, table: str = TASK_TABLE, region: str = REGION):
        self._t = boto3.resource("dynamodb", region_name=region).Table(table)

    def create(self, params: dict) -> str:
        task_id = str(uuid.uuid4())
        now = _now()
        self._t.put_item(Item={
            "taskId": task_id,
            "status": Status.QUEUED,
            "createdAt": now,
            "updatedAt": now,
            "params": params,
            "resources": {},
            "progress": "queued",
        })
        return task_id

    def update(self, task_id: str, **fields):
        fields["updatedAt"] = _now()
        expr = "SET " + ", ".join(f"#{k}=:{k}" for k in fields)
        self._t.update_item(
            Key={"taskId": task_id},
            UpdateExpression=expr,
            ExpressionAttributeNames={f"#{k}": k for k in fields},
            ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
        )

    def get(self, task_id: str) -> dict:
        return self._t.get_item(Key={"taskId": task_id}).get("Item", {})


# ---------------------------------------------------------------------------
# 测试插件抽象 —— 扩展点
#   新增测试类型(iperf3/sysbench/s3-throughput...) = 实现一个子类即可
# ---------------------------------------------------------------------------
@dataclass
class TestContext:
    task_id: str
    params: dict
    store: TaskStore
    resources: dict = field(default_factory=dict)   # 记录已建资源, 供清理
    workdir: str = "/tmp"


class TestPlugin(abc.ABC):
    """所有测试类型的基类. testType -> 插件 由 REGISTRY 映射."""
    test_type: str = "base"

    @abc.abstractmethod
    def provision(self, ctx: TestContext) -> None:
        """起 EC2 + 挂目标存储 (或建网络/DB 环境). 把资源ID写进 ctx.resources."""

    @abc.abstractmethod
    def run(self, ctx: TestContext) -> dict:
        """在环境里跑压测(SSM 下发), 返回原始结果 dict."""

    @abc.abstractmethod
    def analyze(self, ctx: TestContext, raw: dict) -> dict:
        """解析原始结果 -> 结构化指标(吞吐/IOPS/延迟...)."""

    @abc.abstractmethod
    def plot(self, ctx: TestContext, metrics: dict) -> list[str]:
        """出图, 返回本地 PNG 路径列表."""

    def cleanup(self, ctx: TestContext) -> None:
        """默认清理: terminate EC2 / 删存储. 子类可覆盖. (需人工确认后才调用)"""
        # 通用: terminate ctx.resources 里的 ec2InstanceId 等
        raise NotImplementedError


REGISTRY: dict[str, type[TestPlugin]] = {}

def register(cls: type[TestPlugin]) -> type[TestPlugin]:
    REGISTRY[cls.test_type] = cls
    return cls


def get_plugin(test_type: str) -> TestPlugin:
    if test_type not in REGISTRY:
        raise ValueError(f"unknown testType={test_type}; known={list(REGISTRY)}")
    return REGISTRY[test_type]()


# ---------------------------------------------------------------------------
# 编排器 —— 通用骨架, 与具体测试类型无关
# ---------------------------------------------------------------------------
def orchestrate(task_id: str, store: TaskStore | None = None) -> None:
    store = store or TaskStore()
    task = store.get(task_id)
    params = task["params"]
    test_type = params.get("testType", "fio")   # 默认 fio
    plugin = get_plugin(test_type)
    ctx = TestContext(task_id=task_id, params=params, store=store)

    try:
        store.update(task_id, status=Status.PROVISIONING, progress="起环境+挂存储")
        plugin.provision(ctx)
        store.update(task_id, resources=ctx.resources)

        store.update(task_id, status=Status.RUNNING, progress="压测执行中")
        raw = plugin.run(ctx)

        store.update(task_id, status=Status.ANALYZING, progress="解析+画图")
        metrics = plugin.analyze(ctx, raw)
        pngs = plugin.plot(ctx, metrics)

        store.update(task_id, status=Status.ARCHIVING, progress="归档报告")
        result_url = archive_report(ctx, metrics, pngs, raw)

        store.update(task_id, status=Status.DONE, progress="完成", resultUrl=result_url)
        notify_feishu(task_id, metrics, result_url)   # 完成通知
    except Exception as e:  # noqa
        store.update(task_id, status=Status.FAILED, errorMsg=str(e))
        raise


# ---------------------------------------------------------------------------
# 归档 & 通知 (通用) —— 阶段一先留桩, T4/T7 实现
# ---------------------------------------------------------------------------
def archive_report(ctx: TestContext, metrics: dict, pngs: list[str], raw: dict) -> str:
    """生成 report.md + 上传 PNG/raw.json 到 S3, presign 返回 report.md 链接."""
    import config
    s3 = boto3.client("s3", region_name=REGION)
    key_base = f"{config.REPORT_PREFIX}/{ctx.task_id}"

    # report.md
    md = _render_markdown(ctx, metrics)
    s3.put_object(Bucket=config.REPORT_BUCKET, Key=f"{key_base}/report.md",
                  Body=md.encode(), ContentType="text/markdown")
    # raw json
    s3.put_object(Bucket=config.REPORT_BUCKET, Key=f"{key_base}/fio_raw.json",
                  Body=json.dumps(raw).encode(), ContentType="application/json")
    # pngs
    for png in pngs:
        name = png.rsplit("/", 1)[-1]
        with open(png, "rb") as fh:
            s3.put_object(Bucket=config.REPORT_BUCKET, Key=f"{key_base}/{name}",
                          Body=fh.read(), ContentType="image/png")
    # presign report.md (带 region, 延续 presign 铁律)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": config.REPORT_BUCKET, "Key": f"{key_base}/report.md"},
        ExpiresIn=config.PRESIGN_EXPIRE)


def _render_markdown(ctx: TestContext, m: dict) -> str:
    p = ctx.params
    f = p.get("fio", {})
    r, w = m.get("read", {}), m.get("write", {})
    return f"""# 存储实验报告 {ctx.task_id}

## 环境
- 存储类型: {p.get('storageType')}
- 机型: {p.get('instanceType')} @ {p.get('az', '')}
- 资源: {ctx.resources}

## 负载 (fio)
- rw={f.get('rw')} bs={f.get('bs')} iodepth={f.get('iodepth')} numjobs={f.get('numjobs')} runtime={f.get('runtime')}s size={f.get('size')}

## 结果
| 方向 | 吞吐(MB/s) | IOPS | P99延迟(us) |
|---|---|---|---|
| read | {r.get('bw_MBps')} | {r.get('iops')} | {r.get('clat_p99_us')} |
| write | {w.get('bw_MBps')} | {w.get('iops')} | {w.get('clat_p99_us')} |

![throughput](throughput.png)

## 结论
_(阶段一先给数据表; 后续接 LLM 生成结论草稿 + 对比历史同类实验)_
"""


def notify_feishu(task_id: str, metrics: dict, url: str) -> None:
    """飞书通知. 阶段一: 写一条待推消息到 S3/DynamoDB, 由 OpenClaw 主会话或 webhook 推送.
    (cron/lambda 无法直接调 OpenClaw message 工具, 故解耦: 这里只记录, 推送在外层做.)
    生产可改为直接 POST 飞书自定义机器人 webhook."""
    import config
    r = metrics.get("read", {})
    text = (f"[存储实验完成] {task_id}\n"
            f"{metrics.get('params', {}).get('storageType', '')} "
            f"读{r.get('bw_MBps')}MB/s / {r.get('iops')}IOPS\n报告: {url}")
    # 留桩: 写通知到 DynamoDB 供外层轮询推送 (T7 完善)
    try:
        TaskStore().update(task_id, notifyText=text)
    except Exception:
        pass


if __name__ == "__main__":
    # 本地冒烟: 打印已注册插件
    import plugin_fio  # noqa  触发注册
    print("registered testTypes:", list(REGISTRY))
