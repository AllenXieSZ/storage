# EFS Access Point 创建 TPS 测试（1 万个）

区域 us-east-2，单个 EFS（Elastic throughput，无 mount target），boto3 调 `CreateAccessPoint`，客户端自带重试关闭，遇 `ThrottlingException` 自行指数退避重试。测试日期 2026-10-09。

## 结果

| 操作 | 规模 | 并发 | 耗时 | TPS | P50 | P99 | 结果 |
|---|---|---|---|---|---|---|---|
| 创建 AP | 10,000 | 2 | 9,980 s（≈2h46m） | **1.00** | 459 ms | 1,604 ms | 10000/10000 成功，0 失败（期间被限流 13,041 次，全部重试成功） |
| 满额后再建 1 个 | 1 | 1 | — | — | — | — | 报错 `AccessPointLimitExceeded`（HTTP 403） |
| 删除 AP | 10,000 | 2 | ≈10,000 s（≈2h47m） | **1.00** | 254 ms | 1,199 ms | 全部删除成功（被限流 11,580+ 次，重试成功） |

每 1000 个分段创建 TPS：0.99–1.01，全程平稳，无衰减。

满额报错原文：

```
An error occurred (AccessPointLimitExceeded) when calling the CreateAccessPoint operation:
You have reached the maximum number of access points (10000) for your file system fs-xxxxxxxx.
Delete an access point and add a new one.
```

## 结论

- **创建/删除 Access Point 的 API 速率约 1 个/秒**，与并发数无关（加并发只会多收 ThrottlingException）。创建 1 万个约需 **2 小时 46 分**。
- 单个 FS 上限 10,000 个 AP（默认配额），满额后报 `AccessPointLimitExceeded`。
- 速率限制在两个 FS 同时跑时合计也约 1/s（预探测），推测为账号/区域级的 API 速率限制，而非每 FS。

## 脚本

- `create_ap.py <FS_ID> <N> <并发> <前缀>`：并发创建 N 个 AP，每 1000 个打印进度，结束输出 TPS/P50/P99/重试数。
- `delete_ap.py <FS_ID> <并发>`：删除该 FS 上所有 AP，输出 TPS。

```bash
python3 create_ap.py fs-xxxxxxxx 10000 2 main > run10k.log 2>&1
python3 delete_ap.py fs-xxxxxxxx 2
```
