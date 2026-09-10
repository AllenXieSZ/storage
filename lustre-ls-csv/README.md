# Lustre MDT-ls → CSV

用 `lfs find <dir> -maxdepth 1`（直接查 MDT，不走内核 VFS 逐项 stat）逐目录列举 Lustre
文件，把 **文件名 / 大小 / 时间先缓存在内存，最后一次性批量写入 CSV**。参数/日志风格参照
`fsx-lustre-warmup/lustre_warmup_v2.0`。

## 环境（2026-09-10 实测）
- FSx for Lustre 最小规格：**SCRATCH_2, 1200 GiB**（`fs-014e2e0f35faa9047`, MountName `ibhrrb4v`），us-east-2，与跳板机同子网 `subnet-0c551a33e366d52d4`。
- 客户端：跳板机 `i-0dffb881b2a90daa2`（Amazon Linux 2，**lfs 2.12.8**），SSM 驱动。
- 挂载：`mount -t lustre -o relatime,flock <dns>@tcp:/ibhrrb4v /mnt/lustre`

## 目录树（make_tree.sh）
每目录 5 子目录 + 10 文件（1M~10M 随机），共 **4 层深度**：
- ROOT(1) + L1(5) + L2(25) + L3(125) = **156 目录**，每目录 10 文件 = **1560 文件**。

## CSV 脚本（lustre_ls_csv.py）
```
python3 lustre_ls_csv.py -d /mnt/lustre/tree -o lustre_ls.csv
```
- `-d` 根目录（必填）、`-o` 输出 CSV、`-b` 进度报告批量。
- 流程：`os.walk` 收集全部目录 → 逐目录 `lfs find <dir> -maxdepth 1 -type f -printf '%p\t%s\t%A@'`
  （lfs 2.12 不支持 `-printf` 时自动回退到 `lfs find` + `os.stat`）→ 结果**先全部放内存 list**
  → 最后 `csv.writer` **一次性批量写盘**。
- CSV 列：`name,dir,path,size_bytes,size_human,mtime_epoch,mtime_iso`

## 实测结果
- 1560 文件 / 156 目录，扫描 **1.68s（~930 files/s）**，内存暂存后批量写 CSV（1561 行含表头）。

## 清理
Lustre 文件系统 `fs-014e2e0f35faa9047` + SG `sg-0b292e3df21c627d0`（测完删）；跳板机保留（仅卸载 /mnt/lustre）。
