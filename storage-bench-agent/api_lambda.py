"""
api_lambda.py — API Gateway 后端 (阶段一)
单 Lambda 处理 4 个路由 (proxy integration):
  POST /experiments            提交实验 -> 写 QUEUED + 异步触发 orchestrator -> 202 {taskId}
  GET  /experiments/{taskId}   查单任务
  GET  /experiments            列历史 (GSI status-createdAt-index)
  POST /experiments/{taskId}/cleanup  触发资源清理 (需前端二次确认)

异步触发 orchestrator: 阶段一用 Lambda 自身异步 invoke 另一个 orchestrator Lambda
(或 StepFunctions start-execution). 这里用 lambda invoke(InvocationType='Event').
"""
import json
import os
import boto3

from core import TaskStore, Status
import config

lambda_client = boto3.client("lambda", region_name=config.REGION)
ORCH_FN = os.environ.get("ORCHESTRATOR_FN", "storage-bench-orchestrator")

store = TaskStore()


def _resp(code, body):
    return {"statusCode": code,
            "headers": {"Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(body, default=str)}


def handler(event, _ctx):
    method = event["requestContext"]["http"]["method"] if "requestContext" in event and "http" in event["requestContext"] else event.get("httpMethod")
    path = event.get("rawPath") or event.get("path", "")
    pp = event.get("pathParameters") or {}

    # POST /experiments
    if method == "POST" and path.rstrip("/").endswith("/experiments"):
        params = json.loads(event.get("body") or "{}")
        # 最小校验
        if "storageType" not in params or "fio" not in params:
            return _resp(400, {"error": "need storageType + fio params"})
        task_id = store.create(params)
        lambda_client.invoke(FunctionName=ORCH_FN, InvocationType="Event",
                             Payload=json.dumps({"taskId": task_id}).encode())
        return _resp(202, {"taskId": task_id})

    # POST /experiments/{taskId}/cleanup
    if method == "POST" and path.endswith("/cleanup"):
        tid = pp.get("taskId")
        store.update(tid, progress="cleanup requested")
        lambda_client.invoke(FunctionName=ORCH_FN, InvocationType="Event",
                             Payload=json.dumps({"taskId": tid, "action": "cleanup"}).encode())
        return _resp(200, {"status": "cleaning", "taskId": tid})

    # GET /experiments/{taskId}
    if method == "GET" and pp.get("taskId"):
        item = store.get(pp["taskId"])
        return _resp(200, item) if item else _resp(404, {"error": "not found"})

    # GET /experiments  (列历史)
    if method == "GET":
        qs = event.get("queryStringParameters") or {}
        limit = int(qs.get("limit", 30))
        # 简化: scan (阶段一量小); 生产改用 GSI query by status
        import boto3 as b3
        t = b3.resource("dynamodb", region_name=config.REGION).Table(config.TASK_TABLE)
        items = t.scan(Limit=limit).get("Items", [])
        items.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return _resp(200, {"items": items})

    return _resp(400, {"error": "unhandled route"})
