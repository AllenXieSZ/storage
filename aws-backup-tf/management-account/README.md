# management-account — AWS Backup destination + org policy

Run this **once** in the AWS Organizations management account (or a delegated
backup administrator account).

## Creates
| Resource | Detail |
|---|---|
| `aws_kms_key.vault_b` + alias `alias/org-aurora-vault-b` | Customer-managed key encrypting vault B. Org accounts (`aws:PrincipalOrgID`) are granted use for cross-account copy re-encryption. |
| `aws_backup_vault.vault_b` | Centralized cross-account copy destination `org-aurora-vault-b`. |
| `aws_backup_vault_policy.vault_b` | Resource-based policy allowing `backup:CopyIntoBackupVault` from any account in the org. |
| `aws_organizations_policy.backup` | Org `BACKUP_POLICY` document. |
| `aws_organizations_policy_attachment.backup_root` | Attaches the policy to the org **root**. |

## The backup policy
- Selection: `resources` form — resource type `arn:aws:rds:*:*:cluster:*` (Aurora/RDS clusters) **AND** tag `need_backup=true` (via `conditions.string_equals`).
- Rule: daily `cron(0 5 ? * * *)` → `target_backup_vault_name = org-aurora-vault-a`, retention 35 days.
- `copy_actions` → cross-account copy to `arn:aws:backup:<region>:<mgmt-account>:backup-vault:org-aurora-vault-b`, retention 35 days.
- `iam_role_arn` uses the `$account` placeholder → `arn:aws:iam::$account:role/OrgAuroraBackupRole`.

> Why the `resources` selection (not `tags`): AWS backup-policy syntax does not
> allow `resource_types` inside a `tags` selection. To filter by BOTH resource
> type and tag you must use the `resources` form with `conditions`.

## Variables
| Name | Default |
|---|---|
| `region` | `us-east-2` |
| `vault_b_name` | `org-aurora-vault-b` |
| `vault_a_name` | `org-aurora-vault-a` |
| `backup_role_name` | `OrgAuroraBackupRole` |
| `backup_tag_key` / `backup_tag_value` | `need_backup` / `true` |
| `schedule_expression` | `cron(0 5 ? * * *)` |
| `delete_after_days` | `35` |
| `org_policy_name` | `org-aurora-backup-policy` |

## Usage
```bash
terraform init
terraform apply
```

## Prerequisites
- AWS Organizations with all features enabled and **BACKUP_POLICY** policy type enabled at the root.
- The member-account stack (vault A + `OrgAuroraBackupRole`) must exist in each account for the policy to actually run there.
