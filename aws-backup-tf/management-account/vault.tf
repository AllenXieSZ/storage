data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_organizations_organization" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  org_id     = data.aws_organizations_organization.current.id
  root_id    = data.aws_organizations_organization.current.roots[0].id
}

# ---------------------------------------------------------------------------
# KMS key for Vault B (new customer-managed key, cross-account copy target).
# Org member accounts are granted use of this key so they can copy (and
# re-encrypt) recovery points into vault B.
# ---------------------------------------------------------------------------
resource "aws_kms_key" "vault_b" {
  description             = "KMS key for AWS Backup vault B (${var.vault_b_name}) - cross-account copy destination"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "vault-b-key-policy"
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
      },
      {
        # Allow all accounts in the org to use this key when copying recovery
        # points into vault B (cross-account copy destination).
        Sid       = "AllowOrgAccountsCrossAccountCopy"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
          "kms:CreateGrant"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:PrincipalOrgID" = local.org_id
          }
        }
      }
    ]
  })

  tags = {
    Name    = "${var.vault_b_name}-key"
    Purpose = "aws-backup-org-aurora-crossaccount"
  }
}

resource "aws_kms_alias" "vault_b" {
  name          = "alias/${var.vault_b_name}"
  target_key_id = aws_kms_key.vault_b.key_id
}

# ---------------------------------------------------------------------------
# Backup Vault B (centralized cross-account copy destination).
# ---------------------------------------------------------------------------
resource "aws_backup_vault" "vault_b" {
  name        = var.vault_b_name
  kms_key_arn = aws_kms_key.vault_b.arn

  tags = {
    Purpose = "aws-backup-org-aurora-crossaccount"
  }
}

# ---------------------------------------------------------------------------
# Vault B access policy: allow the whole org to copy recovery points into it
# (resource-based policy required for cross-account backup copy).
# ---------------------------------------------------------------------------
resource "aws_backup_vault_policy" "vault_b" {
  backup_vault_name = aws_backup_vault.vault_b.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowOrgCrossAccountCopyIntoVaultB"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action    = ["backup:CopyIntoBackupVault"]
        Resource  = "*"
        Condition = {
          StringEquals = {
            "aws:PrincipalOrgID" = local.org_id
          }
        }
      }
    ]
  })
}
