# Lustre 文件列举测试（lfs find + 并行）

用 `lfs find <dir> -maxdepth 1`（lfs 层，直接 MDT 查询，可加过滤器）逐目录列举文件，
获取 名字/大小/时间，**64 并发**扫描后批量写入 CSV。

## 环境
- FSx for Lustre 2.15，SCRATCH_2 / 1200 GiB，us-east-2。
- 客户端：EC2 c5.2xlarge（AL2023，lfs 2.15.6）。
- 脚本：`lustre_ls_csv_parallel.py`（多进程并发，`-j` 指定并发数）。

## 测试结果（并发 64）

| 规模 | 目录数 | 并发 | 耗时 | 速率 |
|---|---|---|---|---|
| 10 万文件 | 781 | 64 | **16 s** | ~6400 files/s |
| 100 万文件 | 9,331 | 64 | **182 s（约 3 分钟）** | ~5700 files/s |

## 用法
```
python3 lustre_ls_csv_parallel.py -d /mnt/lustre/many1m -o out.csv -j 64
```
CSV 列：`name,dir,path,size_bytes,size_human,mtime_epoch,mtime_iso`

## 文件
- `lustre_ls_csv_parallel.py` — 并行列举脚本
- `lustre_ls_100k_par.csv` / `lustre_ls_1m_par.csv.gz` — 实测输出
