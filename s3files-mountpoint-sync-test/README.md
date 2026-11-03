# S3 Files vs Mountpoint S3：同步延迟实测

> **结论：S3 Files 和 Mountpoint S3 可以共存于同一 bucket/prefix，双向数据互通。S3 Files 写入约 60-67 秒后 Mountpoint 可见；Mountpoint 写入约 2-3 秒后 S3 Files 可见。**

---

## 测试环境

| 项目 | 配置 |
|---|---|
| Region | us-east-2 (Ohio) |
| S3 Bucket | s3lambdatest2 |
| S3 Files FS | fs-0f4bd4f4454ac8a25, prefix=`checkpoint/` |
| EC2-A (S3 Files) | i-02de90a70603a6593, t3.medium, AL2023, us-east-2c |
| EC2-B (Mountpoint) | i-0a6a7721b3ea24402, t3.medium, AL2023, us-east-2c |
| 挂载方式 | EC2-A: `mount -t s3files fs-xxx:/ /mnt/s3files`<br>EC2-B: `mount-s3 s3lambdatest2 /mnt/mp-s3 --prefix checkpoint/` |
| 文件大小 | 1GB (`dd if=/dev/urandom bs=1M count=1024`) |
| 每方向测试轮次 | 3 轮 |
| 最大等待时间 | 180 秒 |

---

## 测试方法

S3 Files 和 Mountpoint S3 都将 S3 bucket 作为数据面，但机制不同：
- **S3 Files**：有独立的元数据/缓存层，NFS 写入后**异步导出**到 S3 对象层（约 60-67 秒）；S3 对象层变更**异步导入**到 NFS 视图（约 1-2 秒）
- **Mountpoint S3**：直接封装 S3 API，写入即 PutObject，读取即 GetObject，无中间层

测试 6 个方向的同步延迟：

```
方向 A: S3 Files NFS 写入 → S3 API 可见（HeadObject 返回 200）
方向 B: S3 API 写入（PutObject）→ S3 Files NFS 可见（ls + stat > 0）
方向 C: Mountpoint 写入 → S3 API 可见
方向 D: S3 API 写入 → Mountpoint 可见
方向 E: S3 Files NFS 写入 → Mountpoint 可见（= A + D 叠加）
方向 F: Mountpoint 写入 → S3 Files NFS 可见（= C + B 叠加）
```

每方向：写入 1GB 文件 → 每秒轮询目标端是否可见 → 记录首次可见的秒数。

---

## 实测结果

### 单服务同步（S3 Files / Mountpoint 各自 ↔ S3 API）

| 方向 | R1 | R2 | R3 | Min | Max | **Avg** |
|---|---|---|---|---|---|---|
| **A. S3 Files 写 → S3 API** | 68.5s | 64.5s | 67.6s | 64.5s | 68.5s | **66.9s** |
| **B. S3 API → S3 Files** | 1.0s | 2.0s | 1.0s | 1.0s | 2.0s | **1.3s** |
| **C. Mountpoint 写 → S3 API** | 0.8s | 0.6s | 0.6s | 0.6s | 0.8s | **0.7s** |
| **D. S3 API → Mountpoint** | 0.0s | 0.0s | 0.0s | 0.0s | 0.0s | **0.0s** |

### 跨挂载同步（S3 Files ↔ Mountpoint）

| 方向 | R1 | R2 | R3 | Min | Max | **Avg** |
|---|---|---|---|---|---|---|
| **E. S3 Files 写 → Mountpoint** | 66.2s | 66.4s | 66.2s | 66.2s | 66.4s | **66.3s** |
| **F. Mountpoint 写 → S3 Files** | 2.7s | 2.7s | 2.7s | 2.7s | 2.7s | **2.7s** |

---

## 数据流图

```
S3 Files NFS ─── ~67s 导出 ───→ S3 Bucket ─── 0.0s ───→ Mountpoint
     ↑                              ↑                        │
   ~1.3s 导入                       │                     ~0.7s 写入
     │                              │                        │
S3 Files NFS ←──── S3 Bucket ←──────────────── Mountpoint

跨挂载延迟 = 各段叠加：
  S3 Files 写 → Mountpoint 看到: ~66s (瓶颈 = NFS 异步导出到 S3)
  Mountpoint 写 → S3 Files 看到: ~2.7s (= 0.7s MP写入S3 + 2.0s S3导入NFS)
```

---

## 关键结论

### 1. S3 Files 和 Mountpoint S3 可以共存

两个服务可以同时挂载同一个 S3 bucket 的同一个 prefix，双向数据互通：
- S3 Files 写入的文件，约 **66 秒**后 Mountpoint 可见
- Mountpoint 写入的文件，约 **2.7 秒**后 S3 Files 可见

### 2. S3 Files 写入延迟 ~60 秒

S3 Files 的 NFS 写入不是直接调用 S3 PutObject，而是先写入 S3 Files 自身的存储层，然后**异步导出**到 S3 对象层。导出延迟约 65-69 秒（3 轮实测高度一致），不随文件大小显著变化。

### 3. Mountpoint 是 S3 API 的薄封装

Mountpoint 写入约 0.7s 后 S3 对象可见（本质就是 PutObject 的完成时间）；S3 对象变更对 Mountpoint 即时可见（0.0s）。无中间缓存层。

### 4. 适用场景建议

| 场景 | 推荐 | 原因 |
|---|---|---|
| AI 训练 checkpoint 写入 | **Mountpoint** | 需要秒级写入可见，checkpoint 是顺序大文件 |
| 多客户端 POSIX 文件共享 | **S3 Files** | 支持锁、权限、rename、NFS 协议 |
| 混合使用（写 + 共享） | **两者共存** | Mountpoint 写入 checkpoint → 2.7s 后 S3 Files 客户端可读 |
| 实时性要求 <1s | **Mountpoint + S3 API** | S3 Files 写入延迟 ~60s 不适合实时场景 |

---

## 重要注意事项

### S3 Files 的 S3 Prefix 映射

创建 S3 Files FS 时：
- 指定 `--prefix checkpoint/` → NFS 根目录映射 `s3://bucket/checkpoint/`，映射清晰
- **不指定 prefix** → FS 内部会使用一个隐藏前缀（如 `openclaw-files/`），NFS 根目录 ≠ S3 bucket 根目录

建议创建时**始终显式指定 `--prefix`**，避免前缀映射混乱。

### S3 Files 挂载方式

S3 Files **不能**用普通 `mount -t nfs4` 挂载，必须安装 `amazon-efs-utils` 后使用：

```bash
sudo mount -t s3files <file-system-id>:/ /mnt/s3files
# 或带 access point:
sudo mount -t s3files -o accesspoint=<ap-id> <file-system-id>:/ /mnt/s3files
```

### 并发写同一文件

未测试两边同时写同一个文件的冲突行为。建议**不同客户端写不同文件**，通过 S3 as single source of truth 实现最终一致。
