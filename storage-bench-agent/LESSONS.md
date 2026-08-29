# storage-bench 踩坑汇总 (LESSONS.md)

> 每次实验踩的坑统一累积在这里（追加不覆盖）。固定 URL:
> https://github.com/AllenXieSZ/storage/blob/main/storage-bench-agent/LESSONS.md
> 格式：日期 · 现象 · 根因 · 规避

---

## 2026-08-29 首跑 EBS 端到端

- **DynamoDB Decimal 坑**
  - 现象：create_volume 报 `Invalid type for parameter Size, type: Decimal, valid: int`
  - 根因：DynamoDB 读回的数字是 `decimal.Decimal`，boto3 EC2 API 只接受 `int`
  - 规避：provision 里对 Size/Throughput/Iops 等 `int(...)` 强转

- **默认 instance profile 不存在**
  - 现象：run_instances 报 `Invalid IAM Instance Profile name (PVRE-SSMOnboardingInstanceProfile)`
  - 根因：该 profile 名在本账号不存在（是别的环境的默认）
  - 规避：建 `storage-bench-ec2-profile`（附 AmazonSSMManagedInstanceCore），配到 config.INSTANCE_PROFILE

- **gp3 新卷性能偏低**
  - 现象：randread 4k 仅 6940 IOPS/27MB/s（卷配 16000 IOPS）
  - 根因：新卷首次访问初始化惩罚 + 未预热 + size=10G 随机读未充分打满
  - 规避：测基线前先预热（顺序写满一遍或 fio --rw=write 预热），再测随机；数据先准备好
