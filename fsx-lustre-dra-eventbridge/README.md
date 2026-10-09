# FSx for Lustre 双向 DRA：用 EventBridge 获取文件变更事件

在 Lustre 上**新建 / 修改 / 删除**文件后，经 DRA 自动导出同步到 S3，S3 会发出事件。
本文介绍如何在**双向（自动导入 + 自动导出）DRA** 关联的 S3 bucket 上开启 EventBridge，接收这些事件。

## 1. 测试环境

| 项目 | 配置 |
|---|---|
| 区域 | us-east-2 |
| FSx for Lustre | PERSISTENT_2，1200 GiB，Lustre 2.15 |
| DRA | `/bidir` ↔ `s3://<bucket>/bidir/`，自动导入、自动导出均为 NEW / CHANGED / DELETED |
| S3 bucket | Versioning = Enabled |
| 客户端 | AL2023，lustre-client 2.15.6，挂载点 `/mnt/bidir` |
| 事件接收 | EventBridge 规则 → SQS |

## 2. 配置步骤

### 为什么用 EventBridge，而不是普通 S3 Event Notification
双向 DRA 的 bucket 上**已有一条系统自动创建的通知配置**（Id 为 `FSx`，请勿修改或删除）。
同一个 bucket 不允许再添加订阅相同事件类型的 SNS/SQS/Lambda 通知，否则报错：

```
Configurations overlap. Configurations on the same bucket cannot share a common event type.
```

EventBridge 不受此限制，开启后与已有配置互不影响。

### 步骤 1：在 bucket 上开启 EventBridge（保留已有配置）

`put-bucket-notification-configuration` 是**整体覆盖**，必须先读出现有配置，追加 `EventBridgeConfiguration` 后再写回。

```bash
B=<bucket>
R=us-east-2

aws s3api get-bucket-notification-configuration --bucket $B --region $R > cur.json

python3 - <<'PY'
import json
c = json.load(open('cur.json'))
c['EventBridgeConfiguration'] = {}
json.dump(c, open('new.json', 'w'), indent=2)
PY

aws s3api put-bucket-notification-configuration --bucket $B --region $R \
  --notification-configuration file://new.json

# 确认：原有的 TopicConfigurations(Id=FSx) 还在，多了 EventBridgeConfiguration
aws s3api get-bucket-notification-configuration --bucket $B --region $R
```

开启后的配置：
```json
{
  "TopicConfigurations": [
    {
      "Id": "FSx",
      "TopicArn": "arn:aws:sns:us-east-2:<...>:auto-import-<...>",
      "Events": ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
    }
  ],
  "EventBridgeConfiguration": {}
}
```

### 步骤 2：创建 SQS 队列（事件接收目标，可换成 Lambda / CloudWatch Logs）

```bash
Q_URL=$(aws sqs create-queue --queue-name lustre-file-events --region $R --query QueueUrl --output text)
Q_ARN=$(aws sqs get-queue-attributes --queue-url $Q_URL --attribute-names QueueArn \
        --region $R --query Attributes.QueueArn --output text)
```

### 步骤 3：创建 EventBridge 规则

只要删除事件，可在 pattern 中加 `"detail-type": ["Object Deleted"]`；下面示例接收新建和删除。

```bash
RULE_ARN=$(aws events put-rule --name lustre-file-events --region $R \
  --event-pattern '{
    "source": ["aws.s3"],
    "detail-type": ["Object Created", "Object Deleted"],
    "detail": {
      "bucket": { "name": ["'$B'"] },
      "object": { "key": [{ "prefix": "bidir/" }] }
    }
  }' --query RuleArn --output text)
```

### 步骤 4：允许 EventBridge 写入 SQS，并绑定目标

```bash
cat > qpolicy.json <<EOF2
{"Policy":"{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"events.amazonaws.com\"},\"Action\":\"sqs:SendMessage\",\"Resource\":\"$Q_ARN\",\"Condition\":{\"ArnEquals\":{\"aws:SourceArn\":\"$RULE_ARN\"}}}]}"}
EOF2
aws sqs set-queue-attributes --queue-url $Q_URL --region $R --attributes file://qpolicy.json

aws events put-targets --rule lustre-file-events --region $R --targets "Id=sqs,Arn=$Q_ARN"
```

### 步骤 5：测试

```bash
# Lustre 客户端
mkdir -p /mnt/bidir/bidir/evt
echo "hello" > /mnt/bidir/bidir/evt/evtfile.txt   # 新建
cat /mnt/bidir/bidir/evt/evtfile.txt              # 读取
rm /mnt/bidir/bidir/evt/evtfile.txt               # 删除

# 接收事件
aws sqs receive-message --queue-url $Q_URL --region $R --max-number-of-messages 10 --wait-time-seconds 10
```

## 3. 测试结果

| Lustre 操作 | 事件 | 对象 | 延迟 |
|---|---|---|---|
| `mkdir evt` | Object Created | `bidir/evt/`（0 字节） | ~5 秒 |
| 写入 `evtfile.txt` | Object Created | `bidir/evt/evtfile.txt`（44 字节） | ~9 秒 |
| `cat` 读取 | **无事件** | — | — |
| `rm evtfile.txt` | Object Deleted | `bidir/evt/evtfile.txt` | ~5 秒 |

开启 EventBridge 后再验证：DRA 状态仍为 `AVAILABLE`，S3 → Lustre 自动导入正常，bucket Versioning 不变。

## 4. 事件样例（账号 / bucket 已脱敏）

### 新建文件：Object Created
```json
{
  "version": "0",
  "id": "45f37893-c86c-e1f6-96ae-2472c9db6b51",
  "detail-type": "Object Created",
  "source": "aws.s3",
  "account": "111122223333",
  "time": "2026-10-09T04:16:06Z",
  "region": "us-east-2",
  "resources": ["arn:aws:s3:::my-lustre-bucket"],
  "detail": {
    "version": "0",
    "event-version": "1.2",
    "bucket": { "name": "my-lustre-bucket" },
    "object": {
      "key": "bidir/evt/evtfile.txt",
      "size": 44,
      "etag": "61c8a37e0792f134585331243d697a8e",
      "version-id": "rmakbnAjAqSBdQiht67XZGpiqYLyD.yc",
      "sequencer": "006AC86A864828B3DF"
    },
    "request-id": "HW41C6352X82799F",
    "requester": "111122223333",
    "source-ip-address": "52.14.7.35",
    "reason": "PutObject"
  }
}
```

### 新建目录：Object Created（目录标记）
Lustre 新建目录会在 S3 生成一个以 `/` 结尾、0 字节的对象。
```json
{
  "detail-type": "Object Created",
  "detail": {
    "object": {
      "key": "bidir/evt/",
      "size": 0,
      "etag": "d41d8cd98f00b204e9800998ecf8427e",
      "version-id": "0C_RAiRaljSWiN0tdHpyrAnTGf74Q3fU"
    },
    "reason": "PutObject"
  }
}
```
（其余字段与上例相同，此处省略）

### 删除文件：Object Deleted
```json
{
  "version": "0",
  "id": "073aaab0-34b3-bfac-a352-6813c1184467",
  "detail-type": "Object Deleted",
  "source": "aws.s3",
  "account": "111122223333",
  "time": "2026-10-09T04:17:22Z",
  "region": "us-east-2",
  "resources": ["arn:aws:s3:::my-lustre-bucket"],
  "detail": {
    "version": "0",
    "event-version": "1.2",
    "bucket": { "name": "my-lustre-bucket" },
    "object": {
      "key": "bidir/evt/evtfile.txt",
      "etag": "d41d8cd98f00b204e9800998ecf8427e",
      "version-id": "JdSL83A6TIt1KHpdkYl_wBaEGm7EuSFG",
      "sequencer": "006AC86AD272D3836D"
    },
    "request-id": "4WTCGZEGC1XMB539",
    "requester": "111122223333",
    "source-ip-address": "18.224.234.254",
    "reason": "DeleteObject",
    "deletion-type": "Delete Marker Created"
  }
}
```

### 常用字段

| 字段 | 含义 |
|---|---|
| `detail-type` | `Object Created` / `Object Deleted` |
| `detail.object.key` | S3 对象 key，去掉 DRA 前缀即 Lustre 相对路径（`bidir/evt/evtfile.txt` ↔ `/mnt/bidir/bidir/evt/evtfile.txt`） |
| `detail.object.size` | 文件大小（删除事件没有此字段） |
| `detail.reason` | `PutObject`（大文件可能为 `CompleteMultipartUpload`，本次未测）/ `DeleteObject` |
| `detail.deletion-type` | 开了 Versioning 为 `Delete Marker Created`（旧版本仍保留，可恢复）；未开为 `Permanently Deleted` |
| `detail.object.sequencer` | 同一 key 的事件先后顺序，用于排序 / 去重 |

## 5. 限制

1. **只有 DRA 关联路径下的文件才有事件**。Lustre 上不在 DRA 路径内的文件，增删改都不会产生事件。
2. **DRA 自动导出必须包含对应策略**：要删除事件需开启 `DELETED`，要新建事件需开启 `NEW`，修改需开启 `CHANGED`。
3. **读取文件没有事件**。S3 事件不包含读取（GET）类型。
4. **无法知道是谁删除的**。事件中的 `requester` / `source-ip-address` 是 FSx 服务，不是 Lustre 上的用户或客户端 IP。
5. **有延迟**：实测约 5–10 秒（文件写入完成后才会导出）。
6. **至少一次投递**：事件可能重复、可能乱序，下游需按 `sequencer` 排序去重。
7. **新建目录也产生事件**：key 以 `/` 结尾、`size=0`，按需过滤。
8. **删除事件没有文件大小**，`etag` 是删除标记本身的值，不是原文件。
9. **不能改用普通 S3 Event Notification**（SNS/SQS/Lambda）订阅 `ObjectCreated` / `ObjectRemoved`，会与 bucket 上已有配置冲突；只能用 EventBridge。
10. **修改通知配置时必须保留已有的 `FSx` 配置**，否则 S3 → Lustre 自动导入会失效。
11. **重命名不是一条事件**：表现为新名字 `Object Created`（reason=`CopyObject`）+ 旧名字 `Object Deleted`，两条无法直接关联；重命名目录时目录下每个对象各一对。
12. **chmod / chown 产生 `Object Created`（CopyObject）**，看不出改了什么；**只改时间（touch）没有事件**。
13. **删除目录有事件**（key 以 `/` 结尾），`rm -rf` 时每个文件、每级目录各一条。

## 6. 清理

```bash
aws events remove-targets --rule lustre-file-events --ids sqs --region $R
aws events delete-rule --name lustre-file-events --region $R
aws sqs delete-queue --queue-url $Q_URL --region $R
# 如需关闭 EventBridge：读出配置，删除 EventBridgeConfiguration 后写回（保留 FSx 那条）
```

## 参考
- [Using EventBridge (Amazon S3)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventBridge.html)
- [Amazon S3 Event Notifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventNotifications.html)
- [EventBridge 事件消息结构](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ev-events.html)
- [FSx for Lustre 自动导出](https://docs.aws.amazon.com/fsx/latest/LustreGuide/autoexport-data-repo-dra.html)
- [FSx for Lustre 自动导入](https://docs.aws.amazon.com/fsx/latest/LustreGuide/autoimport-data-repo-dra.html)
