#!/usr/bin/env python3
"""
EBS Performance Benchmark Tool
Automatically provisions EC2 + EBS, runs fio tests, generates HTML report.

Usage:
    python3 ebs-bench.py --access-key AKIA... --secret-key ... --region us-east-2
    python3 ebs-bench.py --profile default --region us-east-2
    python3 ebs-bench.py --region us-east-2  # uses env/default credentials
"""

import argparse
import boto3
import json
import time
import sys
import os
from datetime import datetime, timezone

# ============================================================================
# Configuration
# ============================================================================

RUNTIME_SECONDS = 60        # fio --runtime per test (adjustable)
WARMUP_SECONDS = 10         # warmup before each test
FIO_FILE_SIZE = "20G"       # fio test file size
RAMP_TIME = 5               # fio --ramp_time (seconds)

# EBS volume configs to test
EBS_CONFIGS = [
    {
        "name": "gp3-20k",
        "volume_type": "gp3",
        "size_gib": 100,
        "iops": 20000,
        "throughput": 1000,  # MB/s
        "description": "gp3 — 100 GiB, 20,000 IOPS, 1,000 MB/s"
    },
    {
        "name": "io2-20k",
        "volume_type": "io2",
        "size_gib": 100,
        "iops": 20000,
        "throughput": None,  # io2 throughput is auto-calculated
        "description": "io2 — 100 GiB, 20,000 IOPS"
    },
]

# fio test definitions
FIO_TESTS = [
    {
        "name": "rand-read-4k",
        "label": "Random Read 4K",
        "category": "IOPS",
        "bs": "4k",
        "rw": "randread",
        "iodepth": 64,
        "numjobs": 4,
        "direct": 1,
    },
    {
        "name": "rand-write-4k",
        "label": "Random Write 4K",
        "category": "IOPS",
        "bs": "4k",
        "rw": "randwrite",
        "iodepth": 64,
        "numjobs": 4,
        "direct": 1,
    },
    {
        "name": "seq-read-1m",
        "label": "Sequential Read 1M",
        "category": "Throughput",
        "bs": "1m",
        "rw": "read",
        "iodepth": 32,
        "numjobs": 4,
        "direct": 1,
    },
    {
        "name": "seq-write-1m",
        "label": "Sequential Write 1M",
        "category": "Throughput",
        "bs": "1m",
        "rw": "write",
        "iodepth": 32,
        "numjobs": 4,
        "direct": 1,
    },
    {
        "name": "rand-read-4k-lat",
        "label": "Random Read 4K (Latency)",
        "category": "Latency",
        "bs": "4k",
        "rw": "randread",
        "iodepth": 1,
        "numjobs": 1,
        "direct": 1,
    },
    {
        "name": "rand-write-4k-lat",
        "label": "Random Write 4K (Latency)",
        "category": "Latency",
        "bs": "4k",
        "rw": "randwrite",
        "iodepth": 1,
        "numjobs": 1,
        "direct": 1,
    },
    {
        "name": "mixed-randrw-4k",
        "label": "Mixed Random 70R/30W 4K",
        "category": "Mixed",
        "bs": "4k",
        "rw": "randrw",
        "rwmixread": 70,
        "iodepth": 64,
        "numjobs": 4,
        "direct": 1,
    },
]

# EC2 instance selection based on required EBS performance
# Reference: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-optimized.html
INSTANCE_SPECS = [
    # (max_iops, max_throughput_mbps, instance_type)
    (10000,   593,  "c6i.2xlarge"),
    (20000,  1187,  "c6i.4xlarge"),
    (40000,  2375,  "c6i.8xlarge"),
    (80000,  5000,  "c6i.16xlarge"),
    (160000, 10000, "c6i.24xlarge"),
]


def select_instance_type(required_iops, required_throughput_mbps):
    """Select smallest instance that can drive the required EBS performance."""
    for max_iops, max_tp, itype in INSTANCE_SPECS:
        tp = required_throughput_mbps or 0
        if max_iops >= required_iops and max_tp >= tp:
            return itype, max_iops, max_tp
    # fallback to largest
    return INSTANCE_SPECS[-1][2], INSTANCE_SPECS[-1][0], INSTANCE_SPECS[-1][1]


def build_fio_command(test, device, runtime=RUNTIME_SECONDS, ramp=RAMP_TIME):
    """Build fio command string for a test."""
    cmd = (
        f"fio --name={test['name']} "
        f"--filename={device} "
        f"--bs={test['bs']} "
        f"--rw={test['rw']} "
        f"--ioengine=libaio "
        f"--direct={test['direct']} "
        f"--iodepth={test['iodepth']} "
        f"--numjobs={test['numjobs']} "
        f"--size={FIO_FILE_SIZE} "
        f"--runtime={runtime} "
        f"--time_based "
        f"--ramp_time={ramp} "
        f"--group_reporting "
        f"--output-format=json"
    )
    if "rwmixread" in test:
        cmd += f" --rwmixread={test['rwmixread']}"
    return cmd


# ============================================================================
# AWS Operations
# ============================================================================

class EBSBenchmark:
    def __init__(self, region, access_key=None, secret_key=None, profile=None):
        session_kwargs = {"region_name": region}
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
        elif profile:
            session_kwargs["profile_name"] = profile
        
        self.session = boto3.Session(**session_kwargs)
        self.ec2 = self.session.client("ec2")
        self.ssm = self.session.client("ssm")
        self.iam = self.session.client("iam")
        self.region = region
        self.resources = {}  # track for cleanup
        self.results = {}    # test results
        self.start_time = datetime.now(timezone.utc)

    def log(self, msg):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

    # --- AMI ---
    def find_ami(self):
        """Find latest Amazon Linux 2023 AMI."""
        self.log("Finding latest AL2023 AMI...")
        resp = self.ec2.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": ["al2023-ami-2023.*-x86_64"]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "architecture", "Values": ["x86_64"]},
            ],
        )
        images = sorted(resp["Images"], key=lambda x: x["CreationDate"], reverse=True)
        ami = images[0]["ImageId"]
        self.log(f"  AMI: {ami} ({images[0]['Name']})")
        return ami

    # --- IAM ---
    def create_iam_role(self):
        """Create IAM role + instance profile for SSM."""
        role_name = "ebs-bench-ssm-role"
        profile_name = "ebs-bench-ssm-profile"
        
        trust_policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        })

        self.log("Creating IAM role for SSM...")
        try:
            self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=trust_policy,
                Description="EBS Benchmark - SSM access",
            )
        except self.iam.exceptions.EntityAlreadyExistsException:
            self.log("  Role already exists, reusing")

        self.iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
        )

        try:
            self.iam.create_instance_profile(InstanceProfileName=profile_name)
        except self.iam.exceptions.EntityAlreadyExistsException:
            pass

        try:
            self.iam.add_role_to_instance_profile(
                InstanceProfileName=profile_name,
                RoleName=role_name,
            )
        except self.iam.exceptions.LimitExceededException:
            pass  # already attached

        self.resources["iam_role"] = role_name
        self.resources["iam_profile"] = profile_name
        
        # Wait for profile propagation
        self.log("  Waiting for IAM propagation (15s)...")
        time.sleep(15)
        return profile_name

    # --- Security Group ---
    def create_security_group(self, vpc_id):
        """Create SG with no inbound rules (SSM only needs outbound)."""
        self.log("Creating security group...")
        resp = self.ec2.create_security_group(
            GroupName=f"ebs-bench-{int(time.time())}",
            Description="EBS Benchmark - no inbound",
            VpcId=vpc_id,
        )
        sg_id = resp["GroupId"]
        # Revoke default all-traffic egress? No, SSM needs outbound HTTPS.
        self.resources["sg_id"] = sg_id
        self.log(f"  SG: {sg_id}")
        return sg_id

    # --- EC2 ---
    def get_default_vpc_subnet(self):
        """Get default VPC and a subnet."""
        vpcs = self.ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
        if not vpcs["Vpcs"]:
            raise RuntimeError("No default VPC found. Specify --vpc-id and --subnet-id.")
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        
        subnets = self.ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}, {"Name": "default-for-az", "Values": ["true"]}]
        )
        subnet = subnets["Subnets"][0]
        return vpc_id, subnet["SubnetId"], subnet["AvailabilityZone"]

    def launch_instance(self, ami, instance_type, subnet_id, sg_id, profile_name, az):
        """Launch EC2 instance."""
        self.log(f"Launching {instance_type} in {az}...")
        resp = self.ec2.run_instances(
            ImageId=ami,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            SubnetId=subnet_id,
            SecurityGroupIds=[sg_id],
            IamInstanceProfile={"Name": profile_name},
            TagSpecifications=[{
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "ebs-bench"}]
            }],
            # No key pair needed - using SSM
            MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
        )
        instance_id = resp["Instances"][0]["InstanceId"]
        self.resources["instance_id"] = instance_id
        self.log(f"  Instance: {instance_id}")

        # Wait for running
        self.log("  Waiting for instance to be running...")
        waiter = self.ec2.get_waiter("instance_running")
        waiter.wait(InstanceIds=[instance_id])
        self.log("  Instance is running")
        return instance_id

    def wait_ssm_online(self, instance_id, timeout=300):
        """Wait for SSM agent to come online."""
        self.log("  Waiting for SSM agent...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.ssm.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
            )
            if resp["InstanceInformationList"]:
                info = resp["InstanceInformationList"][0]
                if info.get("PingStatus") == "Online":
                    self.log("  SSM agent is online")
                    return True
            time.sleep(10)
        raise TimeoutError("SSM agent did not come online within timeout")

    # --- EBS ---
    def create_volume(self, az, config):
        """Create EBS volume."""
        self.log(f"Creating {config['description']}...")
        params = {
            "AvailabilityZone": az,
            "VolumeType": config["volume_type"],
            "Size": config["size_gib"],
            "Iops": config["iops"],
            "TagSpecifications": [{
                "ResourceType": "volume",
                "Tags": [{"Key": "Name", "Value": f"ebs-bench-{config['name']}"}]
            }],
        }
        if config.get("throughput"):
            params["Throughput"] = config["throughput"]
        
        resp = self.ec2.create_volume(**params)
        vol_id = resp["VolumeId"]
        self.log(f"  Volume: {vol_id}")

        # Wait for available
        waiter = self.ec2.get_waiter("volume_available")
        waiter.wait(VolumeIds=[vol_id])
        self.log(f"  Volume available")
        return vol_id

    def attach_volume(self, instance_id, vol_id, device="/dev/sdf"):
        """Attach EBS volume."""
        self.log(f"Attaching {vol_id} as {device}...")
        self.ec2.attach_volume(
            InstanceId=instance_id,
            VolumeId=vol_id,
            Device=device,
        )
        # Wait for attached
        while True:
            resp = self.ec2.describe_volumes(VolumeIds=[vol_id])
            attachments = resp["Volumes"][0].get("Attachments", [])
            if attachments and attachments[0]["State"] == "attached":
                break
            time.sleep(3)
        self.log(f"  Attached")

    def detach_and_delete_volume(self, instance_id, vol_id):
        """Detach and delete EBS volume."""
        self.log(f"Detaching {vol_id}...")
        try:
            self.ec2.detach_volume(VolumeId=vol_id, InstanceId=instance_id, Force=True)
            time.sleep(10)
        except Exception as e:
            self.log(f"  Detach warning: {e}")
        
        self.log(f"Deleting {vol_id}...")
        try:
            waiter = self.ec2.get_waiter("volume_available")
            waiter.wait(VolumeIds=[vol_id], WaiterConfig={"Delay": 5, "MaxAttempts": 30})
            self.ec2.delete_volume(VolumeId=vol_id)
        except Exception as e:
            self.log(f"  Delete warning: {e}")

    # --- SSM Command Execution ---
    def run_ssm_command(self, instance_id, commands, timeout=600):
        """Run commands via SSM and return output."""
        resp = self.ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
            TimeoutSeconds=timeout,
        )
        cmd_id = resp["Command"]["CommandId"]
        
        # Wait for completion
        deadline = time.time() + timeout + 60
        while time.time() < deadline:
            try:
                inv = self.ssm.get_command_invocation(
                    CommandId=cmd_id, InstanceId=instance_id
                )
                if inv["Status"] in ("Success", "Failed", "TimedOut", "Cancelled"):
                    return {
                        "status": inv["Status"],
                        "stdout": inv.get("StandardOutputContent", ""),
                        "stderr": inv.get("StandardErrorContent", ""),
                    }
            except self.ssm.exceptions.InvocationDoesNotExist:
                pass
            time.sleep(10)
        raise TimeoutError(f"SSM command {cmd_id} did not complete")

    def install_fio(self, instance_id):
        """Install fio on the instance."""
        self.log("Installing fio...")
        result = self.run_ssm_command(instance_id, [
            "yum install -y fio 2>&1 || dnf install -y fio 2>&1",
            "fio --version",
        ])
        version = result["stdout"].strip().split("\n")[-1]
        self.log(f"  fio version: {version}")
        return version

    def find_nvme_device(self, instance_id):
        """Find the NVMe device for the attached EBS volume."""
        result = self.run_ssm_command(instance_id, [
            "lsblk -d -n -o NAME,SIZE,TYPE | grep disk",
            "ls -la /dev/nvme*n1 2>/dev/null || ls -la /dev/xvd* 2>/dev/null",
        ])
        self.log(f"  Block devices: {result['stdout'].strip()}")
        # On Nitro instances, EBS shows as /dev/nvme1n1 (nvme0n1 is root)
        lines = result["stdout"].strip().split("\n")
        for line in lines:
            if "nvme" in line and "n1" in line:
                parts = line.split()
                dev_name = parts[0] if not parts[0].startswith("/") else parts[-1]
                if "nvme0" not in line:  # skip root
                    device = f"/dev/{dev_name}" if not dev_name.startswith("/") else dev_name
                    # clean up device path
                    if "/dev/nvme" in device:
                        device = device.split("/dev/")[-1]
                        device = f"/dev/{device.split()[0]}" if " " in device else f"/dev/{device}"
                    self.log(f"  Using device: {device}")
                    return device
        # Fallback: find non-root disk
        result2 = self.run_ssm_command(instance_id, [
            "lsblk -d -n -p -o NAME,SIZE | grep -v $(lsblk -n -o PKNAME $(findmnt -n -o SOURCE /) | head -1) | head -1 | awk '{print $1}'"
        ])
        device = result2["stdout"].strip()
        if device:
            self.log(f"  Using device (fallback): {device}")
            return device
        raise RuntimeError("Cannot find attached EBS device")

    def run_fio_test(self, instance_id, device, test):
        """Run a single fio test and return parsed JSON result."""
        fio_cmd = build_fio_command(test, device, RUNTIME_SECONDS, RAMP_TIME)
        self.log(f"  Running: {test['label']} ({test['name']})...")
        
        # Run fio with timeout = runtime + ramp + warmup + buffer
        timeout = RUNTIME_SECONDS + RAMP_TIME + 120
        result = self.run_ssm_command(instance_id, [fio_cmd], timeout=timeout)
        
        if result["status"] != "Success":
            self.log(f"    FAILED: {result['stderr'][:200]}")
            return None
        
        try:
            fio_json = json.loads(result["stdout"])
            return {
                "test": test,
                "fio_command": fio_cmd,
                "fio_json": fio_json,
                "parsed": self.parse_fio_result(fio_json, test),
            }
        except json.JSONDecodeError:
            self.log(f"    JSON parse error, stdout: {result['stdout'][:200]}")
            return None

    def parse_fio_result(self, fio_json, test):
        """Extract key metrics from fio JSON output."""
        job = fio_json["jobs"][0]
        result = {}
        
        rw = test["rw"]
        if rw in ("read", "randread"):
            r = job["read"]
            result["iops"] = r["iops"]
            result["bw_mbs"] = r["bw"] / 1024  # KB/s → MB/s
            result["lat_avg_us"] = r["lat_ns"]["mean"] / 1000
            result["lat_p50_us"] = r["clat_ns"]["percentile"].get("50.000000", 0) / 1000
            result["lat_p99_us"] = r["clat_ns"]["percentile"].get("99.000000", 0) / 1000
            result["lat_p999_us"] = r["clat_ns"]["percentile"].get("99.900000", 0) / 1000
        elif rw in ("write", "randwrite"):
            w = job["write"]
            result["iops"] = w["iops"]
            result["bw_mbs"] = w["bw"] / 1024
            result["lat_avg_us"] = w["lat_ns"]["mean"] / 1000
            result["lat_p50_us"] = w["clat_ns"]["percentile"].get("50.000000", 0) / 1000
            result["lat_p99_us"] = w["clat_ns"]["percentile"].get("99.000000", 0) / 1000
            result["lat_p999_us"] = w["clat_ns"]["percentile"].get("99.900000", 0) / 1000
        elif rw == "randrw":
            r, w = job["read"], job["write"]
            result["read_iops"] = r["iops"]
            result["write_iops"] = w["iops"]
            result["total_iops"] = r["iops"] + w["iops"]
            result["read_bw_mbs"] = r["bw"] / 1024
            result["write_bw_mbs"] = w["bw"] / 1024
            result["read_lat_p50_us"] = r["clat_ns"]["percentile"].get("50.000000", 0) / 1000
            result["write_lat_p50_us"] = w["clat_ns"]["percentile"].get("50.000000", 0) / 1000
            result["read_lat_p99_us"] = r["clat_ns"]["percentile"].get("99.000000", 0) / 1000
            result["write_lat_p99_us"] = w["clat_ns"]["percentile"].get("99.000000", 0) / 1000

        return result

    # --- Cleanup ---
    def cleanup(self):
        """Clean up all created resources."""
        self.log("=" * 50)
        self.log("CLEANUP")
        
        instance_id = self.resources.get("instance_id")
        if instance_id:
            self.log(f"Terminating instance {instance_id}...")
            try:
                self.ec2.terminate_instances(InstanceIds=[instance_id])
                waiter = self.ec2.get_waiter("instance_terminated")
                waiter.wait(InstanceIds=[instance_id])
                self.log("  Terminated")
            except Exception as e:
                self.log(f"  Warning: {e}")

        # Delete any leftover volumes
        for key, vol_id in list(self.resources.items()):
            if key.startswith("volume_"):
                try:
                    self.ec2.delete_volume(VolumeId=vol_id)
                    self.log(f"  Deleted volume {vol_id}")
                except Exception:
                    pass

        sg_id = self.resources.get("sg_id")
        if sg_id:
            self.log(f"Deleting security group {sg_id}...")
            time.sleep(5)  # wait for ENI detach
            for attempt in range(6):
                try:
                    self.ec2.delete_security_group(GroupId=sg_id)
                    self.log("  Deleted")
                    break
                except Exception as e:
                    if attempt < 5:
                        time.sleep(10)
                    else:
                        self.log(f"  Warning: {e}")

        role_name = self.resources.get("iam_role")
        profile_name = self.resources.get("iam_profile")
        if role_name:
            self.log(f"Cleaning up IAM role {role_name}...")
            try:
                self.iam.remove_role_from_instance_profile(
                    InstanceProfileName=profile_name, RoleName=role_name
                )
            except Exception:
                pass
            try:
                self.iam.delete_instance_profile(InstanceProfileName=profile_name)
            except Exception:
                pass
            try:
                self.iam.detach_role_policy(
                    RoleName=role_name,
                    PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
                )
            except Exception:
                pass
            try:
                self.iam.delete_role(RoleName=role_name)
                self.log("  Cleaned up IAM")
            except Exception as e:
                self.log(f"  Warning: {e}")

        self.log("Cleanup complete")

    # --- Main Flow ---
    def run(self):
        """Execute the full benchmark."""
        try:
            self.log("=" * 60)
            self.log("EBS Performance Benchmark")
            self.log(f"Region: {self.region}")
            self.log(f"Runtime per test: {RUNTIME_SECONDS}s")
            self.log("=" * 60)

            # Determine instance type from max IOPS/throughput across all configs
            max_iops = max(c["iops"] for c in EBS_CONFIGS)
            max_tp = max(c.get("throughput") or 0 for c in EBS_CONFIGS)
            instance_type, inst_max_iops, inst_max_tp = select_instance_type(max_iops, max_tp)
            self.log(f"Instance type: {instance_type} (EBS: {inst_max_iops} IOPS / {inst_max_tp} MB/s)")
            self.resources["instance_type"] = instance_type

            # Phase 1: Setup
            ami = self.find_ami()
            profile_name = self.create_iam_role()
            vpc_id, subnet_id, az = self.get_default_vpc_subnet()
            self.log(f"VPC: {vpc_id}, Subnet: {subnet_id}, AZ: {az}")
            sg_id = self.create_security_group(vpc_id)
            instance_id = self.launch_instance(ami, instance_type, subnet_id, sg_id, profile_name, az)
            self.wait_ssm_online(instance_id)
            fio_version = self.install_fio(instance_id)
            self.resources["fio_version"] = fio_version

            # Phase 2: Test each EBS config
            all_results = {}
            for ebs_config in EBS_CONFIGS:
                self.log("=" * 50)
                self.log(f"Testing: {ebs_config['description']}")
                self.log("=" * 50)

                # Create and attach volume
                vol_id = self.create_volume(az, ebs_config)
                self.resources[f"volume_{ebs_config['name']}"] = vol_id
                self.attach_volume(instance_id, vol_id)
                time.sleep(5)  # let device settle

                # Find the NVMe device
                device = self.find_nvme_device(instance_id)

                # Run all fio tests on raw device (no filesystem)
                test_results = []
                for test in FIO_TESTS:
                    result = self.run_fio_test(instance_id, device, test)
                    if result:
                        test_results.append(result)
                        # Log key metric
                        p = result["parsed"]
                        if "total_iops" in p:
                            self.log(f"    → R:{p['read_iops']:.0f} + W:{p['write_iops']:.0f} = {p['total_iops']:.0f} IOPS")
                        elif p.get("iops", 0) > 1000:
                            self.log(f"    → {p['iops']:.0f} IOPS, {p['bw_mbs']:.1f} MB/s, p99={p['lat_p99_us']:.0f}µs")
                        else:
                            self.log(f"    → {p['bw_mbs']:.1f} MB/s, p99={p['lat_p99_us']:.0f}µs")

                all_results[ebs_config["name"]] = {
                    "config": ebs_config,
                    "tests": test_results,
                }

                # Detach and delete this volume before next
                self.detach_and_delete_volume(instance_id, vol_id)
                del self.resources[f"volume_{ebs_config['name']}"]

            self.results = all_results

            # Phase 3: Generate report
            report_path = self.generate_html_report(all_results, instance_type, fio_version)
            self.log(f"\n✅ Report saved to: {report_path}")

        finally:
            self.cleanup()

    # --- HTML Report ---
    def generate_html_report(self, all_results, instance_type, fio_version):
        """Generate HTML report."""
        ts = self.start_time.strftime("%Y-%m-%d %H:%M UTC")
        duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        duration_min = duration / 60

        # Build results tables HTML
        volume_sections = ""
        for vol_name, vol_data in all_results.items():
            cfg = vol_data["config"]
            tests = vol_data["tests"]
            
            rows = ""
            commands_html = ""
            for t in tests:
                p = t["parsed"]
                test_info = t["test"]
                
                if test_info["rw"] == "randrw":
                    iops_str = f"R:{p['read_iops']:,.0f} / W:{p['write_iops']:,.0f}<br>Total: {p['total_iops']:,.0f}"
                    bw_str = f"R:{p['read_bw_mbs']:.1f} / W:{p['write_bw_mbs']:.1f}"
                    lat_p50 = f"R:{p['read_lat_p50_us']:.0f} / W:{p['write_lat_p50_us']:.0f}"
                    lat_p99 = f"R:{p['read_lat_p99_us']:.0f} / W:{p['write_lat_p99_us']:.0f}"
                else:
                    iops_str = f"{p['iops']:,.0f}"
                    bw_str = f"{p['bw_mbs']:.1f}"
                    lat_p50 = f"{p['lat_p50_us']:.0f}"
                    lat_p99 = f"{p['lat_p99_us']:.0f}"

                cat_class = test_info["category"].lower()
                rows += f"""
                <tr class="cat-{cat_class}">
                    <td><span class="badge badge-{cat_class}">{test_info['category']}</span></td>
                    <td><strong>{test_info['label']}</strong></td>
                    <td class="num">{iops_str}</td>
                    <td class="num">{bw_str}</td>
                    <td class="num">{lat_p50}</td>
                    <td class="num">{lat_p99}</td>
                </tr>"""
                
                commands_html += f"""
                <div class="cmd-block">
                    <div class="cmd-label">{test_info['label']}</div>
                    <code>{t['fio_command']}</code>
                </div>"""

            tp_line = f", {cfg['throughput']} MB/s" if cfg.get('throughput') else ""
            volume_sections += f"""
            <div class="volume-section">
                <h2>{cfg['description']}</h2>
                <div class="config-pills">
                    <span class="pill">Type: {cfg['volume_type']}</span>
                    <span class="pill">Size: {cfg['size_gib']} GiB</span>
                    <span class="pill">IOPS: {cfg['iops']:,}{tp_line}</span>
                </div>
                
                <h3>Results</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Category</th>
                            <th>Test</th>
                            <th>IOPS</th>
                            <th>BW (MB/s)</th>
                            <th>Lat p50 (µs)</th>
                            <th>Lat p99 (µs)</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                
                <details>
                    <summary>fio Commands</summary>
                    {commands_html}
                </details>
            </div>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EBS Performance Report — {self.region} — {ts}</title>
<style>
    :root {{
        --bg: #0d1117; --fg: #e6edf3; --card: #161b22; --border: #30363d;
        --accent: #58a6ff; --green: #3fb950; --yellow: #d29922; --red: #f85149;
        --purple: #bc8cff;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
           background: var(--bg); color: var(--fg); padding: 2rem; line-height: 1.6; }}
    .container {{ max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
    h2 {{ font-size: 1.4rem; margin-bottom: 1rem; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
    h3 {{ font-size: 1.1rem; margin: 1rem 0 0.5rem; }}
    .meta {{ color: #8b949e; margin-bottom: 2rem; }}
    .meta span {{ margin-right: 1.5rem; }}
    .config-box {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; margin-bottom: 2rem; }}
    .config-box dt {{ color: #8b949e; font-size: 0.85rem; }}
    .config-box dd {{ margin-bottom: 0.5rem; font-weight: 600; }}
    .volume-section {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; margin-bottom: 2rem; }}
    .config-pills {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }}
    .pill {{ background: #21262d; border: 1px solid var(--border); border-radius: 20px; padding: 0.2rem 0.8rem; font-size: 0.85rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 1rem; }}
    th {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 2px solid var(--border); font-size: 0.85rem; color: #8b949e; }}
    td {{ padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--border); }}
    td.num {{ font-family: 'SF Mono', 'Fira Code', monospace; text-align: right; }}
    .badge {{ padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }}
    .badge-iops {{ background: #1f3a5f; color: var(--accent); }}
    .badge-throughput {{ background: #1a3a2a; color: var(--green); }}
    .badge-latency {{ background: #3a2a1a; color: var(--yellow); }}
    .badge-mixed {{ background: #2a1a3a; color: var(--purple); }}
    details {{ margin-top: 1rem; }}
    summary {{ cursor: pointer; color: var(--accent); font-weight: 600; }}
    .cmd-block {{ background: #0d1117; border: 1px solid var(--border); border-radius: 6px; padding: 0.8rem; margin: 0.5rem 0; }}
    .cmd-label {{ font-size: 0.8rem; color: #8b949e; margin-bottom: 0.3rem; }}
    code {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.82rem; word-break: break-all; }}
    .footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); color: #8b949e; font-size: 0.85rem; }}
</style>
</head>
<body>
<div class="container">
    <h1>EBS Performance Test Report</h1>
    <div class="meta">
        <span>📍 {self.region}</span>
        <span>📅 {ts}</span>
        <span>⏱️ {duration_min:.1f} min total</span>
    </div>

    <div class="config-box">
        <h3>Test Environment</h3>
        <dl>
            <dt>Instance Type</dt><dd>{instance_type}</dd>
            <dt>fio Version</dt><dd>{fio_version}</dd>
            <dt>Test Mode</dt><dd>Raw block device (no filesystem)</dd>
            <dt>Runtime per Test</dt><dd>{RUNTIME_SECONDS}s + {RAMP_TIME}s ramp</dd>
            <dt>fio File Size</dt><dd>{FIO_FILE_SIZE}</dd>
        </dl>
    </div>

    {volume_sections}

    <div class="footer">
        Generated by <strong>ebs-bench.py</strong> | Tests: {len(FIO_TESTS)} per volume × {len(EBS_CONFIGS)} volumes
    </div>
</div>
</body>
</html>"""
        
        report_name = f"ebs-report-{self.region}-{self.start_time.strftime('%Y%m%d-%H%M%S')}.html"
        report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), report_name)
        with open(report_path, "w") as f:
            f.write(html)
        
        # Also save raw JSON
        json_path = report_path.replace(".html", ".json")
        json_data = {}
        for vol_name, vol_data in all_results.items():
            json_data[vol_name] = {
                "config": vol_data["config"],
                "tests": [{
                    "name": t["test"]["name"],
                    "label": t["test"]["label"],
                    "command": t["fio_command"],
                    "parsed": t["parsed"],
                } for t in vol_data["tests"]]
            }
        with open(json_path, "w") as f:
            json.dump(json_data, f, indent=2)
        self.log(f"  JSON saved to: {json_path}")
        
        return report_path


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="EBS Performance Benchmark Tool")
    parser.add_argument("--access-key", help="AWS Access Key ID")
    parser.add_argument("--secret-key", help="AWS Secret Access Key")
    parser.add_argument("--profile", help="AWS CLI profile name")
    parser.add_argument("--region", required=True, help="AWS Region")
    parser.add_argument("--runtime", type=int, default=60, help="fio runtime per test in seconds (default: 60)")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip cleanup (for debugging)")
    args = parser.parse_args()

    global RUNTIME_SECONDS
    RUNTIME_SECONDS = args.runtime

    bench = EBSBenchmark(
        region=args.region,
        access_key=args.access_key,
        secret_key=args.secret_key,
        profile=args.profile,
    )

    try:
        bench.run()
    except KeyboardInterrupt:
        print("\nInterrupted! Cleaning up...")
        bench.cleanup()
    except Exception as e:
        print(f"\nERROR: {e}")
        if not args.no_cleanup:
            bench.cleanup()
        raise


if __name__ == "__main__":
    main()
