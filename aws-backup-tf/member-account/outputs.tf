output "vault_a_arn" {
  description = "ARN of backup vault A (local target)"
  value       = aws_backup_vault.vault_a.arn
}

output "vault_a_kms_key_arn" {
  description = "KMS key ARN encrypting vault A"
  value       = aws_kms_key.vault_a.arn
}

output "backup_role_arn" {
  description = "ARN of the AWS Backup IAM role"
  value       = aws_iam_role.backup.arn
}

output "backup_role_name" {
  description = "Name of the AWS Backup IAM role (must match org policy)"
  value       = aws_iam_role.backup.name
}

output "cross_account_backup_enabled" {
  description = "Whether the cross-account backup global setting was enabled"
  value       = var.enable_cross_account_backup
}
