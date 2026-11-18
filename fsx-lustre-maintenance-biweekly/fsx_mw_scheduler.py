#!/usr/bin/env python3
"""
FSx Lustre Maintenance Window Biweekly Scheduler
==================================================
Converts FSx Lustre weekly maintenance into biweekly by shifting the
maintenance window back and forth with two Lambda functions per file system.

Key design:
  - Lambda functions are IDEMPOTENT: they set the MW to a hard-coded absolute
    value (from CSV), not a relative shift. Safe to invoke multiple times.
  - EventBridge uses rate(14 days). Deploy triggers the first Skip invocation
    to align the cycle start.
  - Deploy must happen in the week AFTER a successful maintenance. See README.

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

import boto3
from botocore.exceptions import ClientError

LAMBDA_ROLE_NAME = "fsx-mw-lambda-role"
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


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
    """
    Set FSx Lustre maintenance window to a fixed target value.
    Idempotent: if MW is already at target, no API call is made.

    All values are hard-coded at deploy time from the CSV.
    """
    fs_id = "{fs_id}"
    target_mw = "{target_mw}"
    original_mw = "{original_mw}"
    region = "{region}"
    label = "{label}"

    fsx = boto3.client("fsx", region_name=region)

    resp = fsx.describe_file_systems(FileSystemIds=[fs_id])
    current_mw = resp["FileSystems"][0]["LustreConfiguration"]["WeeklyMaintenanceStartTime"]

    if current_mw == target_mw:
        msg = f"FSx {{fs_id}} [{{label}}]: MW is already {{target_mw}}, no change (idempotent)"
        print(msg)
        return {{"statusCode": 200, "body": msg, "changed": False, "currentMW": current_mw}}

    fsx.update_file_system(
        FileSystemId=fs_id,
        LustreConfiguration={{"WeeklyMaintenanceStartTime": target_mw}},
    )

    day_names = {{1:"Mon",2:"Tue",3:"Wed",4:"Thu",5:"Fri",6:"Sat",7:"Sun"}}
    def fmt(mw):
        d, h, m = int(mw.split(":")[0]), int(mw.split(":")[1]), int(mw.split(":")[2])
        return f"{{day_names[d]}} {{h:02d}}:{{m:02d}} UTC"

    msg = f"FSx {{fs_id}} [{{label}}]: MW changed from {{fmt(current_mw)}} to {{fmt(target_mw)}} (original={{original_mw}})"
    print(msg)
    return {{"statusCode": 200, "body": msg, "changed": True, "oldMW": current_mw, "newMW": target_mw}}
'''


def create_lambda_zip(fs_id: str, target_mw: str, original_mw: str,
                       region: str, label: str) -> bytes:
    code = LAMBDA_CODE_TEMPLATE.format(
        fs_id=fs_id, target_mw=target_mw, original_mw=original_mw,
        region=region, label=label
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", code)
    return buf.getvalue()


def ensure_lambda_role(session, account_id: str):
    iam = session.client("iam")
    role_arn = f"arn:aws:iam::{account_id}:role/{LAMBDA_ROLE_NAME}"

    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    })

    try:
        iam.get_role(RoleName=LAMBDA_ROLE_NAME)
        print(f"   IAM role {LAMBDA_ROLE_NAME} already exists")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            iam.create_role(
                RoleName=LAMBDA_ROLE_NAME,
                AssumeRolePolicyDocument=trust_policy,
                Description="Lambda role for FSx maintenance window scheduler",
            )
            print(f"   ✅ Created IAM role {LAMBDA_ROLE_NAME}")
            time.sleep(10)
        else:
            raise

    policy_doc = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudWatchLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": "arn:aws:logs:*:*:*",
            },
            {
                "Sid": "FSxDescribeUpdate",
                "Effect": "Allow",
                "Action": ["fsx:DescribeFileSystems", "fsx:UpdateFileSystem"],
                "Resource": "*",
            },
        ],
    })
    iam.put_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyName="fsx-mw-lambda-policy",
        PolicyDocument=policy_doc,
    )
    return role_arn


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
    lam = session.client("lambda")
    events = session.client("events")

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
            fire_time = human_readable_mw(shift_mw(original_mw, offset))
            zip_bytes = create_lambda_zip(
                fs_id, target_mw, original_mw, args.region, label
            )

            print(f"\n   Lambda [{label}]: {func_name}")
            print(f"     Target MW : {target_mw} ({human_readable_mw(target_mw)})")
            print(f"     Schedule  : rate(14 days), aligned to {fire_time}")
            print(f"     Idempotent: yes (absolute value, safe to re-invoke)")

            try:
                lam.create_function(
                    FunctionName=func_name,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler="lambda_function.lambda_handler",
                    Code={"ZipFile": zip_bytes},
                    Timeout=30,
                    MemorySize=128,
                    Description=f"{label}: MW→{target_mw} for {fs_id} | original={original_mw}",
                )
                print(f"     ✅ Lambda created")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceConflictException":
                    lam.update_function_code(FunctionName=func_name, ZipFile=zip_bytes)
                    print(f"     ⚠️  Lambda exists, code updated")
                else:
                    raise

            rule_name = f"{func_prefix}-{fs_id}"
            events.put_rule(
                Name=rule_name,
                ScheduleExpression="rate(14 days)",
                State="ENABLED",
                Description=f"{label} MW for {fs_id} at {fire_time} | original={original_mw}",
            )
            func_arn = f"arn:aws:lambda:{args.region}:{account_id}:function:{func_name}"
            events.put_targets(
                Rule=rule_name,
                Targets=[{"Id": f"target-{fs_id}", "Arn": func_arn}],
            )
            try:
                lam.add_permission(
                    FunctionName=func_name,
                    StatementId=f"EventBridge-{rule_name}",
                    Action="lambda:InvokeFunction",
                    Principal="events.amazonaws.com",
                    SourceArn=f"arn:aws:events:{args.region}:{account_id}:rule/{rule_name}",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceConflictException":
                    raise
            print(f"     ✅ EventBridge rule: {rule_name} (rate 14 days)")

        # Invoke Skip Lambda to start the first skip cycle
        skip_func = f"fsx-mw-skip-{fs_id}"
        print(f"\n   🚀 Waiting for {skip_func} to become Active...")
        for _wait in range(30):
            try:
                fn_state = lam.get_function(FunctionName=skip_func)["Configuration"]["State"]
            except Exception:
                fn_state = "Unknown"
            if fn_state == "Active":
                break
            time.sleep(2)
        print(f"     State: {fn_state}")
        print(f"   🚀 Invoking {skip_func} to align first skip cycle...")
        resp = lam.invoke(FunctionName=skip_func, InvocationType="RequestResponse")
        payload = json.loads(resp["Payload"].read())
        print(f"     Result: {payload.get('body', payload)}")

    print(f"\n{'='*60}")
    print("🎉 部署完成！")
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
