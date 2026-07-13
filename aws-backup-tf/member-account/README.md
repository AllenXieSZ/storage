# member-account — AWS Backup source-side resources

Run this in **every account** that owns Aurora clusters to be backed up.
(In the single-account test, the same account is also the management account.)

## Creates
| Resource | Detail |
|---|---|
| `aws_kms_key.vault_a` + alias `alias/org-aurora-vault-a` | Customer-managed key encrypting vault A (rotation on). A CMK is required for cross-account copy. |
| `aws_backup_vault.vault_a` | Local backup target `org-aurora-vault-a`. Name **must** match `target_backup_vault_name` in the org policy. |
| `aws_iam_role.backup` (`OrgAuroraBackupRole`) | Role AWS Backup assumes. Name **must** match the org policy's `$account` role ARN. |
| IAM policies | `AWSBackupServiceRolePolicyForBackup` + `...ForRestores` (managed) plus an inline policy for Aurora backup, local KMS read, destination KMS use, and `backup:CopyFromBackupVault`/`CopyIntoBackupVault`. |
| `aws_backup_global_settings.this` | Enables `isCrossAccountBackupEnabled = true` (org-level cross-account backup feature). |

## Variables
| Name | Default | Notes |
|---|---|---|
| `region` | `us-east-2` | |
| `vault_a_name` | `org-aurora-vault-a` | must match org policy |
| `backup_role_name` | `OrgAuroraBackupRole` | must match org policy |
| `management_account_id` | *(required)* | destination account owning vault B; scopes the destination KMS-use permission |
| `vault_b_name` | `org-aurora-vault-b` | destination vault name |
| `enable_cross_account_backup` | `true` | set false if it's managed elsewhere |

## Usage
```bash
terraform init
terraform apply -var="management_account_id=<ACCOUNT_ID>"
```

## Note on the cross-account backup global setting
`isCrossAccountBackupEnabled` is an **org-level** feature normally set from the
management / delegated-admin account. Because the test account is both member
and management, enabling it here is correct. If you split real accounts, set it
once from the management side and pass `enable_cross_account_backup=false` in
pure member accounts.
