"""
config.py — storage-bench-agent 默认配置 (us-east-2)
可被 params 覆盖. 集中放默认值, 便于扩展/换环境.
"""
REGION = "us-east-2"
ACCOUNT = "386094880462"

# EC2 默认 (default VPC, 公有子网 2c — 与现有实验同子网)
VPC_ID = "vpc-0c28d2a9082ef222e"
DEFAULT_SUBNET = "subnet-0c551a33e366d52d4"   # us-east-2c, MapPublicIp=True
AMI_X86 = "ami-06475e8f54266e38e"             # AL2023 x86_64 (查询自 SSM latest)
DEFAULT_INSTANCE = "c6in.4xlarge"
KEY_NAME = "ohio"

# 报告存储
REPORT_BUCKET = "s3lambdatest2"               # 复用现有 bucket
REPORT_PREFIX = "storage-bench-reports"
PRESIGN_EXPIRE = 604800                        # 7 天

# DynamoDB
TASK_TABLE = "storage-bench-tasks"

# 标签 (所有创建的资源都打, 便于清理/成本归集)
def tags(task_id: str) -> list[dict]:
    return [
        {"Key": "project", "Value": "storage-bench-agent"},
        {"Key": "managedBy", "Value": "openclaw"},
        {"Key": "taskId", "Value": task_id},
    ]
