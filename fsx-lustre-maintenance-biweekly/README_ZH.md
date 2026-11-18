# FSx for Lustre 维护窗口隔周调度（v2）

[English](README.md)

FSx for Lustre 的维护窗口按周设置，没有"隔周"选项。本工具在**跳过周**把窗口临时挪到前一天（已过去的时间点），维护后再挪回原值，从而让补丁最多每两周落地一次。

> 官方说明：补丁"通常每几周一次"，不是每周都有；且必须**每 14 天内至少排一次窗口**，否则有补丁时 AWS 会强制维护。见 [Maintenance windows](https://docs.aws.amazon.com/fsx/latest/LustreGuide/maintenance-windows.html)。

## 工作原理

```
EventBridge Scheduler（cron，UTC，每周）
  skip    计划：原始窗口 −12h 触发 → 若是"跳过周"，窗口写为 原始 −24h
  restore 计划：原始窗口 +12h 触发 → 窗口写回 原始值（每周都执行，兜底）
                │
                ▼
     Lambda fsx-mw-scheduler（全部 FS 共用）
       每次从 S3 读取 CSV → 取该 FS 原始窗口 → 写绝对值
```

例：原始窗口 `3:02:00`（周三 02:00）

| 计划 | cron | 动作 |
|---|---|---|
| skip | `cron(0 14 ? * TUE *)` 周二 14:00 | 跳过周：改为 `2:02:00`（周二 02:00，已过去）→ 本周三不维护 |
| restore | `cron(0 14 ? * WED *)` 周三 14:00 | 改回 `3:02:00` |

## 相比 v1 的改进

| 问题（v1，实测确认） | v2 |
|---|---|
| `rate(14 days)` 锚定在规则创建时间，两条规则同时触发，跳不过维护，甚至窗口被挪偏 | 按 CSV 维护窗口算出 **cron**，Lambda 内按周数判断是否跳过周 |
| 读当前值 ±24h，重复触发会累积偏移 | **幂等**：每次读 CSV 原始窗口，写绝对值；已是目标值则不调用 API |
| 无错误处理 | 前置检查（AVAILABLE、无进行中管理操作）+ API 重试 + 写后校验；失败 → 重试 → **SQS 死信队列** → **CloudWatch 告警 → SNS** |
| 每 FS 两个 Lambda | 一个共用 Lambda，预留并发 = 1，避免并发读改写 |

## 使用

```bash
# 1. 列出 Lustre 文件系统，编辑 CSV 只保留需要隔周的
python3 fsx_mw_scheduler.py list --region us-east-2

# 2. 部署（CSV 上传到 S3；--first-skip-week 为第一个跳过周内任意一天，默认本周）
python3 fsx_mw_scheduler.py deploy --region us-east-2 --bucket <同 Region 的 S3 桶> \
    --csv fsx_lustre_list.csv --first-skip-week 2026-11-23 --email ops@example.com

# 3. 修改原始窗口：改 CSV 后重新 deploy（同时更新 S3 CSV 和 cron）

# 4. 删除计划
python3 fsx_mw_scheduler.py remove --region us-east-2 --all
```

CSV 格式（`MaintenanceWindow` 为原始窗口，`d:HH:MM`，d=1 周一 … 7 周日，UTC）：
```csv
Name,FileSystemId,MaintenanceWindow,MaintenanceWindowHuman,Timezone
mw-biweekly-test,fs-0eeabbe93f4cc61f0,3:02:00,周三 02:00 UTC,UTC
```

## 实测结果（2026-11-18，us-east-2，SCRATCH_2 1200 GiB，原始窗口 3:02:00）

测试脚本：`test_v2.sh`

| # | 场景 | 窗口变化 | 结果 |
|---|---|---|---|
| T1 | 跳过周 skip | `3:02` → `2:02` | ✅ |
| T2 | 重复 skip | `2:02` 不变（NO_CHANGE） | ✅ 幂等 |
| T3 | restore | `2:02` → `3:02` | ✅ |
| T4 | 重复 restore | `3:02` 不变（NO_CHANGE） | ✅ 幂等 |
| T5 | 非跳过周 skip（12-01） | 不变（NOT_SKIP_WEEK） | ✅ |
| T6 | 再下一周 skip（12-08） | `3:02` → `2:02` | ✅ 隔周正确；跨年 12-22 跳 / 12-29 维护 / 01-05 跳 |
| T7 | skip、restore 同时触发 | 串行执行，最终 `3:02` | ✅ 不漂移 |
| T8 | 手工改乱为 `6:10` 后 restore | `6:10` → `3:02` | ✅ 按 CSV 纠正 |
| T9 | 只改 S3 CSV 为 `5:18:30`，不重新部署 | restore 写入 `5:18:30` | ✅ 每次都读 CSV |
| T10 | CSV 中没有该 FS | 报错 `CSV 中找不到文件系统` | ✅ |
| T11 | 非法事件参数 | 报错 `事件参数非法` | ✅ |
| T12 | Scheduler 真实触发（一次性计划） | 正常 FS：`3:02` → `2:02`；不存在的 FS：执行 3 次（1 + 重试 2）后进入 DLQ（RetriesExhausted），告警 `fsx-mw-lambda-errors` 变 ALARM | ✅ |

> 发现：Scheduler 调 Lambda 是异步的，**函数报错不会进 Scheduler 的 DLQ**（那个只管投递失败），必须另外配置 Lambda 异步调用的 OnFailure 目标。v2 已两处都配到同一个 `fsx-mw-dlq`。

## 注意

- 两次实际维护间隔正好 14 天，**没有余量**；AWS 按"已排期"还是"实际执行"判断 14 天，文档未说明，**推测（未实测）**：只要始终有窗口排期即可。
- 真实补丁维护无法人为触发，"跳过后确实没有打补丁"未实测。
- 原始窗口在周一时，skip 在周日 14:00 触发，按"维护发生日"所在周判断，不会错周。

## 文件

| 文件 | 说明 |
|---|---|
| `fsx_mw_scheduler.py` | 部署脚本：`list` / `deploy` / `remove` |
| `lambda_function.py` | Lambda 代码 |
| `test_v2.sh` | 实测脚本 |
| `iam-policy.json` | 运行部署脚本所需权限 |
