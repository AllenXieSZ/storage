output "vault_b_arn" {
  description = "ARN of centralized cross-account vault B"
  value       = aws_backup_vault.vault_b.arn
}

output "vault_b_kms_key_arn" {
  description = "KMS key ARN encrypting vault B"
  value       = aws_kms_key.vault_b.arn
}

output "org_backup_policy_id" {
  description = "ID of the AWS Organizations backup policy"
  value       = aws_organizations_policy.backup.id
}

output "org_backup_policy_attached_to" {
  description = "Org root the backup policy is attached to"
  value       = aws_organizations_policy_attachment.backup_root.target_id
}

output "management_account_id" {
  description = "Management account ID (owner of vault B)"
  value       = local.account_id
}
