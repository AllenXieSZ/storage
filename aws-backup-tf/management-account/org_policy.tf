# ---------------------------------------------------------------------------
# AWS Organizations backup policy (created in the management account).
#
# Applied at the org root so every account in the org receives the effective
# policy. Each account backs up its Aurora clusters tagged
# need_backup=true into vault A (local), then copies the recovery point
# cross-account into the management account's vault B.
#
# The $account placeholder is resolved per-account by AWS Organizations, so
# the IAM role and vault A must exist (same names) in every account. The
# vault B copy destination is hard-referenced to the management account id so
# all accounts copy into the SAME central vault B.
# ---------------------------------------------------------------------------

locals {
  backup_policy = {
    plans = {
      (var.org_policy_name) = {
        regions = {
          "@@assign" = [var.region]
        }
        rules = {
          "AuroraDailyToVaultA" = {
            schedule_expression            = { "@@assign" = var.schedule_expression }
            target_backup_vault_name       = { "@@assign" = var.vault_a_name }
            start_backup_window_minutes    = { "@@assign" = "60" }
            complete_backup_window_minutes = { "@@assign" = "10080" }
            lifecycle = {
              delete_after_days = { "@@assign" = tostring(var.delete_after_days) }
            }
            copy_actions = {
              # Cross-account copy destination = management account vault B.
              # Per AWS backup-policy syntax, the copy_actions key name must
              # equal the target_backup_vault_arn value.
              ("arn:${local.partition}:backup:${var.region}:${local.account_id}:backup-vault:${var.vault_b_name}") = {
                target_backup_vault_arn = {
                  "@@assign" = "arn:${local.partition}:backup:${var.region}:${local.account_id}:backup-vault:${var.vault_b_name}"
                }
                lifecycle = {
                  delete_after_days = { "@@assign" = tostring(var.delete_after_days) }
                }
              }
            }
          }
        }
        # Use the "resources" selection form so we can filter BOTH by resource
        # type (Aurora/RDS clusters) AND by tag need_backup=true. The "tags"
        # selection form does not support resource_types.
        selections = {
          resources = {
            "AuroraTagSelection" = {
              iam_role_arn = {
                "@@assign" = "arn:${local.partition}:iam::$account:role/${var.backup_role_name}"
              }
              resource_types = {
                "@@assign" = ["arn:${local.partition}:rds:*:*:cluster:*"]
              }
              conditions = {
                string_equals = {
                  "NeedBackupTag" = {
                    condition_key   = { "@@assign" = "aws:ResourceTag/${var.backup_tag_key}" }
                    condition_value = { "@@assign" = var.backup_tag_value }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

resource "aws_organizations_policy" "backup" {
  name        = var.org_policy_name
  description = "Org backup policy: Aurora tagged ${var.backup_tag_key}=${var.backup_tag_value} -> vault A, cross-account copy to mgmt vault B"
  type        = "BACKUP_POLICY"
  content     = jsonencode(local.backup_policy)
}

resource "aws_organizations_policy_attachment" "backup_root" {
  policy_id = aws_organizations_policy.backup.id
  target_id = local.root_id
}
