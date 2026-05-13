#!/usr/bin/env python3
"""
S3 Benchmark - Standard vs Express One Zone
Pure Python (boto3) - no AWS CLI required.

1. Create EC2 instance for benchmark
2. Create S3 Standard + Express One Zone buckets
3. Run benchmark on EC2 via SSM
4. Download and generate HTML comparison report
5. Cleanup all resources

Usage:
    pip install boto3
    python run_benchmark.py

Environment variables (optional):
    BENCH_REGION        - AWS region (default: us-east-2)
    BENCH_AZ_ID         - AZ ID for Express (default: use2-az1)
    BENCH_INSTANCE_TYPE - EC2 instance type (default: c6in.2xlarge)
    BENCH_ITERATIONS    - Latency test iterations (default: 20)
    BENCH_CONCURRENCY   - Throughput test concurrency (default: 64)
"""

import boto3
import json
import time
import sys
import os
import base64
from pathlib import Path
from datetime import datetime, timezone

# === Configuration ===
REGION = os.environ.get("BENCH_REGION", "us-east-2")
AZ_ID = os.environ.get("BENCH_AZ_ID", "use2-az1")
INSTANCE_TYPE = os.environ.get("BENCH_INSTANCE_TYPE", "c6in.2xlarge")
ITERATIONS = os.environ.get("BENCH_ITERATIONS", "20")
CONCURRENCY = os.environ.get("BENCH_CONCURRENCY", "64")

TIMESTAMP = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
ROLE_NAME = f"s3-bench-role-{TIMESTAMP}"
PROFILE_NAME = f"s3-bench-profile-{TIMESTAMP}"
SG_NAME = f"s3-bench-sg-{TIMESTAMP}"
BUCKET_STD = f"s3-bench-std-{TIMESTAMP}"
BUCKET_EXPRESS = f"s3-bench-exp-{TIMESTAMP}--{AZ_ID}--x-s3"
INSTANCE_NAME = f"s3-bench-{TIMESTAMP}"

REPORT_DIR = Path(__file__).parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

# Benchmark script (will be uploaded to S3 and run on EC2)
BENCHMARK_SCRIPT = (Path(__file__).parent / "benchmark.py").read_text()

# === Resource tracking ===
resources = {
    "instance_id": None,
    "sg_id": None,
    "role_name": None,
    "profile_name": None,
    "bucket_std": None,
    "bucket_express": None,
}


def log(msg):
    print(f"  {msg}", flush=True)


def header(msg):
    print(f"\n▶ {msg}", flush=True)


# === Clients ===
ec2 = boto3.client("ec2", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
iam = boto3.client("iam")
ssm = boto3.client("ssm", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)


def cleanup():
    """Cleanup all created resources."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    # Terminate EC2
    if resources["instance_id"]:
        log(f"Terminating EC2 {resources['instance_id']}...")
        try:
            ec2.terminate_instances(InstanceIds=[resources["instance_id"]])
            waiter = ec2.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=[resources["instance_id"]])
        except Exception as e:
            log(f"  Warning: {e}")

    # Delete Standard bucket
    if resources["bucket_std"]:
        log(f"Deleting Standard bucket {resources['bucket_std']}...")
        try:
            _empty_bucket(resources["bucket_std"])
            s3.delete_bucket(Bucket=resources["bucket_std"])
        except Exception as e:
            log(f"  Warning: {e}")

    # Delete Express bucket
    if resources["bucket_express"]:
        log(f"Deleting Express bucket {resources['bucket_express']}...")
        try:
            _empty_bucket(resources["bucket_express"])
            s3.delete_bucket(Bucket=resources["bucket_express"])
        except Exception as e:
            log(f"  Warning: {e}")

    # Remove instance profile
    if resources["profile_name"]:
        log(f"Deleting instance profile {resources['profile_name']}...")
        try:
            iam.remove_role_from_instance_profile(
                InstanceProfileName=resources["profile_name"],
                RoleName=resources["role_name"]
            )
        except Exception:
            pass
        try:
            iam.delete_instance_profile(InstanceProfileName=resources["profile_name"])
        except Exception as e:
            log(f"  Warning: {e}")

    # Delete IAM role
    if resources["role_name"]:
        log(f"Deleting IAM role {resources['role_name']}...")
        try:
            iam.delete_role_policy(RoleName=resources["role_name"], PolicyName="S3ExpressAccess")
        except Exception:
            pass
        for arn in [
            "arn:aws:iam::aws:policy/AmazonS3FullAccess",
            "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
        ]:
            try:
                iam.detach_role_policy(RoleName=resources["role_name"], PolicyArn=arn)
            except Exception:
                pass
        try:
            iam.delete_role(RoleName=resources["role_name"])
        except Exception as e:
            log(f"  Warning: {e}")

    # Delete security group
    if resources["sg_id"]:
        log(f"Deleting security group {resources['sg_id']}...")
        time.sleep(5)  # Wait for ENI detach
        try:
            ec2.delete_security_group(GroupId=resources["sg_id"])
        except Exception as e:
            log(f"  Warning: {e}")

    log("✅ Cleanup complete")


def _empty_bucket(bucket):
    """Delete all objects in a bucket."""
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        objects = page.get("Contents", [])
        if objects:
            s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]}
            )


def create_buckets():
    """Create Standard and Express One Zone buckets."""
    header("Step 1: Creating S3 buckets...")

    # Standard bucket
    s3.create_bucket(
        Bucket=BUCKET_STD,
        CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    resources["bucket_std"] = BUCKET_STD
    log(f"✅ Standard bucket: {BUCKET_STD}")

    # Express One Zone bucket
    s3.create_bucket(
        Bucket=BUCKET_EXPRESS,
        CreateBucketConfiguration={
            "Location": {"Type": "AvailabilityZone", "Name": AZ_ID},
            "Bucket": {"Type": "Directory", "DataRedundancy": "SingleAvailabilityZone"},
        }
    )
    resources["bucket_express"] = BUCKET_EXPRESS
    log(f"✅ Express bucket: {BUCKET_EXPRESS}")


def create_iam_role():
    """Create IAM role with S3 + SSM permissions."""
    header("Step 2: Creating IAM role and instance profile...")

    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })

    iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=trust_policy
    )
    resources["role_name"] = ROLE_NAME

    # Attach managed policies
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonS3FullAccess")
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore")

    # Inline policy for S3 Express CreateSession
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="S3ExpressAccess",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "s3express:CreateSession", "Resource": "*"}]
        })
    )

    # Create instance profile
    iam.create_instance_profile(InstanceProfileName=PROFILE_NAME)
    iam.add_role_to_instance_profile(InstanceProfileName=PROFILE_NAME, RoleName=ROLE_NAME)
    resources["profile_name"] = PROFILE_NAME

    log(f"✅ IAM role: {ROLE_NAME}")
    log("Waiting 10s for IAM propagation...")
    time.sleep(10)


def create_security_group():
    """Create security group (no inbound, SSM only)."""
    header("Step 3: Creating security group...")

    # Get default VPC
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    vpc_id = vpcs["Vpcs"][0]["VpcId"]

    sg = ec2.create_security_group(
        GroupName=SG_NAME,
        Description="S3 Benchmark - SSM only, no inbound",
        VpcId=vpc_id
    )
    resources["sg_id"] = sg["GroupId"]
    log(f"✅ Security group: {sg['GroupId']}")
    return vpc_id


def launch_ec2(vpc_id):
    """Launch EC2 instance in same AZ as Express bucket."""
    header(f"Step 4: Launching EC2 ({INSTANCE_TYPE}) in AZ {AZ_ID}...")

    # Find subnet in target AZ
    subnets = ec2.describe_subnets(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "availability-zone-id", "Values": [AZ_ID]},
        ]
    )
    subnet_id = subnets["Subnets"][0]["SubnetId"]
    log(f"Subnet: {subnet_id}")

    # Get latest AL2023 AMI
    images = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": ["al2023-ami-2023*-kernel-*-x86_64"]},
            {"Name": "state", "Values": ["available"]},
        ]
    )
    ami_id = sorted(images["Images"], key=lambda x: x["CreationDate"])[-1]["ImageId"]
    log(f"AMI: {ami_id}")

    # Launch
    resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=INSTANCE_TYPE,
        SubnetId=subnet_id,
        IamInstanceProfile={"Name": PROFILE_NAME},
        SecurityGroupIds=[resources["sg_id"]],
        MinCount=1, MaxCount=1,
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": INSTANCE_NAME}]
        }],
        MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 2},
    )
    instance_id = resp["Instances"][0]["InstanceId"]
    resources["instance_id"] = instance_id
    log(f"Instance ID: {instance_id}")

    # Wait for running
    log("Waiting for instance to start...")
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])
    log("✅ Instance running")

    # Wait for SSM agent
    log("Waiting for SSM agent...")
    for i in range(30):
        try:
            info = ssm.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
            )
            if info["InstanceInformationList"] and info["InstanceInformationList"][0]["PingStatus"] == "Online":
                log("✅ SSM agent online")
                return instance_id
        except Exception:
            pass
        time.sleep(10)

    raise TimeoutError("SSM agent did not come online within 5 minutes")


def run_benchmark_on_ec2(instance_id):
    """Upload script and run via SSM."""
    header("Step 5: Running benchmark on EC2...")

    # Upload benchmark script to S3
    s3.put_object(Bucket=BUCKET_STD, Key="benchmark.py", Body=BENCHMARK_SCRIPT.encode())
    log("Uploaded benchmark.py to S3")

    # Build command
    commands = [
        "dnf install -y python3-pip 2>/dev/null || yum install -y python3-pip",
        "pip3 install boto3 2>/dev/null",
        f"aws s3 cp s3://{BUCKET_STD}/benchmark.py /tmp/benchmark.py --region {REGION} 2>/dev/null || python3 -c \"import boto3; s3=boto3.client('s3',region_name='{REGION}'); s3.download_file('{BUCKET_STD}','benchmark.py','/tmp/benchmark.py')\"",
        f"BENCH_BUCKET_STD={BUCKET_STD} BENCH_BUCKET_EXPRESS={BUCKET_EXPRESS} BENCH_REGION={REGION} BENCH_AZ_ID={AZ_ID} BENCH_ITERATIONS={ITERATIONS} BENCH_CONCURRENCY={CONCURRENCY} python3 /tmp/benchmark.py",
        f"python3 -c \"import boto3; s3=boto3.client('s3',region_name='{REGION}'); s3.upload_file('/tmp/s3_bench_results.json','{BUCKET_STD}','results/s3_bench_results.json'); s3.upload_file('/tmp/s3_bench_report.html','{BUCKET_STD}','results/s3_bench_report.html')\"",
    ]

    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        TimeoutSeconds=900,
        Parameters={"commands": commands}
    )
    command_id = resp["Command"]["CommandId"]
    log(f"SSM Command ID: {command_id}")
    log("Waiting for completion (may take 10-15 minutes)...")

    # Poll for completion
    for i in range(90):
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            status = result["Status"]
            if status == "Success":
                log("✅ Benchmark completed")
                print("\n--- Benchmark Output ---")
                print(result.get("StandardOutputContent", "")[-3000:])  # Last 3000 chars
                return True
            elif status in ("Failed", "Cancelled", "TimedOut"):
                log(f"❌ Failed with status: {status}")
                print("STDOUT:", result.get("StandardOutputContent", "")[-2000:])
                print("STDERR:", result.get("StandardErrorContent", "")[-2000:])
                return False
        except ssm.exceptions.InvocationDoesNotExist:
            pass
        time.sleep(10)

    log("❌ Timeout waiting for benchmark")
    return False


def download_reports():
    """Download report files from S3."""
    header("Step 6: Downloading reports...")

    json_path = REPORT_DIR / "s3_bench_results.json"
    html_path = REPORT_DIR / "s3_bench_report.html"

    s3.download_file(BUCKET_STD, "results/s3_bench_results.json", str(json_path))
    s3.download_file(BUCKET_STD, "results/s3_bench_report.html", str(html_path))

    log(f"✅ JSON: {json_path}")
    log(f"✅ HTML: {html_path}")

    # Also upload to persistent bucket for easy access
    try:
        s3.upload_file(
            str(html_path),
            "<BUCKET>",
            f"reports/s3_bench_compare_{TIMESTAMP}.html",
            ExtraArgs={"ContentType": "text/html"}
        )
        # Generate presigned URL
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": "<BUCKET>", "Key": f"reports/s3_bench_compare_{TIMESTAMP}.html"},
            ExpiresIn=86400
        )
        log(f"📎 Report URL (24h): {url}")
    except Exception as e:
        log(f"  (Could not upload to persistent bucket: {e})")


def main():
    print("=" * 60)
    print("S3 Standard vs Express One Zone Benchmark")
    print("=" * 60)
    print(f"  Region:        {REGION}")
    print(f"  AZ ID:         {AZ_ID}")
    print(f"  Instance:      {INSTANCE_TYPE}")
    print(f"  Iterations:    {ITERATIONS}")
    print(f"  Concurrency:   {CONCURRENCY}")
    print(f"  Std Bucket:    {BUCKET_STD}")
    print(f"  Exp Bucket:    {BUCKET_EXPRESS}")
    print("=" * 60)

    try:
        create_buckets()
        create_iam_role()
        vpc_id = create_security_group()
        instance_id = launch_ec2(vpc_id)

        success = run_benchmark_on_ec2(instance_id)
        if success:
            download_reports()

        print("\n" + "=" * 60)
        if success:
            print("✅ BENCHMARK COMPLETE")
            print(f"   HTML Report: {REPORT_DIR / 's3_bench_report.html'}")
            print(f"   JSON Data:   {REPORT_DIR / 's3_bench_results.json'}")
        else:
            print("❌ BENCHMARK FAILED")
        print("=" * 60)

    finally:
        cleanup()


if __name__ == "__main__":
    main()
