# ---------------------------------------------------------------------------
# IAM role that AWS Backup assumes in this (source/member) account.
# - Backs up Aurora clusters.
# - Reads the local vault A KMS key.
# - Performs the cross-account copy into the management account's vault B.
# The org backup policy references this role by name via the $account
# placeholder, so the role name MUST be identical across all org accounts.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "backup" {
  name = var.backup_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "backup.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Purpose = "aws-backup-org-aurora"
  }
}

# AWS managed policies for backup + restore. AWSBackupServiceRolePolicyForBackup
# includes backup:CopyFromBackupVault and backup:CopyIntoBackupVault, required
# for cross-account copy jobs.
resource "aws_iam_role_policy_attachment" "backup_service" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "restore_service" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

# Explicit permissions: backup Aurora (RDS cluster snapshots + tagging), read
# the local vault A KMS key, and use the destination vault B KMS key (in the
# management account) for cross-account copy re-encryption.
resource "aws_iam_role_policy" "backup_aurora_kms" {
  name = "AuroraBackupAndKmsAccess"
  role = aws_iam_role.backup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AuroraBackup"
        Effect = "Allow"
        Action = [
          "rds:DescribeDBClusters",
          "rds:DescribeDBClusterSnapshots",
          "rds:CreateDBClusterSnapshot",
          "rds:CopyDBClusterSnapshot",
          "rds:DeleteDBClusterSnapshot",
          "rds:ListTagsForResource",
          "rds:AddTagsToResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "KmsReadLocalVaultAKey"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:GenerateDataKey",
          "kms:CreateGrant",
          "kms:RetireGrant"
        ]
        Resource = [aws_kms_key.vault_a.arn]
      },
      {
        # Use the destination account's vault B KMS key when copying
        # cross-account. Scoped to the management account's KMS keys.
        Sid    = "KmsUseDestinationVaultBKey"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:GenerateDataKey",
          "kms:CreateGrant",
          "kms:RetireGrant"
        ]
        Resource = ["arn:${local.partition}:kms:${var.region}:${var.management_account_id}:key/*"]
      },
      {
        # Cross-account copy identity permissions (also required on the
        # destination vault's resource policy).
        Sid    = "CrossAccountCopy"
        Effect = "Allow"
        Action = [
          "backup:CopyFromBackupVault",
          "backup:CopyIntoBackupVault"
        ]
        Resource = "*"
      }
    ]
  })
}
