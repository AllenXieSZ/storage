# Estuary restore 无压缩路径数据损坏修复

## 问题
Estuary（及其上游 ComputeCanada lustre-obj-copytool）在 **不启用 LZ4 压缩**（`use_compression=false`，即 config 无 compression 或默认关闭）时，`lfs hsm_restore` 恢复的数据 **md5 与原文件不符（数据损坏）**。

## 根因（`src/lhsmtool_s3.c` restore 段）
restore 写回逻辑：
```c
int decompressed_size = object_chunk_size;   // 初始 = chunk_size(如100MB)
if (use_compression) {
    uncompress_buf = malloc(object_chunk_size);
    decompressed_size = LZ4_decompress_safe(...);   // 只有压缩时才 malloc + 赋真实长度
}
pwrite(dst_fd, uncompress_buf, decompressed_size, file_offset);
```
无压缩时：
- `uncompress_buf` 始终为 **NULL**（只在 `if(use_compression)` 里 malloc）
- `decompressed_size` 始终为 **object_chunk_size**（未被真实长度覆盖）

→ `pwrite(dst_fd, NULL, object_chunk_size, ...)` —— **数据源和长度都错**。
（S3 GET 回来的真实数据在 `data.buffer`，真实长度在 `data.contentLength`，但无压缩路径根本没用它们。）

推测原作者只测过压缩路径，无压缩路径从未跑通。

## 修复
无压缩时改用 `data.buffer` + `data.contentLength`。共 3 处（两处 pwrite + 一处累加）：

**第一个 chunk（行约 875-889）：**
```c
double before_lustre_write = ct_now();
char *write_buf1 = use_compression ? uncompress_buf : data.buffer;
long long int write_len1 = use_compression ? decompressed_size : (long long int)data.contentLength;
pwrite(dst_fd, write_buf1, write_len1, file_offset);
...
write_total = write_len1;
file_offset += write_len1;
```

**后续 chunk（行约 983-1011）：**
```c
double before_lustre_write = ct_now();
char *write_buf2 = use_compression ? uncompress_buf : data.buffer;
long long int write_len2 = use_compression ? decompressed_size : (long long int)data.contentLength;
pwrite(dst_fd, write_buf2, write_len2, file_offset);
...
write_total += write_len2;
file_offset += write_len2;
```

## 验证
修复后：
- 单 chunk（8MB）：restore md5 一致 ✓
- 多 chunk（250MB → 100+100+50MB）：restore md5 一致，size 精确 ✓
