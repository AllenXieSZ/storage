# Lustre 大规模文件列举耗时测试（lfs find -maxdepth 1 → CSV）

用 `lfs find <dir> -maxdepth 1`（逐目录、直接查 MDT）列举文件，**内存暂存 → 批量写 CSV**，
测不同规模下生成完整文件清单（名字/大小/时间）的耗时。

## 环境（2026-09-10 实测，us-east-2）
- FSx for Lustre 最小规格：**SCRATCH_2 / 1200 GiB**（`fs-014e2e0f35faa9047`，MountName `ibhrrb4v`）。
- 客户端：跳板机 `i-0dffb881b2a90daa2`（Amazon Linux 2，**lfs 2.12.8**，单客户端 numjobs=1），SSM 驱动。
- ⚠️ lfs 2.12.8 **不支持 `lfs find -printf`**，脚本自动回退到 `lfs find <dir> -maxdepth 1 -type f`（列路径，走 MDT）+ `os.stat`（取 size/mtime，会触发 OST glimpse）。这是当前客户端版本的真实表现；若换 lfs ≥2.13 用原生 `-printf` 走纯 MDT，会更快。

## 结果汇总

| 规模 | 目录数 | 文件大小 | 建文件耗时 | **列举+CSV 耗时** | 扫描速率 | CSV |
|---|---|---|---|---|---|---|
| 1,560 | 156 | 1~10 MiB | 秒级 | **1.7 s** | ~930 files/s | lustre_ls.csv |
| 100,000 | 781 | 4~64 KiB | ~52 s | **71.4 s** | ~1417 files/s | lustre_ls_100k.csv |
| 1,000,000 | 9,331 | 4~64 KiB | ~11.3 min | **920 s（15.3 min）** | ~1094 files/s | lustre_ls_1m.csv.gz |

- **100 万文件完整清单 ≈ 15 分钟**（单客户端、lfs 2.12 回退路径）。
- 速率大致线性（~1000~1400 files/s），瓶颈是**每文件一次 `os.stat`（OST glimpse RPC）**，不是内存或 CSV 写入（CSV 批量写 100 万行仅 6 s）。
- 内存暂存 100 万条记录无压力；最后一次性 `csv.writer` 批量写盘。

## 提速方向（未在本轮验证，供参考）
1. **换 lfs ≥ 2.13 用 `lfs find -printf '%p\t%s\t%A@'`**：size/mtime 直接从 MDT 拿，省掉每文件 os.stat 的 OST glimpse，预计显著加速。
2. **多客户端/多进程并行**（本轮 numjobs=1）：按目录分片并行扫描，单 MDT 也能并发多 RPC。
3. `lctl set_param llite.*.statahead_max=8192` 提高元数据预取。

## 文件
- `make_tree.sh` — 4 层小树（每目录 5 子目录 + 10 文件，1~10M）
- `make_many.sh` — N 层骨架 + 指定数量小文件（4~64K）均匀撒入
- `lustre_ls_csv.py` — 逐目录 `lfs find -maxdepth 1` → 内存暂存 → 批量 CSV
- `lustre_ls*.csv` — 各规模实测输出（1M 为 .gz）

## 清理
Lustre `fs-014e2e0f35faa9047` + SG `sg-0b292e3df21c627d0` 测完删；跳板机保留（仅卸载 /mnt/lustre）。
