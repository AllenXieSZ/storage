# FSx ONTAP Storage Efficiency vs AI 模型文件 —— 实测报告

## 实验目的

验证 FSx ONTAP（Gen2）的 Storage Efficiency（inline compression + inline deduplication + data compaction）对 AI 模型相关文件的实际数据缩减效果，特别关注**剪枝（pruning）后零权重**能否被 ONTAP 压缩/去重。

## 实验环境

| 项目 | 值 |
|---|---|
| FSx ONTAP | fs-07a1bc8b8903f81d4, Gen2 SINGLE_AZ_2, us-east-2c |
| SSD 容量 | 1024 GiB |
| 吞吐 | 384 MB/s/HA pair |
| SVM | svm1 (svm-020b7b8b24d5cd25f) |
| NFS 客户端 | MySQL-Master i-0dffb881b2a90daa2 (SSM) |
| 挂载选项 | nfsvers=3,tcp,rsize=65536,wsize=65536 |
| Storage Efficiency | Enabled (inline compression + inline dedupe + data compaction) |
| Efficiency Policy | auto |
| ONTAP 版本 | FSx managed (Gen2) |

## 测试文件说明

每个文件写入独立 volume（10GB 配额），确保 efficiency 数据不互相污染。

| 文件名 | 大小 | 模拟场景 | 数据特征 |
|---|---|---|---|
| `01_dense_random_512mb.bin` | 512 MB | **密集模型**（未剪枝的 FP16 权重） | os.urandom 生成的纯随机字节，模拟 FP16 浮点权重的高熵特性 |
| `02_sparse50_scattered_512mb.bin` | 512 MB | **50% 非结构化剪枝**（Wanda/SparseGPT） | 随机字节中 ~50% 的 FP16 word 置零，零散分布 |
| `03_sparse90_scattered_512mb.bin` | 512 MB | **90% 非结构化剪枝** | ~90% 的 FP16 word 置零，零散分布 |
| `04_sparse50_contiguous_512mb.bin` | 512 MB | **50% 结构化剪枝**（删层/删头） | 前 256MB 全零 + 后 256MB 随机，模拟整层零填充 |
| `05_allzero_512mb.bin` | 512 MB | **100% 零**（极端测试） | 全零文件 |
| `06_semi24_512mb.bin` | 512 MB | **2:4 半结构化剪枝** | 每 4 个 FP16 word 中 2 个为零，2 个随机 |
| `07_int4_random_256mb.bin` | 256 MB | **INT4 量化模型** | os.urandom 纯随机字节 |
| `vol_dedup: copy1 + copy2` | 2×512 MB | **同一模型存两份**（去重测试） | 同一 512MB 随机文件写两份 |

## 核心结果

### 每个 Volume 的 Storage Efficiency 实测数据

| Volume | 文件逻辑大小 | Logical Used (ONTAP) | User Data (Physical) | Physical Used (Total) | **Data Reduction Ratio** | **用户数据节省** |
|---|---|---|---|---|---|---|
| vol_dense (密集随机) | 512 MB | 522.7 MB | 514 MB | 582 MB | **1.00:1** | ❌ 0% |
| vol_sparse50 (50%散零) | 512 MB | 522.7 MB | 514 MB | 582 MB | **1.00:1** | ❌ 0% |
| vol_sparse90 (90%散零) | 512 MB | 522.7 MB | 514 MB | 582 MB | **1.00:1** | ❌ 0% |
| vol_contiguous50 (50%连续零) | 512 MB | 518.5 MB | 258 MB | 320 MB | **~2.0:1** | ✅ ~50% |
| vol_allzero (全零) | 512 MB | 514.4 MB | 2 MB | 58 MB | **~256:1** | ✅ ~99.6% |
| vol_semi24 (2:4稀疏) | 512 MB | 522.6 MB | 514 MB | 582 MB | **1.00:1** | ❌ 0% |
| vol_int4 (INT4量化) | 256 MB | 261.5 MB | 257 MB | 318 MB | **1.00:1** | ❌ 0% |
| vol_dedup (同文件×2) | 2×512 MB | 1036 MB → Logical 1548 MB | 516 MB | 590 MB | **~2.0:1** | ✅ ~50% |

> 注：Physical Used 包含 User Data + Dedup fingerprint + Metadata + Performance Metadata。User Data 是纯文件数据占用。Logical Used 包含 Snapshot Reserve metadata。

### Aggregate 级别总 Efficiency

```
Aggregate: aggr1
Total Storage Efficiency Ratio: 1.54:1
```

## 关键结论（全部基于实测）

### 1. 非结构化剪枝的零权重 → ONTAP 压缩/去重完全无效 ❌

**实测结果**：50% 散零、90% 散零、2:4 半结构化——三者的 User Data 物理占用**和密集随机数据完全一样（514 MB），零节省**。

**根因**：ONTAP Storage Efficiency 工作在 **4KB 数据块**级别：
- **Zero Block Dedup**：只在一个 4KB 块**全部为零**时才消除。非结构化剪枝的零散分布在各处，一个 4KB 块（2048 个 FP16 值）里混着零和非零，几乎不可能凑满整块全零。
- **Compression**（LZ4 based）：在 8KB/32KB 压缩组里找重复模式。随机浮点值的非零部分是高熵数据，即使夹杂 50%-90% 的零 `0x0000`，因为零被非零值"打断"形成短 run，LZ4 的压缩收益极其有限——**实测为零收益**。
- **Inline Dedup**：4KB 块级签名比较，每个块内容不同（随机数据不同位置的零），无重复块。

**即使 90% 稀疏度也完全没有节省**——这超出了之前"可能省 15-30%"的推测。实测证明推测偏乐观。

### 2. 结构化剪枝（连续大块零）→ 非常有效 ✅

**实测**：50% 连续零（前半文件全零 + 后半随机）→ User Data 从 512MB 降到 **258 MB**，几乎完美的 2:1。

**原因**：前 256MB 全零 = 65,536 个 4KB 全零块，全部被 Zero Block Dedup 消除。后半的随机数据不可压缩，保持原样。

### 3. 全零文件 → 极端高效 ✅

**实测**：512MB 全零文件 → User Data 仅 **2 MB**（99.6% 节省）。剩余 2MB 是文件系统元数据开销。

### 4. 同一模型文件存两份 → Inline Dedup 完美去重 ✅

**实测**：2×512MB 完全相同的文件 → User Data **516 MB**（≈只存一份 + 指纹开销）。Logical Used 1548MB vs Physical 590MB。

**这是 ONTAP 在 AI 推理场景的真正杀手级功能**：多租户共享同一基模型 + 各自 LoRA adapter，ONTAP 卷内去重让 N 份基模型只占 ~1 份物理空间。

### 5. INT4 量化模型 → 不可压缩 ❌

**实测**：量化后的数据本质仍是高熵的（INT4 值 0-15 均匀分布 → 每个 nibble ~4bit 熵），打包后和随机字节无异。Data Reduction = 0%。

## 总结对照表

| 场景 | Compression 有效？ | Zero Block Dedup 有效？ | Inline Dedup 有效？ | **实测总节省** |
|---|---|---|---|---|
| 密集模型 FP16 (baseline) | ❌ | ❌ | ❌ | **0%** |
| 非结构化剪枝 50% (Wanda) | ❌ | ❌ | ❌ | **0%** |
| 非结构化剪枝 90% | ❌ | ❌ | ❌ | **0%** |
| 2:4 半结构化剪枝 | ❌ | ❌ | ❌ | **0%** |
| 结构化剪枝 50% (删层) | ❌（随机部分） | ✅（全零块部分） | ❌ | **~50%** |
| 全零文件 | N/A | ✅ | ✅ | **~99.6%** |
| INT4 量化 | ❌ | ❌ | ❌ | **0%** |
| 同一文件存两份 | ❌ | ❌ | ✅ | **~50%** |

## 实际建议（存储架构视角）

1. **非结构化剪枝模型别指望 ONTAP Storage Efficiency 省空间**——实测证明零散零完全不可压缩/去重。要省空间，应该在**应用层**用稀疏存储格式（CSR/COO/torch.sparse）。

2. **结构化剪枝（删整层/整头）对 ONTAP 友好**——被删除的结构填零后形成连续全零块，ONTAP Zero Block Dedup 可以消除。但前提是模型文件格式保留了这些全零 tensor（而不是直接不写）。

3. **ONTAP 对 AI 推理的真正价值 = Inline Dedup（多副本去重）**：
   - 多租户场景：N 个客户共享同一基模型 + 各自 LoRA adapter → 基模型去重
   - CI/CD 场景：模型版本迭代，连续版本间大部分权重不变 → 跨版本去重
   - 数据集：训练数据多副本 → 去重

4. **量化模型数据（INT4/INT8）和浮点模型一样不可压缩**——别指望量化后 ONTAP 能再省一层。

5. **如果非要在存储层省空间，用 ONTAP FlexClone**（写时复制克隆）比指望 compression 更可靠——clone 一个模型文件只占 delta 空间。

## 资源清单（等伟伟确认后清理）

| 资源 | ID | 状态 |
|---|---|---|
| FSx ONTAP | fs-07a1bc8b8903f81d4 | AVAILABLE |
| SVM | svm-020b7b8b24d5cd25f | CREATED |
| Volumes | vol_dense / vol_sparse50 / vol_sparse90 / vol_contiguous50 / vol_allzero / vol_semi24 / vol_int4 / vol_dedup | CREATED |
| 预估费用 | ~$5/天 (SSD) + 吞吐费 | 计费中 |

清理命令：
```bash
# 先删 volumes
for VOLID in fsvol-0a380d57c3aec06db fsvol-013fcfc6e495ecf38 fsvol-020e3744a3eeb3dcb fsvol-0e97d6d649fed2346 fsvol-0acd3d21e1225d9b2 fsvol-002abd96270f87b91 fsvol-02e536f8f1bebb001 fsvol-0727a1b1ce15420ca; do
  aws fsx delete-volume --volume-id $VOLID --ontap-configuration '{"SkipFinalBackup":true}' --region us-east-2
done
# 等 volumes 删完后删 SVM
aws fsx delete-storage-virtual-machine --storage-virtual-machine-id svm-020b7b8b24d5cd25f --region us-east-2
# 等 SVM 删完后删 FS
aws fsx delete-file-system --file-system-id fs-07a1bc8b8903f81d4 --ontap-configuration '{"SkipFinalBackup":true}' --region us-east-2
```
