variable "region" {
  description = "AWS region where the member-account backup vault and role are created."
  type        = string
  default     = "us-east-2"
}

variable "vault_a_name" {
  description = "Name of primary backup vault A. MUST match target_backup_vault_name in the org backup policy."
  type        = string
  default     = "org-aurora-vault-a"
}

variable "backup_role_name" {
  description = "Name of the IAM role AWS Backup assumes. MUST match the role name referenced in the org backup policy ($account placeholder)."
  type        = string
  default     = "OrgAuroraBackupRole"
}

variable "management_account_id" {
  description = "Management (destination) account ID that owns vault B. Used to grant this account's backup role permission to use the destination KMS key / copy cross-account."
  type        = string
}

variable "vault_b_name" {
  description = "Name of the destination vault B in the management account (for the cross-account copy permission ARN)."
  type        = string
  default     = "org-aurora-vault-b"
}

variable "enable_cross_account_backup" {
  description = "Enable the AWS Backup org-level cross-account backup feature (account/global setting)."
  type        = bool
  default     = true
}
