#!/usr/bin/env python3
"""
FSx Lustre Maintenance Window Biweekly Scheduler
==================================================
Converts FSx Lustre weekly maintenance into biweekly by shifting the
maintenance window back and forth with two Lambda functions per file system.

Architecture (per file system):
  - 2 Lambda functions (skip + restore), idempotent absolute-value MW set
  - 4 EventBridge Scheduler schedules:
    - skip-init:    at() one-shot, fires MW−12h, auto-deletes
    - restore-init: at() one-shot, fires MW+12h, auto-deletes
    - skip-cycle:   rate(14 days) starting from the SECOND skip fire time
    - restore-cycle:rate(14 days) starting from the SECOND restore fire time

  The skip and restore fire times are 24h apart, so they never collide.

Usage:
  python3 fsx_mw_scheduler.py list   --region us-east-2 [--output fsx_lustre_list.csv]
  python3 fsx_mw_scheduler.py deploy --region us-east-2 [--csv fsx_lustre_list.csv]
  python3 fsx_mw_scheduler.py clean  --region us-east-2 --fs-id fs-xxxx
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
    """Shift a MW string by ±hours, wrapping within a 7-day week (168h)."""
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
    """
    Next future UTC datetime for (MW + offset_hours), at least 5 min from now.
    """
    shifted = shift_mw(mw_str, offset_hours)
    day, hour, minute = parse_mw(shifted)
    py_weekday = FSX_TO_PY_DAY[day]

    now = datetime.now(timezone.utc)
    days_ahead = py_weekday - now.weekday()
    if days_ahead < 0:
        days_ahead += 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    # Must be at least 5 min in the future
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
        {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
         "Action": "sts:AssumeRole"}
    ]})
    try:
        iam.get_role(RoleName=LAMBDA_ROLE_NAME)
        print(f"   IAM role {LAMBDA_ROLE_NAME} already exists")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            iam.create_role(
                RoleName=LAMBDA_ROLE_NAME, AssumeRolePolicyDocument=trust,
                Description="Lambda role for FSx MW scheduler")
            print(f"   ✅ Created IAM role {LAMBDA_ROLE_NAME}")
            time.sleep(10)
        else:
            raise
    iam.put_role_policy(
        RoleName=LAMBDA_ROLE_NAME, PolicyName="fsx-mw-lambda-policy",
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
            {"Sid": "Logs", "Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream",
                        "logs:PutLogEvents"],
             "Resource": "arn:aws:logs:*:*:*"},
            {"Sid": "FSx", "Effect": "Allow",
             "Action": ["fsx:DescribeFileSystems", "fsx:UpdateFileSystem"],
             "Resource": "*"},
        ]}))
    return role_arn


def ensure_scheduler_role(session, account_id):
    """Role for EventBridge Scheduler to invoke Lambda."""
    iam = session.client("iam")
    role_arn = f"arn:aws:iam::{account_id}:role/{SCHEDULER_ROLE_NAME}"
    trust = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "scheduler.amazonaws.com"},
         "Action": "sts:AssumeRole"}
    ]})
    try:
        iam.get_role(RoleName=SCHEDULER_ROLE_NAME)
        print(f"   IAM role {SCHEDULER_ROLE_NAME} already exists")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            iam.create_role(
                RoleName=SCHEDULER_ROLE_NAME, AssumeRolePolicyDocument=trust,
                Description="EventBridge Scheduler role for FSx MW scheduler")
            print(f"   ✅ Created IAM role {SCHEDULER_ROLE_NAME}")
            time.sleep(10)
        else:
            raise
    iam.put_role_policy(
        RoleName=SCHEDULER_ROLE_NAME, PolicyName="fsx-mw-scheduler-invoke",
        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
            {"Sid": "InvokeLambda", "Effect": "Allow",
             "Action": "lambda:InvokeFunction",
             "Resource": f"arn:aws:lambda:*:{account_id}:function:fsx-mw-*"},
        ]}))
    return role_arn


def create_or_update_lambda(lam, func_name, role_arn, zip_bytes, description):
    try:
        lam.create_function(
            FunctionName=func_name, Runtime="python3.12", Role=role_arn,
            Handler="lambda_function.lambda_handler", Code={"ZipFile": zip_bytes},
            Timeout=30, MemorySize=128, Description=description)
        print(f"     ✅ Lambda created")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            lam.update_function_code(FunctionName=func_name, ZipFile=zip_bytes)
            print(f"     ⚠️  Lambda exists, code updated")
        else:
            raise


def create_or_update_schedule(scheduler, name, expression, func_arn,
                              scheduler_role_arn, desc, start_date=None,
                              auto_delete=False):
    """Create or update an EventBridge Scheduler schedule."""
    kwargs = dict(
        Name=name,
        ScheduleExpression=expression,
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        Target={
            "Arn": func_arn,
            "RoleArn": scheduler_role_arn,
        },
        Description=desc,
    )
    if start_date:
        kwargs["StartDate"] = start_date
    if auto_delete:
        kwargs["ActionAfterCompletion"] = "DELETE"

    try:
        scheduler.create_schedule(**kwargs)
        print(f"     ✅ Scheduler: {name} ({expression})"
              + (f" StartDate={start_date.isoformat()}" if start_date else "")
              + (" [auto-delete]" if auto_delete else ""))
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            scheduler.update_schedule(**kwargs)
            print(f"     ⚠️  Scheduler exists, updated: {name} ({expression})"
                  + (f" StartDate={start_date.isoformat()}" if start_date else ""))
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

        # Calculate fire times:
        #   skip  fires at MW − 12h (before the maintenance window)
        #   restore fires at MW + 12h (after the maintenance window)
        #   They are 24h apart, so they never collide.
        skip_first = next_occurrence_utc(original_mw, -12)
        restore_first = next_occurrence_utc(original_mw, +12)

        # The SECOND occurrence (for rate(14d) StartDate) is 14 days after first
        skip_second = skip_first + timedelta(days=14)
        restore_second = restore_first + timedelta(days=14)

        for label, func_prefix, target_mw, first_at, cycle_start in [
            ("skip", "fsx-mw-skip", skipped_mw, skip_first, skip_second),
            ("restore", "fsx-mw-restore", original_mw, restore_first, restore_second),
        ]:
            func_name = f"{func_prefix}-{fs_id}"
            func_arn = f"arn:aws:lambda:{args.region}:{account_id}:function:{func_name}"

            print(f"\n   Lambda [{label}]: {func_name}")
            print(f"     Target MW   : {target_mw} ({human_readable_mw(target_mw)})")
            print(f"     First fire  : {first_at.strftime('%Y-%m-%d %H:%M UTC (%a)')} (at() one-shot)")
            print(f"     Cycle start : {cycle_start.strftime('%Y-%m-%d %H:%M UTC (%a)')} (rate(14d) from here)")
            print(f"     Idempotent  : yes")

            # 1. Create/update Lambda
            create_or_update_lambda(
                lam, func_name, role_arn,
                create_lambda_zip(fs_id, target_mw, original_mw, args.region, label),
                f"{label}: MW→{target_mw} for {fs_id} | original={original_mw}"
            )

            # 2. Scheduler at() — first trigger (auto-deletes after fire)
            create_or_update_schedule(
                scheduler,
                name=f"{func_prefix}-init-{fs_id}",
                expression=f"at({first_at.strftime('%Y-%m-%dT%H:%M:%S')})",
                func_arn=func_arn,
                scheduler_role_arn=sched_role_arn,
                desc=f"First {label} for {fs_id} at {first_at.isoformat()}",
                auto_delete=True,
            )

            # 3. Scheduler rate(14 days) — ongoing, with StartDate = second occurrence
            #    This ensures the recurring trigger starts AFTER the init at() has fired,
            #    and is properly aligned to MW±12h (not deploy time).
            create_or_update_schedule(
                scheduler,
                name=f"{func_prefix}-cycle-{fs_id}",
                expression="rate(14 days)",
                func_arn=func_arn,
                scheduler_role_arn=sched_role_arn,
                desc=f"Recurring {label} for {fs_id} every 14d from {cycle_start.isoformat()} | original={original_mw}",
                start_date=cycle_start,
            )

    print(f"\n{'='*60}")
    print("🎉 部署完成！")
    print()
    print("📌 调度说明：")
    print("   1. at() 一次性规则：精确在下一个 MW±12h 时间点触发首次 skip/restore，触发后自动删除")
    print("   2. rate(14 days) 周期规则：从第二次 skip/restore 时间点开始，每 14 天触发")
    print("      skip 和 restore 的 StartDate 相差 24h，永远不会同时触发")
    print("   3. Lambda 是幂等的，万一重叠触发也无副作用")
    print()
    print("⚠️  重要：请确保在「上周刚完成 maintenance 之后」部署，详见 README_ZH.md。")


# ─── Feature 3: Clean up resources for one FS ─

def cmd_clean(args):
    session = boto3.Session(region_name=args.region)
    fs_id = args.fs_id
    lam = session.client("lambda")
    scheduler = session.client("scheduler")

    print(f"🧹 Cleaning up resources for {fs_id} in {args.region}")

    for prefix in ["fsx-mw-skip", "fsx-mw-restore"]:
        # Delete Lambda
        func_name = f"{prefix}-{fs_id}"
        try:
            lam.delete_function(FunctionName=func_name)
            print(f"   ✅ Deleted Lambda: {func_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"   ⏭️  Lambda not found: {func_name}")
            else:
                print(f"   ❌ Error deleting Lambda {func_name}: {e}")

        # Delete Scheduler schedules (init + cycle)
        for suffix in ["init", "cycle"]:
            sched_name = f"{prefix}-{suffix}-{fs_id}"
            try:
                scheduler.delete_schedule(Name=sched_name)
                print(f"   ✅ Deleted Scheduler: {sched_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    print(f"   ⏭️  Scheduler not found: {sched_name}")
                else:
                    print(f"   ❌ Error deleting Scheduler {sched_name}: {e}")

    # Also clean up legacy EventBridge Rules (from old version that used Rules rate(14d))
    events = session.client("events")
    for prefix in ["fsx-mw-skip", "fsx-mw-restore"]:
        rule_name = f"{prefix}-{fs_id}"
        try:
            # Old version used two different target ID formats; try both
            for target_id in [f"target-{fs_id}", f"target-{rule_name}"]:
                try:
                    events.remove_targets(Rule=rule_name, Ids=[target_id])
                except ClientError:
                    pass
            events.delete_rule(Name=rule_name)
            print(f"   ✅ Deleted legacy EB Rule: {rule_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                pass  # no legacy rule, fine
            else:
                print(f"   ❌ Error deleting legacy rule {rule_name}: {e}")

    print(f"\n✅ Cleanup complete for {fs_id}")


def main():
    parser = argparse.ArgumentParser(
        description="FSx Lustre Maintenance Window Biweekly Scheduler"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List FSx Lustre → CSV")
    p_list.add_argument("--region", required=True)
    p_list.add_argument("--output", default="fsx_lustre_list.csv")

    p_deploy = sub.add_parser("deploy", help="Deploy Lambda + Scheduler")
    p_deploy.add_argument("--region", required=True)
    p_deploy.add_argument("--csv", default="fsx_lustre_list.csv")

    p_clean = sub.add_parser("clean", help="Clean up all resources for one FS")
    p_clean.add_argument("--region", required=True)
    p_clean.add_argument("--fs-id", required=True, help="File system ID to clean up")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "deploy":
        cmd_deploy(args)
    elif args.command == "clean":
        cmd_clean(args)


if __name__ == "__main__":
    main()
