#!/usr/bin/env python3
"""
FSx Lustre 维护窗口隔周调度器 v2
=================================
用法:
  python3 fsx_mw_scheduler.py list   --region us-east-2 [--output fsx_lustre_list.csv]
  python3 fsx_mw_scheduler.py deploy --region us-east-2 --bucket <S3桶> [--csv fsx_lustre_list.csv]
                                     [--first-skip-week 2026-11-23] [--email ops@example.com]
  python3 fsx_mw_scheduler.py remove --region us-east-2 [--csv fsx_lustre_list.csv | --all]

部署内容:
  - CSV 上传到 s3://<bucket>/fsx-mw/fsx_lustre_list.csv，Lambda 每次执行都重新读取（原始维护窗口的唯一来源）
  - 1 个共用 Lambda: fsx-mw-scheduler
  - 每个 FS 2 个 EventBridge Scheduler 计划（按 CSV 维护窗口计算的 cron，UTC）:
      fsx-mw-skip-<fs>     每周 窗口-12h，跳过周把窗口写为 原始-24h
      fsx-mw-restore-<fs>  每周 窗口+12h，把窗口写回 原始值
  - 重试 3 次 + SQS 死信队列 fsx-mw-dlq + CloudWatch 告警 -> SNS fsx-mw-alerts
"""
import argparse
import csv
import io
import json
import os
import time
import zipfile
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

FUNC_NAME = "fsx-mw-scheduler"
LAMBDA_ROLE = "fsx-mw-scheduler-lambda-role"
SCHED_ROLE = "fsx-mw-scheduler-invoke-role"
GROUP = "fsx-mw"
DLQ_NAME = "fsx-mw-dlq"
TOPIC_NAME = "fsx-mw-alerts"
CSV_KEY = "fsx-mw/fsx_lustre_list.csv"
HERE = os.path.dirname(os.path.abspath(__file__))

DAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
DAY_EN = {1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI", 6: "SAT", 7: "SUN"}


# ─── 工具函数 ──────────────────────────────────
def parse_mw(mw):
    d, h, m = (int(x) for x in mw.split(":"))
    if not (1 <= d <= 7 and 0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(mw)
    return d, h, m


def shift(mw, hours):
    d, h, m = parse_mw(mw)
    t = ((d - 1) * 24 + h + hours) % 168
    return t // 24 + 1, t % 24, m


def human(mw):
    d, h, m = parse_mw(mw)
    return f"{DAY_CN[d]} {h:02d}:{m:02d} UTC"


def cron_at(mw, offset_hours):
    """维护窗口偏移 offset_hours 后的每周 cron（EventBridge Scheduler 格式）"""
    d, h, m = shift(mw, offset_hours)
    return f"cron({m} {h} ? * {DAY_EN[d]} *)", f"{DAY_CN[d]} {h:02d}:{m:02d} UTC"


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("FileSystemId", "").strip()]
    for r in rows:
        try:
            parse_mw(r["MaintenanceWindow"].strip())
        except Exception:
            raise SystemExit(f"❌ CSV 中 {r['FileSystemId']} 的维护窗口格式非法: {r['MaintenanceWindow']}（应为 d:HH:MM）")
    return rows


def retry(fn, what, tries=6, wait=5):
    """IAM 角色刚创建时常有传播延迟，统一重试"""
    for i in range(tries):
        try:
            return fn()
        except ClientError as e:
            if i == tries - 1 or e.response["Error"]["Code"] not in (
                    "InvalidParameterValueException", "ValidationException", "AccessDeniedException"):
                raise
            print(f"   ⏳ {what} 失败（{e.response['Error']['Code']}），{wait}s 后重试（IAM 传播中）")
            time.sleep(wait)


# ─── list ──────────────────────────────────────
def cmd_list(a):
    fsx = boto3.client("fsx", region_name=a.region)
    rows = []
    for page in fsx.get_paginator("describe_file_systems").paginate():
        for fs in page["FileSystems"]:
            if fs["FileSystemType"] != "LUSTRE":
                continue
            mw = fs.get("LustreConfiguration", {}).get("WeeklyMaintenanceStartTime", "")
            name = next((t["Value"] for t in fs.get("Tags", []) if t["Key"] == "Name"), "")
            rows.append({"Name": name, "FileSystemId": fs["FileSystemId"], "MaintenanceWindow": mw,
                         "MaintenanceWindowHuman": human(mw) if mw else "", "Timezone": "UTC"})
    with open(a.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "FileSystemId", "MaintenanceWindow",
                                          "MaintenanceWindowHuman", "Timezone"])
        w.writeheader()
        w.writerows(rows)
    print(f"✅ 已写入 {len(rows)} 个 FSx Lustre 文件系统到 {a.output}")
    for r in rows:
        print(f"   {r['FileSystemId']}  {r['Name']:<28s} 维护窗口={r['MaintenanceWindow']}（{r['MaintenanceWindowHuman']}）")
    print("💡 请编辑 CSV，只保留需要改为隔周维护的文件系统；MaintenanceWindow 列即原始窗口")


# ─── deploy ────────────────────────────────────
def ensure_role(iam, name, service, policy):
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
             "Principal": {"Service": service}, "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
        print(f"   IAM 角色 {name} 已存在")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        arn = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="FSx Lustre biweekly maintenance window scheduler")["Role"]["Arn"]
        print(f"   ✅ 已创建 IAM 角色 {name}")
    iam.put_role_policy(RoleName=name, PolicyName=f"{name}-policy", PolicyDocument=json.dumps(policy))
    return arn


def cmd_deploy(a):
    s = boto3.Session(region_name=a.region)
    acct = s.client("sts").get_caller_identity()["Account"]
    rows = read_csv(a.csv)
    if not rows:
        raise SystemExit("❌ CSV 里没有文件系统")
    print(f"📋 从 {a.csv} 读取到 {len(rows)} 个文件系统")

    # 第一个跳过周：默认本周（若本周最早的 skip 时间点已过，则仍从下一个跳过周生效）
    first = a.first_skip_week or datetime.now(timezone.utc).date().isoformat()
    datetime.strptime(first, "%Y-%m-%d")

    # 1. 上传 CSV
    s.client("s3").upload_file(a.csv, a.bucket, CSV_KEY)
    print(f"✅ CSV 已上传到 s3://{a.bucket}/{CSV_KEY}（Lambda 每次执行都读取它）")

    # 2. SNS + SQS 死信队列
    sns, sqs = s.client("sns"), s.client("sqs")
    topic = sns.create_topic(Name=TOPIC_NAME)["TopicArn"]
    if a.email:
        sns.subscribe(TopicArn=topic, Protocol="email", Endpoint=a.email)
        print(f"   📧 已向 {a.email} 发送订阅确认邮件，请点击确认")
    q_url = sqs.create_queue(QueueName=DLQ_NAME, Attributes={"MessageRetentionPeriod": "1209600"})["QueueUrl"]
    q_arn = sqs.get_queue_attributes(QueueUrl=q_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    print(f"✅ 告警主题 {TOPIC_NAME}，死信队列 {DLQ_NAME}")

    # 3. IAM 角色
    iam = s.client("iam")
    lam_role = ensure_role(iam, LAMBDA_ROLE, "lambda.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": f"arn:aws:logs:{a.region}:{acct}:*"},
        {"Effect": "Allow", "Action": "fsx:DescribeFileSystems", "Resource": "*"},
        {"Effect": "Allow", "Action": "fsx:UpdateFileSystem",
         "Resource": [f"arn:aws:fsx:{a.region}:{acct}:file-system/{r['FileSystemId']}" for r in rows]},
        {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{a.bucket}/{CSV_KEY}"},
        {"Effect": "Allow", "Action": "sqs:SendMessage", "Resource": q_arn}]})
    func_arn = f"arn:aws:lambda:{a.region}:{acct}:function:{FUNC_NAME}"
    sch_role = ensure_role(iam, SCHED_ROLE, "scheduler.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": func_arn},
        {"Effect": "Allow", "Action": "sqs:SendMessage", "Resource": q_arn}]})

    # 4. Lambda（共用一个）
    lam = s.client("lambda")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(HERE, "lambda_function.py"), "lambda_function.py")
    env = {"Variables": {"CSV_BUCKET": a.bucket, "CSV_KEY": CSV_KEY, "FIRST_SKIP_WEEK": first}}
    try:
        lam.get_function(FunctionName=FUNC_NAME)
        lam.update_function_code(FunctionName=FUNC_NAME, ZipFile=buf.getvalue())
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNC_NAME)
        lam.update_function_configuration(FunctionName=FUNC_NAME, Environment=env, Role=lam_role)
        print(f"✅ Lambda {FUNC_NAME} 已更新")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        retry(lambda: lam.create_function(
            FunctionName=FUNC_NAME, Runtime="python3.12", Role=lam_role,
            Handler="lambda_function.lambda_handler", Code={"ZipFile": buf.getvalue()},
            Timeout=120, MemorySize=128, Environment=env,
            Description="FSx Lustre biweekly MW skip (idempotent, reads CSV from S3)"), "创建 Lambda")
        print(f"✅ Lambda {FUNC_NAME} 已创建")
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNC_NAME)
    # Scheduler 对 Lambda 是异步调用：函数执行报错由 Lambda 异步重试 2 次，耗尽后投递到同一个 DLQ
    retry(lambda: lam.put_function_event_invoke_config(
        FunctionName=FUNC_NAME, MaximumRetryAttempts=2, MaximumEventAgeInSeconds=3600,
        DestinationConfig={"OnFailure": {"Destination": q_arn}}), "配置 Lambda 失败目标")
    print(f"✅ Lambda 异步失败重试 2 次，耗尽后投递 {DLQ_NAME}")
    try:  # 并发=1，避免两次调用同时读改写同一个 FS
        lam.put_function_concurrency(FunctionName=FUNC_NAME, ReservedConcurrentExecutions=1)
    except ClientError as e:
        print(f"   ⚠️ 无法设置预留并发=1（{e.response['Error']['Code']}），不影响幂等性")

    # 5. 告警：Lambda 错误 / 死信队列有消息
    cw = s.client("cloudwatch")
    cw.put_metric_alarm(AlarmName="fsx-mw-lambda-errors", Namespace="AWS/Lambda", MetricName="Errors",
                        Dimensions=[{"Name": "FunctionName", "Value": FUNC_NAME}], Statistic="Sum",
                        Period=300, EvaluationPeriods=1, Threshold=1, ComparisonOperator="GreaterThanOrEqualToThreshold",
                        TreatMissingData="notBreaching", AlarmActions=[topic],
                        AlarmDescription="FSx MW scheduler Lambda failed")
    cw.put_metric_alarm(AlarmName="fsx-mw-dlq-not-empty", Namespace="AWS/SQS",
                        MetricName="ApproximateNumberOfMessagesVisible",
                        Dimensions=[{"Name": "QueueName", "Value": DLQ_NAME}], Statistic="Maximum",
                        Period=300, EvaluationPeriods=1, Threshold=1, ComparisonOperator="GreaterThanOrEqualToThreshold",
                        TreatMissingData="notBreaching", AlarmActions=[topic],
                        AlarmDescription="FSx MW schedule retries exhausted (DLQ); window may not be restored")
    print("✅ CloudWatch 告警: fsx-mw-lambda-errors / fsx-mw-dlq-not-empty -> SNS")

    # 6. Scheduler 计划
    sch = s.client("scheduler")
    try:
        sch.create_schedule_group(Name=GROUP)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise
    for r in rows:
        fs_id, mw = r["FileSystemId"].strip(), r["MaintenanceWindow"].strip()
        print(f"\n{'=' * 60}\n📁 {r.get('Name') or fs_id}（{fs_id}）原始维护窗口 {mw}（{human(mw)}）")
        for action, offset, desc in [("skip", -12, "跳过周把窗口改为 原始-24h"),
                                     ("restore", +12, "把窗口恢复为原始值")]:
            expr, when = cron_at(mw, offset)
            name = f"fsx-mw-{action}-{fs_id}"
            params = dict(
                Name=name, GroupName=GROUP, ScheduleExpression=expr, ScheduleExpressionTimezone="UTC",
                FlexibleTimeWindow={"Mode": "OFF"}, State="ENABLED",
                Description=f"{fs_id} {action}: weekly at MW{offset:+d}h",
                Target={"Arn": func_arn, "RoleArn": sch_role,
                        "Input": json.dumps({"action": action, "fs_id": fs_id}),
                        "RetryPolicy": {"MaximumRetryAttempts": 3, "MaximumEventAgeInSeconds": 3600},
                        "DeadLetterConfig": {"Arn": q_arn}})
            try:
                retry(lambda: sch.create_schedule(**params), f"创建计划 {name}")
                verb = "已创建"
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConflictException":
                    raise
                sch.update_schedule(**params)
                verb = "已更新"
            print(f"   ✅ {verb}计划 {name}: {expr} = 每周 {when}，{desc}")
    print(f"\n{'=' * 60}\n🎉 部署完成。跳过周从 {first} 所在周开始，之后每隔一周跳过一次。")
    print("   修改原始窗口：改 CSV 后重新 deploy（会更新 S3 CSV 和计划时间）。")


# ─── remove ────────────────────────────────────
def cmd_remove(a):
    sch = boto3.client("scheduler", region_name=a.region)
    ids = None if a.all else {r["FileSystemId"].strip() for r in read_csv(a.csv)}
    n = 0
    for page in sch.get_paginator("list_schedules").paginate(GroupName=GROUP):
        for it in page["Schedules"]:
            if ids is None or any(it["Name"].endswith(i) for i in ids):
                sch.delete_schedule(Name=it["Name"], GroupName=GROUP)
                print(f"   🗑️ 已删除计划 {it['Name']}")
                n += 1
    print(f"✅ 共删除 {n} 个计划（Lambda/角色/队列保留；如需彻底清理见 README）")


def main():
    p = argparse.ArgumentParser(description="FSx Lustre 维护窗口隔周调度器 v2")
    sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("list", help="列出 FSx Lustre 文件系统到 CSV")
    x.add_argument("--region", required=True)
    x.add_argument("--output", default="fsx_lustre_list.csv")
    x = sub.add_parser("deploy", help="按 CSV 部署 Lambda + Scheduler")
    x.add_argument("--region", required=True)
    x.add_argument("--csv", default="fsx_lustre_list.csv")
    x.add_argument("--bucket", required=True, help="存放 CSV 的 S3 桶（同 Region）")
    x.add_argument("--first-skip-week", help="第一个跳过周内任意一天 YYYY-MM-DD（UTC），默认本周")
    x.add_argument("--email", help="告警邮箱（可选）")
    x = sub.add_parser("remove", help="删除计划")
    x.add_argument("--region", required=True)
    x.add_argument("--csv", default="fsx_lustre_list.csv")
    x.add_argument("--all", action="store_true")
    a = p.parse_args()
    {"list": cmd_list, "deploy": cmd_deploy, "remove": cmd_remove}[a.cmd](a)


if __name__ == "__main__":
    main()
