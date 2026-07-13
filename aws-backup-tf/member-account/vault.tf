data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

# ---------------------------------------------------------------------------
# Enable AWS Backup cross-account backup (org-level global setting).
#
# NOTE: This setting is managed from the AWS Organizations management account
# (or a delegated backup administrator account). In this test, the single
# account is BOTH member and management, so enabling it here is valid.
# ---------------------------------------------------------------------------
resource "aws_backup_global_settings" "this" {
  count = var.enable_cross_account_backup ? 1 : 0

  global_settings = {
    "isCrossAccountBackupEnabled" = "true"
  }
}

# ---------------------------------------------------------------------------
# KMS key for Vault A (new customer-managed key).
# A CMK is required so that recovery points can be copied cross-account
# (AWS-managed keys cannot be shared cross-account).
# ---------------------------------------------------------------------------
resource "aws_kms_key" "vault_a" {
  description             = "KMS key for AWS Backup vault A (${var.vault_a_name})"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "vault-a-key-policy"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowAWSBackupService"
        Effect    = "Allow"
        Principal = { Service = "backup.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
          "kms:CreateGrant"
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name    = "${var.vault_a_name}-key"
    Purpose = "aws-backup-org-aurora"
  }
}

resource "aws_kms_alias" "vault_a" {
  name          = "alias/${var.vault_a_name}"
  target_key_id = aws_kms_key.vault_a.key_id
}

# ---------------------------------------------------------------------------
# Backup Vault A (local backup target in the member account).
# ---------------------------------------------------------------------------
resource "aws_backup_vault" "vault_a" {
  name        = var.vault_a_name
  kms_key_arn = aws_kms_key.vault_a.arn

  tags = {
    Purpose = "aws-backup-org-aurora"
  }
}
