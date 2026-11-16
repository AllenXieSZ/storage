# du -sm：FSx Lustre 2.15.6 客户端 vs 本地 xfs 实测结果

测试时间：2026-11-16（us-east-2）
脚本：[`scripts/`](./scripts/)（s0 环境、s1/s1b st_blocks 稳定性、s2/s2b 单文件、s3 目录级、s4 symlink）

---

## 0. 环境（已实测）

| 项 | 值 |
|---|---|
| FSx | FSx for Lustre PERSISTENT_2，125 MB/s/TiB，1200 GiB，DataCompression=NONE |
| 服务端版本 | OST import `target_version: 2.15.8.0` |
| **OST 数量** | **只有 1 个（OST0000），MDT 1 个** → PFL 的 8/16/32 条带全部被压成 stripe_count=1 |
| PFL 默认 layout | 0–100MB c=1；100MB–10GB c=8；10–100GB c=16；100GB+ c=32；stripe_size 1MiB 全部一致 |
| DoM | 没有（第一个组件就在 OST 上，`dom_read_open` 不存在） |
| 客户端 | AL2023，kernel 6.18.62-127.179.amzn2023.x86_64，`lustre-client-2.15.6-35.amzn2023`，`lctl version=2.15.6` |
| 挂载 | `mount -t lustre -o relatime,flock <FS_DNS>@tcp:/<MOUNT_NAME> /mnt/lustre` → 生效选项 `rw,relatime,seclabel,checksum,flock,nouser_xattr,lruresize,lazystatfs,nouser_fid2path,verbose,encrypt` |
| OSC grant 参数 | `grant_block_size: 262144`，`grant_inode_size: 4096`，`grant_extent_tax: 655360`，`max_brw_size 1MiB` |
| 本地盘 | 独立 250 GiB gp3 EBS，`mkfs.xfs` 默认参数（bsize=4096、reflink=1、crc=1），挂 /mnt/xfs |
| EC2 | m6i.2xlarge（客户端规格不影响 du 结果） |

数据统一用 `dd if=/dev/urandom` 先写到 xfs，再 `cp`/`cp -a` 到 Lustre，两边字节内容完全一致（抽查 md5 一致）。

---

## 1. st_blocks 稳定性（已实测，最重要的方法学发现）

### 1.1 10 MiB 文件（写完后在**写入客户端**上 stat）

| 时点 | st_blocks（rep1 / rep2） |
|---|---|
| 写完立即 | **1 / 1** |
| sync 后 | 1 / 1 |
| sync + drop_caches 3 | 1 / 1 |
| +5s / 10s / 30s / 60s / 120s / **300s** | **全部 1 / 1** |
| umount + remount | **20513 / 20513**（正确值） |

### 1.2 1 GiB 文件

| 时点 | st_blocks |
|---|---|
| 写完立即 / sync / drop_caches / +30s | 1732194（只有正确值的 82.6%） |
| umount+remount（第 1 次、第 2 次） | 2097922 / 2097922 |

### 1.3 "写完多久 remount 才准"（每个文件：dd 10M → sync → sleep X → remount）

| X | 首次 remount | +10s 再 remount | +70s 再 remount |
|---|---|---|---|
| 0s | **1** ❌ | 20513 | 20513 |
| 2s | **1** ❌ | 20513 | 20513 |
| 5s | 20513 | 20513 | 20513 |
| 10/20/40s | 20513 | 20513 | 20513 |

另外：dd 后不 sync 直接 remount，**连续两次 remount 都还是 1**，过几分钟再读才变成 20513。

### 1.4 不 umount 能不能刷新？
`lctl set_param ldlm.namespaces.*.lru_size=clear`（丢弃客户端缓存的 DLM 锁）之后**立刻**得到 20513（已实测）。所以生产环境里不 umount 也能拿到准确的 du。

### 1.5 结论（已实测）
- 写入客户端上，刚写完的文件 st_blocks **偏小**（1 或者真实值的约 80%），**sync、drop_caches、等 300s 都不会自己刷新**。如果刚写完马上 du，就会得到偏小的结果。
- 要拿到准确值，需要：**sync → 等 ≥5s → umount+remount**（或者 `ldlm lru_size=clear`）。服务端提交大概要 2–5s，太早 remount 会拿到旧值。
- 稳定之后，再 remount 1 次、等 60s 后再 remount，数值完全不变（§2/§3 都做了二次 remount 验证，每个文件都一致）。
- 后面所有测量都用 `sync; sleep 30; remount; sleep 5; remount`（`scripts/common.sh` 里的 `stable_remount`）之后再 du。
- 推测（未实测）：缓存值来自 OST extent 锁的 LVB，只要锁不被释放，客户端就一直用旧的 blocks。lru clear 立刻生效这一点支持这个推测，但我没有看源码确认。其他客户端（没写这个文件的）读到的是不是正确值，也没测。

---

## 2. 单文件对照（stable_remount 之后，单位见列名）

| 文件大小 | xfs du -sm | Lustre du -sm | xfs KiB（st_blocks/2） | Lustre KiB | Lustre 多出 | 比例 |
|---|---|---|---|---|---|---|
| 1 KiB | 1 | 1 | 4 | 12.5 | +8.5 KiB | 3.1× |
| 10 KiB | 1 | 1 | 12 | 24.5 | +12.5 KiB | 2.04× |
| 100 KiB | 1 | 1 | 100 | 136.5 | +36.5 KiB | 1.37× |
| 512 KiB | 1 | 1 | 512 | 528.5 | +16.5 KiB | +3.2% |
| 1 MiB | 1 | **2** | 1024 | 1040.5 | +16.5 KiB | +1.6% |
| 1,000,001 B | 1 | **2** | 980 | 1040.5 | +60.5 KiB | +6.2% |
| 10 MiB | 10 | 11 | 10240 | 10256.5 | +16.5 KiB | +0.16% |
| 100 MiB | 100 | 101 | 102400 | 102448.5 | +48.5 KiB | +0.047% |
| 1 GiB | 1024 | 1025 | 1048576 | 1048961 | +385 KiB | +0.037% |
| 10 GiB | 10240 | 10244 | 10485760 | 10489313 | +3553 KiB | +0.034% |

`--apparent-size` 两边完全相同。所有文件 `lfs getstripe -c` 都是 1（因为只有 1 个 OST），stripe_size 1 MiB。
注意：单个文件 `du -sm` 是向上取整到 MiB 的，所以 1 MiB 文件在 Lustre 上显示 2，只是多出 16.5 KiB 被进位了。

### 2.1 细粒度探测：Lustre 的 st_blocks 分配规律（已实测）

| 字节数 | Lustre KiB | 规律 |
|---|---|---|
| 0 | 0.5 | 空文件也有 1 个 512B 块 |
| 1 / 512 / 4096 | 12.5 | 4 KiB + 8.5 |
| 8192 / 16K / 32K / 64K / 128K | 每档 = 按 4K 取整 + **8.5 KiB** | **≤128 KiB：按 4 KiB 取整 + 固定 8.5 KiB** |
| 131073（128K+1） | 264.5 | 跳到 256K + 8.5 |
| 262144 | 264.5 | 256K + 8.5 |
| 262145 | 528.5 | 512K + 16.5 |
| 524289 | 784.5 | 768K + 16.5 |
| 1048575 / 1048577 | 1040.5 / 1296.5 | 1024K / 1280K + 16.5 |
| 2M / 2M+1 / 3M / 4M / 8M / 16M | 按 **256 KiB 取整 + 16.5 KiB** | **>128 KiB：按 256 KiB 取整** |
| 32M / 64M | +24.5 / +32.5 | 固定开销随大小慢慢增长 |
| 100M+1 B | 102477 | 跨 PFL 100MB 边界 → 多一个 OST 对象（4K+8.5） |
| 200M / 500M / 1G / 10G | +97 / +201 / +385 / +3553 KiB | 大文件约 **+0.034–0.037%** |

其他实测：
- 在 100 KiB×100 次追加写出来的 10,240,000 B 文件 = 10256.5 KiB，和一次性写一样（按 256K 取整：10000K 向上取整到 10240K，再 +16.5）
- 原地覆盖写 8 MiB 文件：16417 块，没有变化
- 稀疏文件（truncate 1G，只写 1 MiB）：2098 块 = 1049 KiB，只算实际写入的部分
- 目录：Lustre 每个目录 50 块（25 KiB，size=25600），xfs 小目录是 0 块（inline）
- symlink：Lustre **每个 10 块（5 KiB）**，xfs 0 块；1000 个 symlink：Lustre du 5145 KiB，xfs 44 KiB

**推测（未实测）**：这些规律（小文件按 4K 用单块，超过 128K 后整个文件改成固定 256K 块，大文件约 0.034% 的递增开销像间接块，`grant_block_size=262144`）和 ZFS OST 后端（recordsize≈256K）的行为非常吻合。AWS 文档里没写 FSx 用的是什么后端，这一点只是我根据数据做的猜测。

---

## 3. 目录级（模拟 HF 缓存，stable_remount 之后；+60s 再 remount 数值完全不变）

| 场景 | 文件数 | apparent du -sm（两边一样） | xfs du -sm | Lustre du -sm | 差 | 比例 |
|---|---|---|---|---|---|---|
| A：10×10GiB + 50 个小文件（294B–98KB，平均 39 KB） | 60 | 102402 | 102402 | **102438** | +36 MB | **+0.035%** |
| B：10×10GiB + 5000 个小文件（33B–100KB，平均 51 KB） | 5010 | 102646 | 102656 | **102839** | +183 MB | **+0.178%** |
| C：10000 × 10 KiB | 10000 | 98 / 100* | 118 | **241** | +123 MB | **2.04×** |

*C 场景的 apparent 不一样，是因为 Lustre 目录 size=25600 B，和 xfs 的目录 size 不同。

KiB 级拆分：

| 场景 | 部分 | xfs KiB | Lustre KiB | 差 |
|---|---|---|---|---|
| A | 10 个大文件 | 104,857,600 | 104,893,155 | +35,555（每个 10G 文件 +3555.5，和单文件测试一致） |
| A | 50 个小文件 | 2,024 | 3,322 | +64% |
| B | 10 个大文件 | 104,857,600 | 104,893,155 | +35,555 |
| B | 5000 个小文件 | 261,464 | 413,245 | **+58%（+148 MiB）** |
| C | 10000 个小文件 | 120,000 | 245,000 | 每个文件 12 KiB → 24.5 KiB |

和 §2 单文件模型对得上：**大文件 +0.034%；每个小文件 +8.5 KiB，再加 4K 取整**（100 KiB 那档 = 100 + 8.5 + 4K 取整 ≈ 136.5）。

---

## 4. 结论（数据驱动）

1. **st_blocks 稳定之后，Lustre 的 `du -sm` 一律比 xfs 大，从来没有偏小过**（所有大小、所有场景、二次 remount 结果都一样）。写完立即 du 会因客户端缓存的 st_blocks 而偏小（见 §1），属于测量方法问题。
2. **差多少取决于文件大小分布：**
   - 大文件（≥1 GiB）：**+0.034%–0.037%**
   - 10–100 MiB：+0.05%–0.16%
   - 128 KiB–1 MiB：+1.6%–6%（按 256 KiB 取整 + 16.5 KiB）
   - ≤128 KiB 小文件：每个固定 **+8.5 KiB**（再加 4K 取整），10 KiB 文件就是 2×，1 KiB 文件 3×
   - 每个目录 +25 KiB，每个 symlink +5 KiB（xfs 都是 0）
3. **根因（已实测的部分）**：是 OST 上的对象分配方式和元数据开销造成的，**和条带对齐无关**：
   - 本次所有文件都是 stripe_count=1（只有 1 个 OST），差异照样存在
   - stripe_size 1 MiB 的边界上也没有对应的跳变；跳变出现在 **128 KiB** 和 **256 KiB 粒度**
   - 不是 st_blocks 的 bug：稳定后多次 remount 数值完全一致，且符合规律
4. **本次测试的局限**：测试 FS 只有 1 个 OST，PFL 的多条带布局全部退化为 stripe_count=1，**多 OST / 多条带下每个对象的固定开销是否被放大，本次未测**。
   - 推测（未实测）：在多 OST 的 FS 上，>100MB 的文件会被 PFL 切成 8/16/32 个 OST 对象，每个对象各有 8.5–16.5 KiB 开销和 256K 尾部取整，差异可能比本次更大。
   - 如需评估某个真实目录，可在该目录上按文件类型/大小分档统计 apparent 与实际分配：`find <dir> -printf '%y %s %b
'`。
5. **实用建议**：比较容量请用 `du -sm --apparent-size`（两边完全一致）。看 Lustre 真实占用，先 `lctl set_param ldlm.namespaces.*.lru_size=clear`（或 remount），否则刚写完的数据会被低估。

---

## 5. 资源清理
- 测试数据、测试 EC2（含 EBS）已全部删除；FSx 文件系统保留。

## 6. 复现方法
```bash
export FS_DNS=<fs-xxx.fsx.<region>.amazonaws.com> MOUNT_NAME=<mountname>
# 客户端：AL2023 + lustre-client 2.15.6；另挂一块空 EBS 做 xfs（s0.sh 会对 250G 盘 mkfs.xfs）
bash scripts/s0.sh          # 环境信息 + 挂载
bash scripts/s1.sh          # st_blocks 稳定性（立即/sync/drop_caches/等待/remount）
bash scripts/s1b.sh         # remount 前等待时间、ldlm lru clear
bash scripts/s2.sh          # 单文件对照 1K–10G
bash scripts/s2b.sh         # 字节级分配规律、稀疏/覆盖/追加写
bash scripts/s3run.sh       # 目录级场景 A/B/C
bash scripts/s4.sh          # symlink；结束时清理测试数据
```
所有测量前都执行 `stable_remount`（`sync; sleep 30; remount; sleep 5; remount`）。
