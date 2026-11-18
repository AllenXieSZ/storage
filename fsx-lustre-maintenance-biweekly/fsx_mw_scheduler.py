#!/usr/bin/env python3
"""
FSx Lustre Maintenance Window Biweekly Scheduler
==================================================
Converts FSx Lustre weekly maintenance into biweekly by shifting the
maintenance window back and forth with two Lambda functions per file system.

Usage:
  python3 fsx_mw_scheduler.py list   --region us-east-2 [--output fsx_lustre_list.csv]
  python3 fsx_mw_scheduler.py deploy --region us-east-2 [--csv fsx_lustre_list.csv]

Prerequisites:
  - IAM user with the policy from iam-policy.json attached
  - AWS credentials configured (env vars or ~/.aws/credentials)
  - Python 3.9+ with boto3 installed
"""

import argparse
import csv
import io
import json
import os
import sys
import time
import zipfile

import boto3
from botocore.exceptions import ClientError

LAMBDA_ROLE_NAME = "fsx-mw-lambda-role"

# FSx uses d=1(Mon)..7(Sun), all UTC
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


# ─── Helpers ──────────────────────────────────

def get_account_id(session) -> str:
    """Get AWS account ID from STS."""
    return session.client("sts").get_caller_identity()["Account"]


def parse_mw(mw_str: str) -> tuple:
    """Parse 'd:HH:MM' -> (day_int, hour_int, minute_int)."""
    parts = mw_str.split(":")
    return int(parts[0]), int(parts[1]), int(parts[2])


def format_mw(day: int, hour: int, minute: int) -> str:
    """Format to 'd:HH:MM'."""
    return f"{day}:{hour:02d}:{minute:02d}"


def shift_mw(mw_str: str, hours: int) -> str:
    """Shift a maintenance window by +/- hours (wraps within 7-day week)."""
    day, hour, minute = parse_mw(mw_str)
    total_hours = (day - 1) * 24 + hour + hours
    total_hours = total_hours % 168  # 7 days * 24 hours
    if total_hours < 0:
        total_hours += 168
    new_day = total_hours // 24 + 1
    new_hour = total_hours % 24
    return format_mw(new_day, new_hour, minute)


def human_readable_mw(mw_str: str) -> str:
    """Convert '3:02:00' to 'Wed 02:00 UTC'."""
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


# ─── Lambda code template ────────────────────

LAMBDA_CODE_TEMPLATE = '''
import json
import boto3

def lambda_handler(event, context):
    """
    Shift FSx Lustre maintenance window by SHIFT_HOURS.
    FS_ID, SHIFT_HOURS, REGION are baked in at deploy time.
    """
    fs_id = "{fs_id}"
    shift_hours = {shift_hours}
    region = "{region}"

    fsx = boto3.client("fsx", region_name=region)

    # Get current maintenance window
    resp = fsx.describe_file_systems(FileSystemIds=[fs_id])
    current_mw = resp["FileSystems"][0]["LustreConfiguration"]["WeeklyMaintenanceStartTime"]

    # Parse and shift (7-day wrap)
    parts = current_mw.split(":")
    day, hour, minute = int(parts[0]), int(parts[1]), int(parts[2])
    total_hours = (day - 1) * 24 + hour + shift_hours
    total_hours = total_hours % 168
    if total_hours < 0:
        total_hours += 168
    new_day = total_hours // 24 + 1
    new_hour = total_hours % 24
    new_mw = f"{{new_day}}:{{new_hour:02d}}:{{minute:02d}}"

    fsx.update_file_system(
        FileSystemId=fs_id,
        LustreConfiguration={{"WeeklyMaintenanceStartTime": new_mw}},
    )

    day_names = {{1:"Mon",2:"Tue",3:"Wed",4:"Thu",5:"Fri",6:"Sat",7:"Sun"}}
    msg = (
        f"FSx {{fs_id}}: shifted MW from {{day_names[day]}} {{hour:02d}}:{{minute:02d}} UTC "
        f"to {{day_names[new_day]}} {{new_hour:02d}}:{{minute:02d}} UTC ({{shift_hours:+d}}h)"
    )
    print(msg)
    return {{"statusCode": 200, "body": msg, "oldMW": current_mw, "newMW": new_mw}}
'''


def create_lambda_zip(fs_id: str, shift_hours: int, region: str) -> bytes:
    """Create in-memory zip with lambda_function.py."""
    code = LAMBDA_CODE_TEMPLATE.format(
        fs_id=fs_id, shift_hours=shift_hours, region=region
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", code)
    return buf.getvalue()


def ensure_lambda_role(session, account_id: str):
    """Create the Lambda execution role with minimal permissions."""
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
            time.sleep(10)  # wait for IAM propagation
        else:
            raise

    # Minimal policy: CloudWatch Logs + FSx describe/update only
    policy_doc = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudWatchLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "arn:aws:logs:*:*:*",
            },
            {
                "Sid": "FSxDescribeUpdate",
                "Effect": "Allow",
                "Action": [
                    "fsx:DescribeFileSystems",
                    "fsx:UpdateFileSystem",
                ],
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


def compute_schedule_info(mw_str: str, offset_hours: int) -> dict:
    """Compute the target fire time for an EventBridge schedule."""
    day, hour, minute = parse_mw(mw_str)
    total_hours = (day - 1) * 24 + hour + offset_hours
    total_hours = total_hours % 168
    if total_hours < 0:
        total_hours += 168
    fire_day = total_hours // 24 + 1
    fire_hour = total_hours % 24

    eb_day_map = {
        1: "MON", 2: "TUE", 3: "WED", 4: "THU",
        5: "FRI", 6: "SAT", 7: "SUN",
    }
    return {
        "rate_expr": "rate(14 days)",
        "target_time": f"{eb_day_map[fire_day]} {fire_hour:02d}:{minute:02d} UTC",
    }


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
        mw = fs["MaintenanceWindow"]
        name = fs["Name"] or fs_id
        print(f"\n{'='*60}")
        print(f"📁 {name} ({fs_id})  MW={mw} ({human_readable_mw(mw)})")

        for label, func_prefix, offset, shift in [
            ("A (skip)", "fsx-mw-skip", -12, -24),
            ("B (restore)", "fsx-mw-restore", +12, +24),
        ]:
            func_name = f"{func_prefix}-{fs_id}"
            sched = compute_schedule_info(mw, offset)
            zip_bytes = create_lambda_zip(fs_id, shift, args.region)

            print(f"   Lambda {label}: {func_name}")
            print(f"     Fires at: {sched['target_time']} ({abs(offset)}h {'before' if offset < 0 else 'after'} MW)")
            print(f"     Action: shift MW {shift:+d}h")

            # Create or update Lambda
            try:
                lam.create_function(
                    FunctionName=func_name,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler="lambda_function.lambda_handler",
                    Code={"ZipFile": zip_bytes},
                    Timeout=30,
                    MemorySize=128,
                    Description=f"{'Skip' if shift < 0 else 'Restore'} MW for {fs_id} ({sched['target_time']}, {shift:+d}h)",
                )
                print(f"     ✅ Lambda created")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceConflictException":
                    lam.update_function_code(FunctionName=func_name, ZipFile=zip_bytes)
                    print(f"     ⚠️  Lambda exists, updated code")
                else:
                    raise

            # EventBridge rule
            rule_name = f"{func_prefix}-{fs_id}"
            events.put_rule(
                Name=rule_name,
                ScheduleExpression=sched["rate_expr"],
                State="ENABLED",
                Description=f"Biweekly {func_prefix.split('-')[-1]} MW for {fs_id} at {sched['target_time']}",
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
            print(f"     ✅ EventBridge rule: {rule_name} ({sched['rate_expr']})")

    print(f"\n{'='*60}")
    print("🎉 Deployment complete!")


# ─── Main ─────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="FSx Lustre Maintenance Window Biweekly Scheduler"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List FSx Lustre file systems → CSV")
    p_list.add_argument("--region", required=True)
    p_list.add_argument("--output", default="fsx_lustre_list.csv")

    p_deploy = sub.add_parser("deploy", help="Deploy Lambda + EventBridge from CSV")
    p_deploy.add_argument("--region", required=True)
    p_deploy.add_argument("--csv", default="fsx_lustre_list.csv")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "deploy":
        cmd_deploy(args)


if __name__ == "__main__":
    main()
