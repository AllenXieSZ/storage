#!/usr/bin/env python3
"""
FSx Lustre Maintenance Window Biweekly Scheduler
==================================================
Converts FSx Lustre weekly maintenance into biweekly by shifting the
maintenance window back and forth with two Lambda functions per file system.

Key design:
  - Lambda functions are IDEMPOTENT (absolute value, not relative shift).
  - First trigger uses EventBridge Scheduler at() for precise UTC alignment.
  - Subsequent triggers use EventBridge Rules rate(14 days).
  - All times are UTC (same as FSx MW timezone).

Usage:
  python3 fsx_mw_scheduler.py list   --region us-east-2 [--output fsx_lustre_list.csv]
  python3 fsx_mw_scheduler.py deploy --region us-east-2 [--csv fsx_lustre_list.csv]
"""

import argparse
import csv
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

LAMBDA_ROLE_NAME = "fsx-mw-lambda-role"
SCHEDULER_ROLE_NAME = "fsx-mw-scheduler-role"
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
FSX_TO_PY_DAY = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}  # FSx Mon=1 → Python Mon=0


# ─── Helpers ──────────────────────────────────

def get_account_id(session) -> str:
    return session.client("sts").get_caller_identity()["Account"]


def parse_mw(mw_str: str) -> tuple:
    parts = mw_str.split(":")
    return int(parts[0]), int(parts[1]), int(parts[2])


def format_mw(day: int, hour: int, minute: int) -> str:
    return f"{day}:{hour:02d}:{minute:02d}"


def shift_mw(mw_str: str, hours: int) -> str:
    day, hour, minute = parse_mw(mw_str)
    total_hours = (day - 1) * 24 + hour + hours
    total_hours = total_hours % 168
    if total_hours < 0:
        total_hours += 168
    new_day = total_hours // 24 + 1
    new_hour = total_hours % 24
    return format_mw(new_day, new_hour, minute)


def human_readable_mw(mw_str: str) -> str:
    day, hour, minute = parse_mw(mw_str)
    return f"{DAY_NAMES[day]} {hour:02d}:{minute:02d} UTC"


def next_occurrence_utc(mw_str: str, offset_hours: int) -> datetime:
    """Next future UTC datetime for (MW + offset_hours), at least 5 min from now."""
    shifted = shift_mw(mw_str, offset_hours)
    day, hour, minute = parse_mw(shifted)
    py_weekday = FSX_TO_PY_DAY[day]

    now = datetime.now(timezone.utc)
    days_ahead = py_weekday - now.weekday()
    if days_ahead < 0:
        days_ahead += 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    if candidate <= now + timedelta(minutes=5):
        candidate += timedelta(weeks=1)
    return candidate


# ─── Feature 1: List FSx Lustre → CSV ────────

def cmd_list(args):
    session = boto3.Session(region_name=args.region)
    fsx = session.client("fsx")

    filesystems = []
    paginator = fsx.get_paginator("describe_file_systems")
    for page in paginator.paginate():
        for fs in page["FileSystems"]:
            if fs["FileSystemType"] != "LUSTRE":
                continue
            fs_id = fs["FileSystemId"]
            name = ""
            for tag in fs.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
                    break
            mw = fs.get("LustreConfiguration", {}).get(
                "WeeklyMaintenanceStartTime", ""
            )
            filesystems.append({
                "Name": name,
                "FileSystemId": fs_id,
                "MaintenanceWindow": mw,
                "MaintenanceWindowHuman": human_readable_mw(mw) if mw else "",
                "Timezone": "UTC",
            })

    output = args.output
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Name", "FileSystemId", "MaintenanceWindow",
                "MaintenanceWindowHuman", "Timezone",
            ],
        )
        writer.writeheader()
        writer.writerows(filesystems)

    print(f"✅ Wrote {len(filesystems)} FSx Lustre file systems to {output}")
    for fs in filesystems:
        print(
            f"   {fs['FileSystemId']}  {fs['Name']:<30s}  "
            f"MW={fs['MaintenanceWindow']} ({fs['MaintenanceWindowHuman']})"
        )


# ─── Lambda code template (idempotent) ───────

LAMBDA_CODE_TEMPLATE = '''
import json
import boto3

def lambda_handler(event, context):
    """Set FSx Lustre MW to a fixed target. Idempotent."""
    fs_id = "{fs_id}"
    target_mw = "{target_mw}"
    original_mw = "{original_mw}"
    region = "{region}"
    label = "{label}"

    fsx = boto3.client("fsx", region_name=region)
    resp = fsx.describe_file_systems(FileSystemIds=[fs_id])
    current_mw = resp["FileSystems"][0]["LustreConfiguration"]["WeeklyMaintenanceStartTime"]

    day_names = {{1:"Mon",2:"Tue",3:"Wed",4:"Thu",5:"Fri",6:"Sat",7:"Sun"}}
    def fmt(mw):
        d, h, m = int(mw.split(":")[0]), int(mw.split(":")[1]), int(mw.split(":")[2])
        return f"{{day_names[d]}} {{h:02d}}:{{m:02d}} UTC"

    if current_mw == target_mw:
        msg = f"FSx {{fs_id}} [{{label}}]: MW is already {{fmt(target_mw)}}, no change (idempotent)"
        print(msg)
        return {{"statusCode": 200, "body": msg, "changed": False}}

    fsx.update_file_system(
        FileSystemId=fs_id,
        LustreConfiguration={{"WeeklyMaintenanceStartTime": target_mw}},
    )
    msg = f"FSx {{fs_id}} [{{label}}]: MW changed from {{fmt(current_mw)}} to {{fmt(target_mw)}} (original={{original_mw}})"
    print(msg)
    return {{"statusCode": 200, "body": msg, "changed": True}}
'''


def create_lambda_zip(fs_id, target_mw, original_mw, region, label):
    code = LAMBDA_CODE_TEMPLATE.format(
        fs_id=fs_id, target_mw=target_mw, original_mw=original_mw,
        region=region, label=label
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", code)
    return buf.getvalue()


def ensure_lambda_role(session, account_id):
    iam = session.client("iam")
    role_arn = f"arn:aws:iam::{account_id}:role/{LAMBDA_ROLE_NAME}"
    trust = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}
    ]})
    try:
        iam.get_role(RoleName=LAMBDA_ROLE_NAME)
        print(f"   IAM role {LAMBDA_ROLE_NAME} already exists")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            iam.create_role(RoleName=LAMBDA_ROLE_NAME, AssumeRolePolicyDocument=trust,
                           Description="Lambda role for FSx MW scheduler")
            print(f"   ✅ Created IAM role {LAMBDA_ROLE_NAME}")
            time.sleep(10)
        else:
            raise
    iam.put_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyName="fsx-mw-lambda-policy",
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
            {"Sid": "Logs", "Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": "arn:aws:logs:*:*:*"},
            {"Sid": "FSx", "Effect": "Allow",
             "Action": ["fsx:DescribeFileSystems", "fsx:UpdateFileSystem"], "Resource": "*"},
        ]}))
    return role_arn


def ensure_scheduler_role(session, account_id):
    """Role for EventBridge Scheduler to invoke Lambda."""
    iam = session.client("iam")
    role_arn = f"arn:aws:iam::{account_id}:role/{SCHEDULER_ROLE_NAME}"
    trust = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "scheduler.amazonaws.com"}, "Action": "sts:AssumeRole"}
    ]})
    try:
        iam.get_role(RoleName=SCHEDULER_ROLE_NAME)
        print(f"   IAM role {SCHEDULER_ROLE_NAME} already exists")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            iam.create_role(RoleName=SCHEDULER_ROLE_NAME, AssumeRolePolicyDocument=trust,
                           Description="EventBridge Scheduler role for FSx MW scheduler")
            print(f"   ✅ Created IAM role {SCHEDULER_ROLE_NAME}")
            time.sleep(10)
        else:
            raise
    iam.put_role_policy(RoleName=SCHEDULER_ROLE_NAME, PolicyName="fsx-mw-scheduler-invoke",
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
            {"Sid": "InvokeLambda", "Effect": "Allow", "Action": "lambda:InvokeFunction",
             "Resource": f"arn:aws:lambda:*:{account_id}:function:fsx-mw-*"},
        ]}))
    return role_arn


def create_or_update_lambda(lam, func_name, role_arn, zip_bytes, description):
    try:
        lam.create_function(FunctionName=func_name, Runtime="python3.12", Role=role_arn,
            Handler="lambda_function.lambda_handler", Code={"ZipFile": zip_bytes},
            Timeout=30, MemorySize=128, Description=description)
        print(f"     ✅ Lambda created")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            lam.update_function_code(FunctionName=func_name, ZipFile=zip_bytes)
            print(f"     ⚠️  Lambda exists, code updated")
        else:
            raise


def setup_rate_rule(events, lam, rule_name, func_name, func_arn, account_id, region, desc):
    """EventBridge Rules rate(14 days) for ongoing triggers."""
    events.put_rule(Name=rule_name, ScheduleExpression="rate(14 days)",
                    State="ENABLED", Description=desc)
    events.put_targets(Rule=rule_name, Targets=[{"Id": f"target-{rule_name}", "Arn": func_arn}])
    try:
        lam.add_permission(FunctionName=func_name, StatementId=f"EB-{rule_name}",
            Action="lambda:InvokeFunction", Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:{region}:{account_id}:rule/{rule_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise


def setup_scheduler_at(scheduler, sched_name, at_time, func_arn, scheduler_role_arn, desc):
    """EventBridge Scheduler one-shot at() for first trigger alignment."""
    at_expr = f"at({at_time.strftime('%Y-%m-%dT%H:%M:%S')})"
    try:
        scheduler.create_schedule(
            Name=sched_name,
            ScheduleExpression=at_expr,
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": func_arn,
                "RoleArn": scheduler_role_arn,
            },
            Description=desc,
            ActionAfterCompletion="DELETE",  # auto-delete after firing
        )
        print(f"     ✅ Scheduler one-shot: {sched_name} ({at_expr}) [auto-delete after fire]")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            scheduler.update_schedule(
                Name=sched_name,
                ScheduleExpression=at_expr,
                ScheduleExpressionTimezone="UTC",
                FlexibleTimeWindow={"Mode": "OFF"},
                Target={
                    "Arn": func_arn,
                    "RoleArn": scheduler_role_arn,
                },
                Description=desc,
                ActionAfterCompletion="DELETE",
            )
            print(f"     ⚠️  Scheduler exists, updated: {sched_name} ({at_expr})")
        else:
            raise


# ─── Feature 2: Deploy Lambda + EventBridge ──

def cmd_deploy(args):
    session = boto3.Session(region_name=args.region)
    account_id = get_account_id(session)

    with open(args.csv, "r") as f:
        filesystems = list(csv.DictReader(f))

    if not filesystems:
        print("❌ No file systems found in CSV")
        return

    print(f"📋 Read {len(filesystems)} file systems from {args.csv}")
    role_arn = ensure_lambda_role(session, account_id)
    sched_role_arn = ensure_scheduler_role(session, account_id)
    lam = session.client("lambda")
    events = session.client("events")
    scheduler = session.client("scheduler")

    for fs in filesystems:
        fs_id = fs["FileSystemId"]
        original_mw = fs["MaintenanceWindow"]
        name = fs["Name"] or fs_id
        skipped_mw = shift_mw(original_mw, -24)

        print(f"\n{'='*60}")
        print(f"📁 {name} ({fs_id})")
        print(f"   Original MW : {original_mw} ({human_readable_mw(original_mw)})")
        print(f"   Skipped MW  : {skipped_mw} ({human_readable_mw(skipped_mw)})")

        for label, func_prefix, target_mw, offset in [
            ("skip",    "fsx-mw-skip",    skipped_mw,  -12),
            ("restore", "fsx-mw-restore", original_mw, +12),
        ]:
            func_name = f"{func_prefix}-{fs_id}"
            func_arn = f"arn:aws:lambda:{args.region}:{account_id}:function:{func_name}"
            fire_time = human_readable_mw(shift_mw(original_mw, offset))
            first_at = next_occurrence_utc(original_mw, offset)

            print(f"\n   Lambda [{label}]: {func_name}")
            print(f"     Target MW  : {target_mw} ({human_readable_mw(target_mw)})")
            print(f"     Weekly at  : {fire_time} (MW {'+' if offset > 0 else ''}{offset}h)")
            print(f"     First fire : {first_at.strftime('%Y-%m-%d %H:%M UTC (%a)')}")
            print(f"     Then       : rate(14 days) from deploy time")
            print(f"     Idempotent : yes")

            # Create Lambda
            create_or_update_lambda(
                lam, func_name, role_arn,
                create_lambda_zip(fs_id, target_mw, original_mw, args.region, label),
                f"{label}: MW→{target_mw} for {fs_id} | original={original_mw}"
            )

            # EventBridge Scheduler at() — first trigger (auto-deletes after fire)
            setup_scheduler_at(
                scheduler, f"{func_prefix}-init-{fs_id}", first_at, func_arn, sched_role_arn,
                f"First {label} for {fs_id} at {first_at.isoformat()}"
            )

            # EventBridge Rules rate(14 days) — ongoing
            setup_rate_rule(
                events, lam, func_name, func_name, func_arn,
                account_id, args.region,
                f"Recurring {label} for {fs_id} every 14 days | original={original_mw}"
            )
            print(f"     ✅ EventBridge rate(14 days): {func_name}")

    print(f"\n{'='*60}")
    print("🎉 部署完成！")
    print()
    print("📌 调度说明：")
    print("   1. Scheduler at() 规则：精确在下一个 MW±12h 时间点触发首次 skip/restore")
    print("      触发后自动删除（ActionAfterCompletion=DELETE）")
    print("   2. EventBridge rate(14 days) 规则：从部署时间起每 14 天触发后续周期")
    print("   3. Lambda 是幂等的，重叠触发无副作用")
    print()
    print("⚠️  重要：请确保在【上周刚完成 maintenance 之后】部署。")
    print("   详见 README_ZH.md「部署时机」章节。")


def main():
    parser = argparse.ArgumentParser(
        description="FSx Lustre Maintenance Window Biweekly Scheduler"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="List FSx Lustre → CSV")
    p_list.add_argument("--region", required=True)
    p_list.add_argument("--output", default="fsx_lustre_list.csv")
    p_deploy = sub.add_parser("deploy", help="Deploy Lambda + EventBridge")
    p_deploy.add_argument("--region", required=True)
    p_deploy.add_argument("--csv", default="fsx_lustre_list.csv")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "deploy":
        cmd_deploy(args)


if __name__ == "__main__":
    main()
