# FSx for Lustre — DRA 关联与自动导出检查脚本 + S3 Versioning 实测

用一个脚本查清某个 Region 里所有 FSx for Lustre：**有没有关联 S3（DRA）**，**Lustre 上的改动会不会自动同步到 S3**。
另外实测：S3 开启 Versioning 后，自动导出时新增、覆盖、删除分别会在 S3 里留下什么。

- 区域：us-east-2 (Ohio)
- 测试日期：2026-10-09

## 1. 检查脚本 `fsx-lustre-dra-check.sh`

### 判断逻辑

"Lustre 的改动会不会同步到 S3" 只看 DRA 的 **AutoExportPolicy**：

| AutoExport 事件 | 结论 |
|---|---|
| NEW + CHANGED + DELETED | ✅ 完整同步 |
| 只开了一部分 | ⚠️ 部分同步 |
| 没开 | ❌ 已关联 S3，但 Lustre 的改动不会同步过去 |
| 没有 DRA | ❌ 未关联 S3 |
| 旧式关联（Scratch_1 / Persistent_1 创建时指定 ImportPath） | ⚠️ 不支持自动导出 |
| DRA 不是 AVAILABLE | ⚠️ 同步可能不生效 |

同时根据 AutoImport 标出方向：**双向 / 单向导出 / 单向导入**。一个文件系统有多个 DRA 时，每个 DRA 单独一行。

### 使用方法

```bash
# 依赖：aws cli v2 + jq
# IAM 权限：fsx:DescribeFileSystems, fsx:DescribeDataRepositoryAssociations
chmod +x fsx-lustre-dra-check.sh
./fsx-lustre-dra-check.sh us-east-2
```

### 输出示例

测试环境：4 个 PERSISTENT_2 文件系统（1.2 TiB，125 MB/s/TiB，Lustre 2.15），分别配成双向、单向导出、单向导入、不关联。

```
Region: us-east-2   Lustre 文件系统数量: 4

FileSystemId          DRA-Id                 DRA-Lifecycle  S3 Path                    AutoExport(Lustre->S3)  AutoImport(S3->Lustre)  结论
fs-0aaaaaaaaaaaaaaaa  dra-0aaaaaaaaaaaaaaaa  AVAILABLE      s3://<BUCKET>/bidir/       NEW,CHANGED,DELETED     NEW,CHANGED,DELETED     ✅ [双向] Lustre改动完整同步到S3(新增/修改/删除)
fs-0bbbbbbbbbbbbbbbb  dra-0bbbbbbbbbbbbbbbb  AVAILABLE      s3://<BUCKET>/export/      NEW,CHANGED,DELETED     NONE                    ✅ [单向导出] Lustre改动完整同步到S3(新增/修改/删除)
fs-0cccccccccccccccc  dra-0cccccccccccccccc  AVAILABLE      s3://<BUCKET>/import/      NONE                    NEW,CHANGED,DELETED     ❌ [单向导入] 已关联S3，但Lustre改动不会同步到S3
fs-0dddddddddddddddd  -                      -              -                          -                       -                       ❌ 未关联 S3

汇总（按文件系统）: 共 4 个 | 完整同步 2 | 部分同步 0 | 关联了但不导出 1 | 未关联 S3 1
```

（为便于阅读，上面省略了 Lifecycle、DeployType 两列，以及每行下面的 Lustre 路径和 Name。）

> ✅ 只表示策略配置正确，不代表没有导出积压。实际延迟要看 CloudWatch 指标 `AgeOfOldestQueuedMessage`。

## 2. S3 Versioning + 自动导出实测

### 测试内容

- bucket 开启 Versioning（`Status=Enabled`）
- 两个开了 AutoExport（NEW,CHANGED,DELETED）的路径：双向 `/bidir/`、单向导出 `/export/`
- 每个路径依次：新增 10 个文件 → 同名覆盖写一遍 → 删除其中 5 个
- 用 `s3-version-check.sh` 统计 S3 里的版本数和删除标记

### 结果（两个路径完全一致）

| 步骤 | S3 当前对象 | 版本数 | 删除标记 |
|---|---|---|---|
| 新增 file01–10 | 10 | 每个 1，共 10 | 0 |
| 同名覆盖 file01–10 | 10 | **每个 2，共 20** | 0 |
| 删除 file01–05 | 5（06–10） | 仍为 20 | **5**（01–05 的最新版本是删除标记） |

被删除的 file01.txt 版本列表：

```
版本 A  03:26:05  31B  内容 "v1 file01 ..."
版本 B  03:27:51  43B  内容 "v2 file01 ... overwritten"
删除标记  03:29:10  IsLatest=True
```

两个历史版本都能用 VersionId 取回原始内容。

### 结论

1. **每次修改都会在 S3 生成一个新版本**，旧内容保留为历史版本。
2. **删除只在 S3 加一个删除标记**，历史版本都在。删掉删除标记即可恢复。
3. 双向和单向导出表现相同。
4. Lustre 写完后约 **8–10 秒**，对象出现在 S3。
5. 文件频繁修改时历史版本会不断累积，建议给非当前版本配置 Lifecycle 过期规则。

## 3. 复现命令

```bash
REGION=us-east-2
SUBNET=<SUBNET_ID>; SG=<SG_ID>      # SG 需允许组内 TCP 988、1018-1023
BUCKET=<BUCKET>

# 4 个 PERSISTENT_2 文件系统（最小规格）
for n in bidir export-only import-only no-s3; do
  aws fsx create-file-system --region $REGION --file-system-type LUSTRE --file-system-type-version 2.15 \
    --storage-capacity 1200 --storage-type SSD --subnet-ids $SUBNET --security-group-ids $SG \
    --lustre-configuration DeploymentType=PERSISTENT_2,PerUnitStorageThroughput=125,DataCompressionType=NONE \
    --tags Key=Name,Value=dra-check-$n
done

# DRA（文件系统 AVAILABLE 后创建）
aws fsx create-data-repository-association --region $REGION --file-system-id <FS_BIDIR> \
  --file-system-path /bidir --data-repository-path s3://$BUCKET/bidir/ --batch-import-meta-data-on-create \
  --s3 'AutoImportPolicy={Events=[NEW,CHANGED,DELETED]},AutoExportPolicy={Events=[NEW,CHANGED,DELETED]}'
aws fsx create-data-repository-association --region $REGION --file-system-id <FS_EXPORT> \
  --file-system-path /export --data-repository-path s3://$BUCKET/export/ --batch-import-meta-data-on-create \
  --s3 'AutoExportPolicy={Events=[NEW,CHANGED,DELETED]}'
aws fsx create-data-repository-association --region $REGION --file-system-id <FS_IMPORT> \
  --file-system-path /import --data-repository-path s3://$BUCKET/import/ --batch-import-meta-data-on-create \
  --s3 'AutoImportPolicy={Events=[NEW,CHANGED,DELETED]}'

# 检查
./fsx-lustre-dra-check.sh $REGION

# 开启 versioning
aws s3api put-bucket-versioning --bucket $BUCKET --versioning-configuration Status=Enabled

# 客户端（AL2023，同 VPC，同 SG）挂载
sudo dnf install -y lustre-client
sudo mkdir -p /mnt/bidir /mnt/export
sudo mount -t lustre -o relatime,flock <FS_BIDIR_DNS>@tcp:/<MOUNTNAME> /mnt/bidir
sudo mount -t lustre -o relatime,flock <FS_EXPORT_DNS>@tcp:/<MOUNTNAME> /mnt/export

# 新增 → 覆盖 → 删除（每步之后等约 60 秒再查 S3）
for d in /mnt/bidir/bidir /mnt/export/export; do
  for i in $(seq -w 1 10); do echo "v1 file$i $(date +%s.%N)" > $d/file$i.txt; done; done
AWS_REGION=$REGION ./s3-version-check.sh $BUCKET bidir export

for d in /mnt/bidir/bidir /mnt/export/export; do
  for i in $(seq -w 1 10); do echo "v2 file$i $(date +%s.%N) overwritten" > $d/file$i.txt; done; done
AWS_REGION=$REGION ./s3-version-check.sh $BUCKET bidir export

for d in /mnt/bidir/bidir /mnt/export/export; do rm -f $d/file0{1..5}.txt; done
AWS_REGION=$REGION ./s3-version-check.sh $BUCKET bidir export

# 取回某个历史版本
aws s3api list-object-versions --bucket $BUCKET --prefix export/file01.txt
aws s3api get-object --bucket $BUCKET --key export/file01.txt --version-id <VERSION_ID> out.txt
```

## 文件

- `fsx-lustre-dra-check.sh` — DRA 关联 / 自动导出检查
- `s3-version-check.sh` — 按文件统计 S3 版本数和删除标记
