# EFS 弹性吞吐模式 — 单文件写入延迟测试

在 Amazon EFS（Elastic Throughput 弹性吞吐模式）上，用一台 c7i.4xlarge EC2 按官方 user guide 挂载，测试往 EFS 写一个 **200 MiB** 文件时，不同 `pwrite()` I/O size 下的**整体写入总时间**与**每次 pwrite 的平均延迟**。

I/O size 取 5 档：**512K / 1M / 2M / 4M / 8M**。

---

## 测试环境

| 项目 | 配置 |
|------|------|
| 存储 | Amazon EFS，**Elastic Throughput（弹性吞吐）**，General Purpose 性能模式，加密 |
| EFS ID | fs-045bbde273186f931 |
| 挂载方式 | 官方 EFS mount helper：`sudo mount -t efs -o tls fs-xxx:/ /mnt/efs` |
| 挂载参数（实际生效） | nfs4，vers=4.1，rsize=1048576，wsize=1048576，hard，noresvport，proto=tcp，timeo=600，retrans=2，传输加密（TLS，stunnel 本地 127.0.0.1 代理） |
| 客户端工具 | amazon-efs-utils 3.3.2 |
| EC2 实例 | c7i.4xlarge（16 vCPU / 30 GiB） |
| 区域 / 可用区 | us-east-2（Ohio），us-east-2a（EC2 与 EFS 挂载点同 AZ） |
| 操作系统 | Amazon Linux 2023.12（内核 6.18.51-120.162.amzn2023.x86_64） |
| 文件大小 | 200 MiB |
| I/O size | 512K / 1M / 2M / 4M / 8M |
| 每档轮次 | 3 轮，取最优（min total）+ 3 轮均值 |
| 落盘方式 | 全部 pwrite 完成后 `fsync()` 强制刷到 EFS，单独计时 |

---

## 性能对比结果

> `total` = 写完整个 200MiB 文件的墙钟时间（含所有 pwrite + 最后一次 fsync）
> `avg pwrite` = 每次 `pwrite()` 调用的平均延迟
> `fsync` = 最后一次 fsync 落盘耗时（占 total 的绝大部分）

| I/O size | pwrite 次数 | 最优总时间 (ms) | 3轮均值总时间 (ms) | 平均 pwrite 延迟 (ms) | p50 (ms) | p99 (ms) | max (ms) | fsync (ms) | 吞吐 (MB/s) |
|:--------:|:----------:|:--------------:|:-----------------:|:--------------------:|:--------:|:--------:|:--------:|:---------:|:----------:|
| 512K | 400 | 466.7 | 518.2 | 0.047 | 0.046 | 0.060 | 0.074 | 447.9 | 428.5 |
| 1M   | 200 | 462.9 | 469.9 | 0.098 | 0.097 | 0.120 | 0.121 | 443.2 | 432.1 |
| 2M   | 100 | 399.4 | 453.1 | 0.221 | 0.220 | 0.243 | 0.243 | 377.2 | 500.7 |
| 4M   | 50  | 391.4 | 396.5 | 0.447 | 0.441 | 0.534 | 0.534 | 369.0 | 510.9 |
| 8M   | 25  | 393.3 | 403.5 | 0.909 | 0.885 | 1.136 | 1.136 | 370.6 | 508.5 |

### 结论

1. **整体写完 200MiB 的总时间在各 I/O size 下相近（约 390–470ms）**，大 I/O size（2M/4M/8M）略优，吞吐从 512K 的 ~428 MB/s 提升到 4M/8M 的 ~510 MB/s。
2. **单次 pwrite 平均延迟随 I/O size 线性增长**：512K≈0.047ms → 1M≈0.098ms → 2M≈0.22ms → 4M≈0.45ms → 8M≈0.91ms。基本与数据量成正比（每字节耗时相当）。
3. **总时间几乎全部消耗在最后的 fsync 落盘上**（fsync 占 total 的 92%–96%）。`pwrite()` 本身写入的是客户端 page cache（NFS 缓冲写），单次调用极快（亚毫秒/微秒级），真正把数据刷到 EFS 服务端的成本集中在 fsync。
4. **因此**：单看 pwrite 延迟反映的是「写入本地缓存」的速度（随 I/O size 线性）；单看整体总时间反映的是「200MiB 落盘到 EFS」的真实成本（受 fsync/网络往返主导，各 I/O size 差异不大）。大 I/O size 在减少系统调用次数与略微提升吞吐上有小幅优势。

---

## 测试代码

`efs_write_bench.py`：对每个 I/O size 新建文件，用 `os.pwrite()` 定长分块写满 200MiB，逐次记录 pwrite 延迟，末尾 `fsync()` 落盘并单独计时；每档跑 3 轮。

```python
#!/usr/bin/env python3
import os, sys, time, statistics, json

FILE_SIZE = 200 * 1024 * 1024          # 200 MiB
IO_SIZES = [512*1024, 1*1024*1024, 2*1024*1024, 4*1024*1024, 8*1024*1024]
ROUNDS = 3
TARGET_DIR = sys.argv[1] if len(sys.argv) > 1 else "/mnt/efs"

def run_one(io_size):
    path = os.path.join(TARGET_DIR, f"efs_wtest_{io_size}.bin")
    buf = os.urandom(io_size)
    n_writes = FILE_SIZE // io_size
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    lat = []
    t0 = time.perf_counter()
    off = 0
    for _ in range(n_writes):
        s = time.perf_counter()
        written = os.pwrite(fd, buf, off)
        e = time.perf_counter()
        if written != io_size:
            raise RuntimeError(f"short write {written}!={io_size}")
        lat.append((e - s) * 1000.0)   # ms
        off += io_size
    tf0 = time.perf_counter()
    os.fsync(fd)                        # 落盘到 EFS 服务端
    tf1 = time.perf_counter()
    t1 = time.perf_counter()
    os.close(fd); os.unlink(path)
    lat_sorted = sorted(lat)
    pct = lambda p: lat_sorted[min(len(lat_sorted)-1, int(len(lat_sorted)*p))]
    return {
        "io_size": io_size, "n_writes": n_writes,
        "total_ms": (t1 - t0) * 1000.0,      # 所有 pwrite + fsync
        "fsync_ms": (tf1 - tf0) * 1000.0,
        "avg_ms": statistics.mean(lat),
        "p50_ms": pct(0.50), "p99_ms": pct(0.99),
        "max_ms": max(lat), "min_ms": min(lat),
        "throughput_MBps": (FILE_SIZE/1024/1024) / ((t1 - t0)),
    }

def main():
    results = {}
    for io in IO_SIZES:
        rounds = [run_one(io) for _ in range(ROUNDS)]
        best = min(rounds, key=lambda x: x["total_ms"])
        results[io] = {
            "best": best, "rounds": rounds,
            "mean_total_ms": statistics.mean(x["total_ms"] for x in rounds),
            "mean_avg_ms": statistics.mean(x["avg_ms"] for x in rounds),
        }
    print(json.dumps({str(k): v for k, v in results.items()}, indent=2))

if __name__ == "__main__":
    main()
```

### 复现步骤（可抄了就跑）

```bash
# 1. 创建 EFS（弹性吞吐）
aws efs create-file-system --performance-mode generalPurpose \
  --throughput-mode elastic --encrypted --region us-east-2

# 2. 在与 EC2 同 AZ 的子网创建挂载点（SG 放行 2049 来自 EC2 SG）
aws efs create-mount-target --file-system-id fs-xxx \
  --subnet-id subnet-xxx --security-groups sg-xxx --region us-east-2

# 3. EC2 (c7i.4xlarge, AL2023) 上安装 efs-utils 并按官方方式挂载
sudo dnf install -y amazon-efs-utils
sudo mkdir -p /mnt/efs
sudo mount -t efs -o tls fs-xxx:/ /mnt/efs      # 官方 mount helper + 传输加密
sudo chown ec2-user:ec2-user /mnt/efs

# 4. 跑测试
python3 efs_write_bench.py /mnt/efs
```

---

## 补充实验：不同挂载 wsize 对写入的影响

上一节固定 wsize=1MiB（EFS 默认），变化应用层 pwrite size。本节反过来：**固定应用层 pwrite=1MiB，变化挂载 `wsize`**，看真正落到 EFS 的网络层 I/O size 对性能的影响。

- 挂载方式改为直连 NFS4.1（`mount -t nfs4 -o nfsvers=4.1,rsize=$WS,wsize=$WS,...`），以便显式控制 wsize；用 `nfsstat -m` 验证实际生效值。
- wsize 取 4 档：64K / 256K / 512K / 1M。

| 挂载 wsize | 实际生效 | pwrite 次数 | 最优总时间 (ms) | 3轮均值 (ms) | 平均 pwrite (ms) | fsync (ms) | 吞吐 (MB/s) |
|:---------:|:-------:|:----------:|:--------------:|:-----------:|:---------------:|:---------:|:----------:|
| 64K  | 65536（不钳制） | 200 | 1890.6 | 1938.9 | 0.095 | 1871.6 | 105.8 |
| 256K | 262144（不钳制）| 200 | 774.4 | 807.2 | 0.090 | 756.4 | 258.3 |
| 512K | 524288（不钳制）| 200 | 533.8 | 551.5 | 0.089 | 516.0 | 374.7 |
| 1M   | 1048576（不钳制）| 200 | 457.2 | 469.9 | 0.101 | 437.0 | 437.4 |

### wsize 结论

1. **EFS 完全接受 64K/256K/512K/1M 的 wsize，不做钳制**（`nfsstat -m` 显示请求多少就生效多少）。这点与 FSx ONTAP 不同（ONTAP 会把 wsize 钳制到 64K）。
2. **wsize 对写吞吐/总时间影响巨大**：wsize 从 64K → 1M，写完 200MiB 的总时间从 **1890ms 降到 457ms（快 4.1 倍）**，吞吐从 **105.8 MB/s 升到 437.4 MB/s（4.1 倍）**。
3. **原因**：wsize 决定 NFS 客户端每个 WRITE op 携带多少数据。wsize 越小，把 200MiB 刷到 EFS 需要的网络往返（WRITE op）次数越多——64K 需要 200MiB/64K ≈ 3200 次 WRITE，1M 只需 200 次。每次 WRITE 都有网络往返开销，往返次数随 wsize 减小而线性放大，直接决定 fsync 落盘耗时（占总时间 92%+）。
4. **应用层 pwrite 延迟几乎不受 wsize 影响**（都在 ~0.09–0.10ms），因为它写的是本地 page cache，与网络 wsize 无关。差异全部体现在 fsync 落盘阶段。
5. **建议**：EFS 挂载务必用官方推荐的 `wsize=1048576`（1MiB，也是 EFS 上限）。用小 wsize 会显著拖慢写吞吐。

> 网络层真正的写 I/O size = 挂载协商的 `wsize`，而非应用层 pwrite 的大小。参考 AWS 官方推荐挂载参数：<https://docs.aws.amazon.com/efs/latest/ug/mounting-fs-mount-cmd-general.html>

---

## 说明与限制

- pwrite 属于**缓冲写**（写入 NFS 客户端 page cache），单次调用延迟不等于数据落到 EFS 的延迟；真实落盘成本体现在末尾 `fsync()`。若需测「每次写立即落盘」的延迟，可用 `O_SYNC`/`O_DIRECT` 或每次 pwrite 后 fsync（会显著增加总时间、降低吞吐）。
- 弹性吞吐模式下 EFS 吞吐按需自动伸缩，本测试为单线程顺序写、单文件；多线程/多文件并发可获得更高聚合吞吐。
- 挂载走官方 mount helper 的 TLS 通道（stunnel 本地代理，故 mount 显示 `127.0.0.1:/`），这是 AWS 推荐的加密传输方式。
- 数值为单次实验结果，供趋势参考；EFS 为共享分布式存储，延迟受网络与后端负载影响会有波动。
