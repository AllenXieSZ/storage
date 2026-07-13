# AWS Backup Org — Aurora cross-account backup (split Terraform)

Two independent Terraform stacks implementing org-wide AWS Backup for Aurora,
split by the account role they run in.

## Architecture

```
                 MEMBER ACCOUNT(s)                      MANAGEMENT ACCOUNT
 ┌──────────────────────────────────────┐   ┌────────────────────────────────────┐
 │ KMS key (vault A)                     │   │ KMS key (vault B)                  │
 │ Backup vault A  (local target)        │   │ Backup vault B (central copy dest) │
 │ IAM role OrgAuroraBackupRole          │   │ Vault B access policy (org-wide)   │
 │ Enable cross-account backup (global)  │   │ Org BACKUP_POLICY -> root (r-...)  │
 └──────────────────────────────────────┘   └────────────────────────────────────┘
          │  daily snapshot                            ▲
          ▼                                            │ cross-account copy
     vault A ───────────────────────────────────────► vault B
```

Backup plan (defined by the org policy, executed in each account):
1. Select **Aurora / RDS clusters** (`arn:aws:rds:*:*:cluster:*`) tagged **`need_backup=true`**.
2. Daily 05:00 UTC → snapshot into local **vault A** (35-day retention).
3. Cross-account copy into the management account's **vault B** (35-day retention).

## Directories
| Dir | Runs in | Creates |
|---|---|---|
| [`member-account/`](./member-account) | every account that has Aurora to back up | KMS key + vault A, IAM role `OrgAuroraBackupRole`, enable cross-account backup |
| [`management-account/`](./management-account) | org management (or delegated admin) account | KMS key + vault B + vault access policy, org backup policy attached to root |

## Deploy order
1. **member-account** first (creates the role + vault A the org policy references):
   ```bash
   cd member-account
   terraform init
   terraform apply -var="management_account_id=<MGMT_ACCOUNT_ID>"
   ```
2. **management-account** second:
   ```bash
   cd ../management-account
   terraform init
   terraform apply
   ```

> In this test the SAME account is both member and management, so both stacks
> run against one account. In a real org, run `member-account` in every member
> account (e.g. via a CloudFormation StackSet or a per-account Terraform run)
> and `management-account` once in the mgmt account.

## Prerequisites
- AWS Organizations with **all features** enabled and the **BACKUP_POLICY** policy type enabled at the org root.
- Aurora opt-in enabled in AWS Backup region settings (default on).
- Credentials with Organizations + Backup + KMS + IAM permissions.

## Tested
Applied and verified in account `<ACCOUNT_ID>` (us-east-2, org `<ORG_ID>`, root `<ROOT_ID>`):
- `isCrossAccountBackupEnabled = true`
- Org policy `p-89uxxhmzm3` attached to root `<ROOT_ID>`
- vault A + vault B each with their own CMK
- IAM role `OrgAuroraBackupRole`

## Teardown
`terraform destroy` in each dir (management-account first, then member-account). KMS keys have a 7-day deletion window.
