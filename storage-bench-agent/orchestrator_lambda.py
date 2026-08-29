"""
orchestrator_lambda.py — 异步编排 Lambda (阶段一)
被 api_lambda 异步 invoke. 调 core.orchestrate 跑完整流程, 或执行 cleanup.

⚠️ 单 Lambda 15min 上限: 若 fio runtime + provision 可能 > 15min,
   阶段二改用 Step Functions (每步一个 state, 轮询等待). 阶段一 fio runtime<=300s
   + provision 数分钟, 勉强可放单 Lambda(配 15min timeout); 建议尽早上 StepFunctions.
"""
import plugin_fio  # noqa 触发插件注册
from core import orchestrate, TaskStore, TestContext, get_plugin


def handler(event, _ctx):
    task_id = event["taskId"]
    action = event.get("action")
    store = TaskStore()

    if action == "cleanup":
        task = store.get(task_id)
        plugin = get_plugin(task["params"].get("testType", "fio"))
        ctx = TestContext(task_id=task_id, params=task["params"],
                          store=store, resources=task.get("resources", {}))
        plugin.cleanup(ctx)
        store.update(task_id, progress="cleaned")
        return {"ok": True}

    orchestrate(task_id, store)
    return {"ok": True}
