variable "region" {
  description = "AWS region where vault B and the org policy operate."
  type        = string
  default     = "us-east-2"
}

variable "vault_b_name" {
  description = "Name of centralized cross-account copy destination vault B (in the management account)."
  type        = string
  default     = "org-aurora-vault-b"
}

variable "vault_a_name" {
  description = "Name of member-account vault A (backup plan primary target). Must match the vault created in each member account."
  type        = string
  default     = "org-aurora-vault-a"
}

variable "backup_role_name" {
  description = "Name of the IAM role AWS Backup assumes in each account. Must match the role created in the member accounts."
  type        = string
  default     = "OrgAuroraBackupRole"
}

variable "backup_tag_key" {
  description = "Tag key used to select Aurora resources for backup."
  type        = string
  default     = "need_backup"
}

variable "backup_tag_value" {
  description = "Tag value used to select Aurora resources for backup."
  type        = string
  default     = "true"
}

variable "schedule_expression" {
  description = "Cron expression (UTC) for when backups start."
  type        = string
  default     = "cron(0 5 ? * * *)" # daily 05:00 UTC
}

variable "delete_after_days" {
  description = "Retention (days) for recovery points in both vault A and the vault B copy."
  type        = number
  default     = 35
}

variable "org_policy_name" {
  description = "Name of the AWS Organizations backup policy."
  type        = string
  default     = "org-aurora-backup-policy"
}
