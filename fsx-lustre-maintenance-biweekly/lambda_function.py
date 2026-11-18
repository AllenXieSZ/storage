"""
FSx Lustre 维护窗口隔周跳过 —— Lambda 运行时代码（所有文件系统共用一个函数）

事件格式（由 EventBridge Scheduler 传入）:
  {"action": "skip" | "restore", "fs_id": "fs-xxx"}
测试用可选字段:
  "force": true          跳过隔周判断，skip 一定执行
  "now": "2026-11-24T14:00:00Z"   模拟当前时间（用于验证隔周判断）

设计要点:
  1. 幂等：每次从 S3 上的 CSV 读取"原始维护窗口"，写入绝对值
     skip    -> 原始窗口 - 24h
     restore -> 原始窗口
     当前值已等于目标值时不调用 UpdateFileSystem，执行多少次结果都一样。
  2. 隔周：Scheduler 每周触发，skip 只在"跳过周"真正执行；restore 每周都执行（幂等，兜底恢复）。
     跳过周 = FIRST_SKIP_WEEK 所在周（周一~周日）起每隔一周；按天数计算，不用 ISO 周号，跨年不会连跳两周。
  3. 错误处理：前置检查 + 有限重试 + 写后校验；失败时抛异常，
     由 Scheduler 重试，重试耗尽进 SQS 死信队列，CloudWatch 告警通知。
"""
import csv
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

CSV_BUCKET = os.environ["CSV_BUCKET"]
CSV_KEY = os.environ["CSV_KEY"]
FIRST_SKIP_WEEK = os.environ["FIRST_SKIP_WEEK"]  # 第一个跳过周内任意一天 (UTC)，如 2026-11-23
REGION = os.environ.get("AWS_REGION", "us-east-2")

DAY_NAMES = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}

fsx = boto3.client("fsx", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)


class MWError(Exception):
    """需要重试 / 告警的错误"""


def human(mw):
    d, h, m = (int(x) for x in mw.split(":"))
    return f"{DAY_NAMES[d]} {h:02d}:{m:02d} UTC"


def shift(mw, hours):
    d, h, m = (int(x) for x in mw.split(":"))
    t = ((d - 1) * 24 + h + hours) % 168
    return f"{t // 24 + 1}:{t % 24:02d}:{m:02d}"


def read_original_mw(fs_id):
    """每次调用都重新读取 CSV，取该 FS 的原始维护窗口"""
    try:
        body = s3.get_object(Bucket=CSV_BUCKET, Key=CSV_KEY)["Body"].read().decode("utf-8-sig")
    except ClientError as e:
        raise MWError(f"读取 CSV 失败 s3://{CSV_BUCKET}/{CSV_KEY}: {e}")
    for row in csv.DictReader(io.StringIO(body)):
        if row.get("FileSystemId", "").strip() == fs_id:
            mw = row.get("MaintenanceWindow", "").strip()
            try:
                d, h, m = (int(x) for x in mw.split(":"))
                assert 1 <= d <= 7 and 0 <= h <= 23 and 0 <= m <= 59
            except Exception:
                raise MWError(f"CSV 中 {fs_id} 的维护窗口格式非法: '{mw}'（应为 d:HH:MM）")
            return mw
    raise MWError(f"CSV 中找不到文件系统 {fs_id}")


def is_skip_week(now):
    """skip 在维护窗口前 12h 触发，因此用 now+12h 所在日期判断是否为跳过周"""
    mw_date = (now + timedelta(hours=12)).date()
    first = datetime.strptime(FIRST_SKIP_WEEK, "%Y-%m-%d").date()
    first_monday = first - timedelta(days=first.weekday())
    mw_monday = mw_date - timedelta(days=mw_date.weekday())
    weeks = (mw_monday - first_monday).days // 7
    return weeks >= 0 and weeks % 2 == 0, mw_date


def describe(fs_id):
    try:
        fs = fsx.describe_file_systems(FileSystemIds=[fs_id])["FileSystems"][0]
    except ClientError as e:
        raise MWError(f"查询文件系统 {fs_id} 失败: {e}")
    return fs


def check_ready(fs):
    if fs["Lifecycle"] != "AVAILABLE":
        raise MWError(f"文件系统状态为 {fs['Lifecycle']}，不是 AVAILABLE，稍后重试")
    for a in fs.get("AdministrativeActions", []):
        if a.get("Status") in ("PENDING", "IN_PROGRESS"):
            raise MWError(f"文件系统有进行中的管理操作 {a.get('AdministrativeActionType')}，稍后重试")


def set_mw(fs_id, target, attempts=3):
    for i in range(1, attempts + 1):
        try:
            fsx.update_file_system(
                FileSystemId=fs_id,
                LustreConfiguration={"WeeklyMaintenanceStartTime": target},
            )
            break
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if i == attempts or code not in ("BadRequest", "ThrottlingException",
                                              "InternalServerError", "ServiceLimitExceeded"):
                raise MWError(f"UpdateFileSystem 失败（第 {i} 次）: {code} {e}")
            print(f"UpdateFileSystem 第 {i} 次失败 {code}，{5 * i}s 后重试")
            time.sleep(5 * i)
    # 写后校验
    for _ in range(6):
        cur = describe(fs_id)["LustreConfiguration"]["WeeklyMaintenanceStartTime"]
        if cur == target:
            return
        time.sleep(5)
    raise MWError(f"写后校验失败：期望 {target}，实际 {cur}")


def lambda_handler(event, context):
    action = event.get("action")
    fs_id = event.get("fs_id")
    if action not in ("skip", "restore") or not fs_id:
        raise MWError(f"事件参数非法: {json.dumps(event)}")

    now = datetime.fromisoformat(event["now"].replace("Z", "+00:00")) if event.get("now") \
        else datetime.now(timezone.utc)

    original = read_original_mw(fs_id)

    if action == "skip" and not event.get("force"):
        skip, mw_date = is_skip_week(now)
        if not skip:
            msg = f"{fs_id}: {mw_date} 不是跳过周，本周正常维护，不做修改（原始窗口 {human(original)}）"
            print(msg)
            return {"result": "NOT_SKIP_WEEK", "fs_id": fs_id, "message": msg}

    target = shift(original, -24) if action == "skip" else original

    fs = describe(fs_id)
    current = fs["LustreConfiguration"]["WeeklyMaintenanceStartTime"]

    if current == target:
        msg = f"{fs_id}: 当前窗口已是 {human(target)}，无需修改（幂等）"
        print(msg)
        return {"result": "NO_CHANGE", "fs_id": fs_id, "current": current, "message": msg}

    if action == "restore" and current not in (shift(original, -24),):
        # 不是我们挪的位置：仍恢复到 CSV 原始值，但打印告警便于排查
        print(f"⚠️ 告警: {fs_id} 当前窗口 {human(current)} 既不是原始值也不是 skip 值，将强制恢复为原始值")

    check_ready(fs)
    set_mw(fs_id, target)
    label = "跳过本周维护" if action == "skip" else "恢复原始维护窗口"
    msg = f"{fs_id}: {label}，窗口 {human(current)} -> {human(target)}"
    print(msg)
    return {"result": "UPDATED", "fs_id": fs_id, "old": current, "new": target, "message": msg}
