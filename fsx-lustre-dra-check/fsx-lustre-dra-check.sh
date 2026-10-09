#!/usr/bin/env bash
# 检查某个 Region 下所有 FSx for Lustre 是否关联了 S3（DRA），以及是否开启了自动导出（Lustre -> S3 同步）
# 用法: ./fsx-lustre-dra-check.sh <region>        例: ./fsx-lustre-dra-check.sh us-east-2
# 依赖: aws cli v2 + jq；权限: fsx:DescribeFileSystems, fsx:DescribeDataRepositoryAssociations
set -euo pipefail
REGION="${1:?用法: $0 <region>}"

FS_JSON=$(aws fsx describe-file-systems --region "$REGION" --output json \
  | jq '[.FileSystems[] | select(.FileSystemType=="LUSTRE")]')
FS_COUNT=$(jq 'length' <<<"$FS_JSON")
echo "Region: $REGION   Lustre 文件系统数量: $FS_COUNT"
[ "$FS_COUNT" -eq 0 ] && exit 0

printf '\n%-22s %-12s %-14s %-24s %-15s %-34s %-24s %-24s %s\n' \
  FileSystemId Lifecycle DeployType DRA-Id DRA-Lifecycle "S3 Path" "AutoExport(Lustre->S3)" "AutoImport(S3->Lustre)" 结论
printf '%.0s-' {1..210}; echo

SUM_NO_DRA=0; SUM_EXPORT_FULL=0; SUM_EXPORT_PART=0; SUM_EXPORT_NONE=0

for FS_ID in $(jq -r '.[].FileSystemId' <<<"$FS_JSON"); do
  FS=$(jq --arg id "$FS_ID" '.[]|select(.FileSystemId==$id)' <<<"$FS_JSON")
  FS_LC=$(jq -r '.Lifecycle' <<<"$FS")
  DEPLOY=$(jq -r '.LustreConfiguration.DeploymentType // "-"' <<<"$FS")
  NAME=$(jq -r '(.Tags // [])[]|select(.Key=="Name")|.Value' <<<"$FS" | head -1)

  # 旧式关联（Scratch_1 / Persistent_1 创建时指定 ImportPath/ExportPath，不走 DRA，不支持自动导出）
  LEGACY=$(jq -r '.LustreConfiguration.DataRepositoryConfiguration // empty
                  | "\(.ImportPath // "-")|\(.AutoImportPolicy // "NONE")|\(.Lifecycle // "-")"' <<<"$FS")

  DRAS=$(aws fsx describe-data-repository-associations --region "$REGION" \
           --filters Name=file-system-id,Values="$FS_ID" --output json \
         | jq '.Associations // []')
  N_DRA=$(jq 'length' <<<"$DRAS")

  if [ "$N_DRA" -eq 0 ]; then
    if [ -n "$LEGACY" ]; then
      IFS='|' read -r IMP AIP LLC <<<"$LEGACY"
      printf '%-22s %-12s %-14s %-24s %-15s %-34s %-24s %-24s %s\n' \
        "$FS_ID" "$FS_LC" "$DEPLOY" "(旧式关联,非DRA)" "$LLC" "$IMP" "不支持" "$AIP" "⚠️ 旧式关联，不能自动导出到S3"
      SUM_EXPORT_NONE=$((SUM_EXPORT_NONE+1))
    else
      printf '%-22s %-12s %-14s %-24s %-15s %-34s %-24s %-24s %s\n' \
        "$FS_ID" "$FS_LC" "$DEPLOY" "-" "-" "-" "-" "-" "❌ 未关联 S3"
      SUM_NO_DRA=$((SUM_NO_DRA+1))
    fi
    [ -n "$NAME" ] && echo "    Name=$NAME"
    continue
  fi

  FS_HAS_FULL=0; FS_HAS_PART=0
  while read -r D; do
    DID=$(jq -r '.AssociationId' <<<"$D")
    DLC=$(jq -r '.Lifecycle' <<<"$D")
    S3P=$(jq -r '.DataRepositoryPath' <<<"$D")
    FSP=$(jq -r '.FileSystemPath' <<<"$D")
    EXP=$(jq -r '(.S3.AutoExportPolicy.Events // []) | if length==0 then "NONE" else join(",") end' <<<"$D")
    IMP=$(jq -r '(.S3.AutoImportPolicy.Events // []) | if length==0 then "NONE" else join(",") end' <<<"$D")
    N_EXP=$(jq '(.S3.AutoExportPolicy.Events // []) | length' <<<"$D")
    N_IMP=$(jq '(.S3.AutoImportPolicy.Events // []) | length' <<<"$D")
    if   [ "$N_EXP" -gt 0 ] && [ "$N_IMP" -gt 0 ]; then DIR="双向"
    elif [ "$N_EXP" -gt 0 ]; then DIR="单向导出"
    elif [ "$N_IMP" -gt 0 ]; then DIR="单向导入"
    else DIR="无自动同步"; fi

    if [ "$DLC" != "AVAILABLE" ]; then
      VERDICT="⚠️ DRA 状态 $DLC，同步可能不生效"
    elif [ "$N_EXP" -eq 3 ]; then
      VERDICT="✅ [$DIR] Lustre改动完整同步到S3(新增/修改/删除)"; FS_HAS_FULL=1
    elif [ "$N_EXP" -gt 0 ]; then
      VERDICT="⚠️ [$DIR] 部分同步到S3(仅 $EXP)"; FS_HAS_PART=1
    else
      VERDICT="❌ [$DIR] 已关联S3，但Lustre改动不会同步到S3"
    fi
    printf '%-22s %-12s %-14s %-24s %-15s %-34s %-24s %-24s %s\n' \
      "$FS_ID" "$FS_LC" "$DEPLOY" "$DID" "$DLC" "$S3P" "$EXP" "$IMP" "$VERDICT"
    echo "    Lustre路径=$FSP${NAME:+   Name=$NAME}"
  done < <(jq -c '.[]' <<<"$DRAS")

  if   [ $FS_HAS_FULL -eq 1 ]; then SUM_EXPORT_FULL=$((SUM_EXPORT_FULL+1))
  elif [ $FS_HAS_PART -eq 1 ]; then SUM_EXPORT_PART=$((SUM_EXPORT_PART+1))
  else SUM_EXPORT_NONE=$((SUM_EXPORT_NONE+1)); fi
done

echo
echo "汇总（按文件系统）: 共 $FS_COUNT 个 | 完整同步 $SUM_EXPORT_FULL | 部分同步 $SUM_EXPORT_PART | 关联了但不导出 $SUM_EXPORT_NONE | 未关联 S3 $SUM_NO_DRA"
