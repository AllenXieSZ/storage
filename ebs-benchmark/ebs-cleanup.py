#!/usr/bin/env python3
"""
EBS Benchmark Cleanup Tool
Find and delete leftover EC2 instances, EBS volumes, Security Groups,
and IAM roles created by ebs-bench.py.

Usage:
    python3 ebs-cleanup.py --region us-east-2
    python3 ebs-cleanup.py --region us-east-2 --dry-run
    python3 ebs-cleanup.py --access-key AKIA... --secret-key ... --region us-east-2
"""

import argparse
import boto3
import time
import sys

TAG_NAME = "ebs-bench"
IAM_ROLE_NAME = "ebs-bench-ssm-role"
IAM_PROFILE_NAME = "ebs-bench-ssm-profile"


class EBSCleanup:
    def __init__(self, region, access_key=None, secret_key=None, profile=None, dry_run=False):
        session_kwargs = {"region_name": region}
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
        elif profile:
            session_kwargs["profile_name"] = profile

        self.session = boto3.Session(**session_kwargs)
        self.ec2 = self.session.client("ec2")
        self.iam = self.session.client("iam")
        self.region = region
        self.dry_run = dry_run
        self.found = 0
        self.deleted = 0

    def log(self, msg):
        prefix = "[DRY-RUN] " if self.dry_run else ""
        print(f"{prefix}{msg}", flush=True)

    def find_instances(self):
        """Find EC2 instances tagged with ebs-bench."""
        resp = self.ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [TAG_NAME]},
                {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
            ]
        )
        instances = []
        for res in resp["Reservations"]:
            for inst in res["Instances"]:
                instances.append({
                    "id": inst["InstanceId"],
                    "type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "launch": inst.get("LaunchTime", ""),
                    "sg_ids": [sg["GroupId"] for sg in inst.get("SecurityGroups", [])],
                })
        return instances

    def find_volumes(self):
        """Find EBS volumes tagged with ebs-bench-*."""
        resp = self.ec2.describe_volumes(
            Filters=[
                {"Name": "tag:Name", "Values": ["ebs-bench-*"]},
            ]
        )
        volumes = []
        for vol in resp["Volumes"]:
            name = ""
            for tag in vol.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            volumes.append({
                "id": vol["VolumeId"],
                "name": name,
                "state": vol["State"],
                "size": vol["Size"],
                "type": vol["VolumeType"],
                "attachments": vol.get("Attachments", []),
            })
        return volumes

    def find_security_groups(self):
        """Find security groups with ebs-bench in name."""
        resp = self.ec2.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": ["ebs-bench-*"]},
            ]
        )
        return [{"id": sg["GroupId"], "name": sg["GroupName"]} for sg in resp["SecurityGroups"]]

    def terminate_instances(self, instances):
        """Terminate EC2 instances."""
        if not instances:
            return
        ids = [i["id"] for i in instances]
        for inst in instances:
            self.log(f"  Terminating {inst['id']} ({inst['type']}, {inst['state']}, launched {inst['launch']})")
        if not self.dry_run:
            self.ec2.terminate_instances(InstanceIds=ids)
            self.log(f"  Waiting for termination...")
            waiter = self.ec2.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=ids)
            self.log(f"  ✅ {len(ids)} instance(s) terminated")
        self.deleted += len(ids)

    def delete_volumes(self, volumes):
        """Detach and delete EBS volumes."""
        for vol in volumes:
            self.log(f"  Deleting {vol['id']} ({vol['name']}, {vol['type']}, {vol['size']} GiB, {vol['state']})")
            if not self.dry_run:
                # Detach if attached
                for att in vol["attachments"]:
                    if att["State"] in ("attached", "attaching"):
                        try:
                            self.ec2.detach_volume(VolumeId=vol["id"], Force=True)
                            self.log(f"    Detaching from {att['InstanceId']}...")
                            time.sleep(10)
                        except Exception as e:
                            self.log(f"    Detach warning: {e}")
                # Wait for available then delete
                try:
                    for _ in range(30):
                        resp = self.ec2.describe_volumes(VolumeIds=[vol["id"]])
                        if resp["Volumes"][0]["State"] == "available":
                            break
                        time.sleep(5)
                    self.ec2.delete_volume(VolumeId=vol["id"])
                    self.log(f"    ✅ Deleted")
                except Exception as e:
                    self.log(f"    ❌ Delete failed: {e}")
            self.deleted += 1

    def delete_security_groups(self, sgs):
        """Delete security groups."""
        for sg in sgs:
            self.log(f"  Deleting SG {sg['id']} ({sg['name']})")
            if not self.dry_run:
                for attempt in range(6):
                    try:
                        self.ec2.delete_security_group(GroupId=sg["id"])
                        self.log(f"    ✅ Deleted")
                        break
                    except Exception as e:
                        if attempt < 5:
                            self.log(f"    Retrying in 10s... ({e})")
                            time.sleep(10)
                        else:
                            self.log(f"    ❌ Failed: {e}")
            self.deleted += 1

    def delete_iam_resources(self):
        """Delete IAM role and instance profile."""
        # Check if role exists
        try:
            self.iam.get_role(RoleName=IAM_ROLE_NAME)
        except self.iam.exceptions.NoSuchEntityException:
            return False

        self.log(f"  Cleaning IAM role: {IAM_ROLE_NAME}")
        self.log(f"  Cleaning IAM profile: {IAM_PROFILE_NAME}")

        if not self.dry_run:
            # Remove role from profile
            try:
                self.iam.remove_role_from_instance_profile(
                    InstanceProfileName=IAM_PROFILE_NAME, RoleName=IAM_ROLE_NAME
                )
            except Exception:
                pass
            # Delete profile
            try:
                self.iam.delete_instance_profile(InstanceProfileName=IAM_PROFILE_NAME)
            except Exception:
                pass
            # Detach policies
            try:
                self.iam.detach_role_policy(
                    RoleName=IAM_ROLE_NAME,
                    PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
                )
            except Exception:
                pass
            # Delete role
            try:
                self.iam.delete_role(RoleName=IAM_ROLE_NAME)
                self.log(f"    ✅ IAM cleaned up")
            except Exception as e:
                self.log(f"    ❌ IAM cleanup failed: {e}")

        self.deleted += 1
        return True

    def run(self):
        """Execute cleanup."""
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print(f"{'='*50}")
        print(f"EBS Benchmark Cleanup [{mode}]")
        print(f"Region: {self.region}")
        print(f"{'='*50}\n")

        # 1. Find EC2 instances
        print("🔍 Scanning EC2 instances...")
        instances = self.find_instances()
        if instances:
            self.found += len(instances)
            for i in instances:
                print(f"   Found: {i['id']} ({i['type']}, {i['state']})")
            self.terminate_instances(instances)
        else:
            print("   None found\n")

        # 2. Find EBS volumes
        print("🔍 Scanning EBS volumes...")
        volumes = self.find_volumes()
        if volumes:
            self.found += len(volumes)
            for v in volumes:
                print(f"   Found: {v['id']} ({v['name']}, {v['type']}, {v['size']}GiB, {v['state']})")
            self.delete_volumes(volumes)
        else:
            print("   None found\n")

        # 3. Find Security Groups
        print("🔍 Scanning Security Groups...")
        sgs = self.find_security_groups()
        if sgs:
            self.found += len(sgs)
            for sg in sgs:
                print(f"   Found: {sg['id']} ({sg['name']})")
            # Wait a bit after instance termination for ENI cleanup
            if instances and not self.dry_run:
                self.log("  Waiting 15s for ENI cleanup...")
                time.sleep(15)
            self.delete_security_groups(sgs)
        else:
            print("   None found\n")

        # 4. IAM Role & Profile
        print("🔍 Scanning IAM resources...")
        had_iam = self.delete_iam_resources()
        if not had_iam:
            print("   None found\n")

        # Summary
        print(f"\n{'='*50}")
        if self.found == 0:
            print("✅ No leftover ebs-bench resources found. All clean!")
        elif self.dry_run:
            print(f"🔍 Found {self.found} resource(s). Run without --dry-run to delete.")
        else:
            print(f"✅ Cleaned up {self.deleted} resource(s)")
        print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(description="EBS Benchmark Cleanup Tool")
    parser.add_argument("--access-key", help="AWS Access Key ID")
    parser.add_argument("--secret-key", help="AWS Secret Access Key")
    parser.add_argument("--profile", help="AWS CLI profile name")
    parser.add_argument("--region", required=True, help="AWS Region")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    args = parser.parse_args()

    cleanup = EBSCleanup(
        region=args.region,
        access_key=args.access_key,
        secret_key=args.secret_key,
        profile=args.profile,
        dry_run=args.dry_run,
    )
    cleanup.run()


if __name__ == "__main__":
    main()
