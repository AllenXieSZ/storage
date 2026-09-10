# Lustre 2.15 提速测试 —— 关键结论（2026-09-10 实测）

**问题**：能否用 lfs 2.15 客户端 + `lfs find -printf` 提速文件列举（对比 2.10/lfs2.12 的串行 os.stat）？

**结论（实测，颠覆假设）**：
- ❌ **换 2.15 客户端 + `lfs find -printf` 本身几乎不提速**。
- ✅ **真正提速靠「并行」**：多进程并发 → 10万 71s→16s、100万 920s→182s，**快 5~7 倍**。

## 环境
- FSx for Lustre **2.15**（`fs-00a157c339fd994ec`，SCRATCH_2/1200GiB，MountName `lbabrb4v`）。
- 客户端：新建 EC2 `i-0910da3c209d5cfe4`（AL2023，**lfs 2.15.6，支持 `-printf`**，c5.2xlarge 8vCPU），SSM 驱动。
- 对照：之前 2.10 FS + 跳板机 lfs 2.12.8。

## ⭐ 根因实测（10 万文件，2.15 客户端）

| 方式 | 耗时 | 说明 |
|---|---|---|
| 只列**文件名**（`lfs find`，无属性） | **1.5 s** | 纯 MDT readdir，极快 |
| 名字 + **只 size**（`-printf %s`） | **112 s** | 取 size 要 OST glimpse |
| 名字 + **只 mtime**（`-printf %A@`） | **113 s** | 取 mtime 也要 OST glimpse |
| 名字 + size + mtime（`-printf %s %A@`） | **112 s** | 同上 |
| 逐目录串行（脚本 v1，2.15） | 123 s | 与上同量级 |

**结论**：只要取 **size 或 mtime 任一属性**，就必须对每个文件做 **OST glimpse RPC**（FSx Lustre 默认**未开 Size-on-MDT**，`llite.*.som` 不存在）→ 比纯列名慢 ~75 倍。**这跟 lfs 2.12/2.15、用不用 `-printf` 都无关** —— 瓶颈是"取属性必须问 OST"这个物理事实。

## ⭐ 提速方案：并行（lustre_ls_csv_parallel.py，-j 64）

| 规模 | 串行(v1) | **并行(v2, -j64)** | 加速比 | 速率 |
|---|---|---|---|---|
| 10 万 | 71~123 s | **16 s** | ~7x | 6432 files/s |
| 100 万 | 920 s (15.3min) | **182 s (3min)** | ~5x | 5681 files/s |

原理：glimpse 是 IO 等待型（每次等 OST 回 RPC，CPU 空闲），多进程并发把上百个 glimpse RPC 同时打出去，摊薄延迟。`-j` 可超配 CPU 核数（本例 8 核跑 64 worker）。

## 进一步提速方向（未测，供参考）
1. **只要文件名清单**（不要 size/mtime）→ `lfs find` 单条 1.5s 出 10 万，直接秒级。
2. **开 Size-on-MDT（SoM）** → size 存 MDT，`-printf %s` 不再问 OST（需服务端支持/开启；FSx 是否可配需查/实测）。
3. 更大 `-j` 或多客户端并行；`statahead_max` 调大。

## 文件
- `lustre_ls_csv_parallel.py` — 并行版（本轮提速主角）
- `lustre_ls_100k_par.csv` / `lustre_ls_1m_par.csv.gz` — 2.15 并行版输出
- 对照见 `SCALE_TEST_REPORT.md`（2.10/2.12 串行版）

## 清理
两套都要清：`fs-00a157c339fd994ec`(2.15) + `fs-014e2e0f35faa9047`(2.10) + EC2 `i-0910da3c209d5cfe4` + SG `sg-0b292e3df21c627d0`。跳板机保留。
