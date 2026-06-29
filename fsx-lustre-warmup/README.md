# FSx for Lustre — S3 Warmup (HSM restore)

基于 [tzhu0704/s3warmup](https://github.com/tzhu0704/s3warmup) 的 `lustre_warmup.sh` 改造，
新增 `-f first_run` 参数，可在"首次全量预热"时跳过 identify 阶段，直接对全部文件 `lfs hsm_restore`。

## 用法
```bash
chmod +x lustre_warmup.sh

# 首次全量预热（默认 fast，跳过 identify，已 restore 的自动 no-op）
sudo ./lustre_warmup.sh -b -j 64 -d /mnt/lustre/yourdir

# 非首次（原版逻辑：先 lfs hsm_state 找 released 再 restore）
sudo ./lustre_warmup.sh -b -j 64 -f false -d /mnt/lustre/yourdir
```

## 参数
| 参数 | 说明 | 默认 |
|---|---|---|
| `-d DIR` | 目标目录（必填） | — |
| `-j JOBS` | 并行 job 数 | 32 |
| `-n SIZE` | 每个 hsm_restore 命令处理的文件数 | 5 |
| `-s SIZE` | 进度报告批大小 | 10000 |
| `-b` | 后台运行（nohup） | 关 |
| `-f true\|false` | **first_run**：true=跳过 identify 直接全量 restore | **true** |

## 相对原版的改动
- 新增 `-f first_run` 参数与对应的 if 分支（true 时 `cp all_files → released_files` 跳过 `lfs hsm_state` 判定阶段）
- `find` 扫描简化为一行（功能等价）
- restore 批处理抽成 `run_batch()` 函数去重（功能等价）
- 启动/完成日志标注 first_run
- identify 逻辑、并行 restore 机制、Progress 进度、成功/失败统计、`-b` 后台、大文件分批 —— 与原版一致

## 判定逻辑（identify，-f false 时）
对每个文件 `lfs hsm_state`，输出含 `released exists archived` 即视为需 restore。
已 restore 的文件状态无 `released`，会被跳过；`hsm_restore` 对已在本地的文件也是 no-op（AWS 官方）。

## 性能提示（实测，FSx Lustre 16-MDT）
- HSM restore 速率瓶颈为 MDT coordinator（per-MDT max_requests，FSx 托管不可调），
  单客户端约 85–170 文件/s，多客户端 ~4 台即饱和、总吞吐硬顶 ~345 文件/s。
- 与 metadata IOPS、存储容量/吞吐、客户端 RPC 调优均无关；唯一杠杆是加客户端（且很快饱和）。
- `-f true` 省的是 identify 判定时间，不改变 restore 本身的速率上限。

## 性能修复（重要）
原版（及早期本改版）的进度 monitor 每处理一个文件就对 success.txt/failed.txt 执行 `wc -l`，
当文件累积到百万级时形成 **O(n²)** 开销，导致 restore 表观速率随时间单调衰减（实测 333/s → 37/s）。
本版改为 **内存计数器**（monitor 循环内 `((SUCCESS++))`/`((FAILED++))`），消除该瓶颈。
排查依据：客户端 CPU/网络/Lustre 资源全程低利用率，瓶颈定位为脚本侧进度统计而非 FSx 服务端。
