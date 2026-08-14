# 三种 AMI 对照：B300 上 FSx Lustre over EFA + GPUDirect Storage(GDS)

> 实测时间：2026-08-13 ~ 08-14（UTC），区域 us-west-2a，机型 p6-b300.48xlarge。
> 目的：在同一套 FSx Lustre(EFA) 上，用三种不同 AMI 从零配置 EFA + GDS，对比"预装了什么 / 要手动补什么"，并严谨验证 GDS 到底走没走 direct path。
> 结论标注：【实测】= 本次真机跑出；【推测/待确认】= 未实测的推断。

---

## 0. 一句话结论

**三种 AMI 都能把 FSx Lustre over EFA 跑通（FIO 走 EFA、高吞吐），但 GDS 全部只能 compat mode，走不了真正的 GPUDirect direct path。** 根因是 EFA（SRD/libfabric，`transport: unspecified`）不是 cuFile/nvidia-fs 需要的标准 verbs RDMA，与 AMI 无关。三种 AMI 的差异只在"预装了多少组件"。

---

## 1. 三种 AMI 对照表

| 组件 | EKS AL2023 NVIDIA (ami-013c537b921d2f4b6) | DLAMI (ami-0a7b058a8e9a433af) | 纯净 Ubuntu 24.04 (ami-0ac74609c6396bed3) |
|---|---|---|---|
| OS / kernel | AL2023 / 6.12.79-amzn2023 | Ubuntu 24.04.4 / 6.17.0-1019-aws | Ubuntu 24.04.4 / 6.17.0-1019-aws |
| GPU driver | 预装 580.126.09 | 预装 595.71.05 | 手动装 |
| GPU fabric (fabricmanager) | 预装, cuInit=0 | 预装, cuInit=0 | 手动补 mlx5_ib + nvlsm + fabricmanager |
| EFA driver | 预装 3.0.0g | 预装 3.0.0g | 手动装 |
| 16 EFA 网卡 | 是 | 是 | 是 |
| Lustre client | 手动装 (2.15.6) | 预装 2.15.6 | 手动装 |
| CUDA / GDS 工具 | 手动装 (nvidia-gds) | 预装 | 手动装 |
| nvidia-fs 内核模块 | 手动编 | 手动编 | 手动编 |
| git / fio | 手动装 | fio 手动装 | 手动装 |

要点：
- **fabric 是纯净 Ubuntu 的最大坑**：B300 的 GPU 不是直连，靠 2 张 ConnectX-7 当 NVSwitch bridge + Fabric Manager + nvlsm 经 InfiniBand 建 NVLink fabric。纯净 Ubuntu 缺 mlx5_ib(在 linux-modules-extra) + nvlsm + nvidia-fabricmanager 三件套，fabric 卡 "In Progress" 导致 cuInit=802。DLAMI 和 EKS AL2023 都预装好了 fabricmanager，cuInit 开箱=0。
- **nvidia-fs 三种 AMI 都要手动编**：git clone github.com/NVIDIA/gds-nvidia-fs, cd src, NVFS_MAX_PEER_DEVS=128 NVFS_MAX_PCI_DEPTH=16 make, insmod nvidia-fs.ko。
- **GDS 白名单**：三种都要手动把 p6-b300.48xlarge 加进 configure-efa-fsx-lustre-client.py 的 GDS_SUPPORTED_INSTANNCES 数组（AWS 尚未收录 b300）。

---

## 2. FIO 结果（三种 AMI 都跑通, 走 EFA）

| AMI | 顺写 | 顺读 |
|---|---|---|
| EKS AL2023 NVIDIA | 10.3 GB/s (9819 MiB/s) | 33.2 GB/s (30.9 GiB/s) |
| DLAMI (16 EFA 重建轮) | 10.9 GB/s | 45.2 GB/s |
| 纯净 Ubuntu 24 | 3.07 GB/s (快测) | 2.48 GB/s (快测, 非峰值) |

- FIO 参数：direct=1, ioengine=libaio, bs=1M, numjobs=8, iodepth=32。
- 均通过 `lnetctl net show -v 4` 的 send_count/recv_count 前后暴涨验证数据确实走 EFA。
- 吞吐差异主要来自测试时长/轮次（快测 vs 满测）与 OST 连接数，非 AMI 本质差异。

---

## 3. GDS 严谨验证：三种 AMI 全部 compat mode

### 判据（重要）
判断"是否走真 GDS direct path"，可靠性从高到低：
1. **nvidia-fs 内核 Ops 计数器** (`/proc/driver/nvidia-fs/stats` 的 `Ops: Read/Write`) —— 最硬。真 GDS 数据必经 nvidia-fs 内核模块，Ops=0 就是没走 GDS。
2. `gdscheck -p` 的 `use_compat_mode` 标志 —— 次之。
3. gdsio 输出的 `XferType` 标签 —— **最不可靠**，会误报 GPUD（它标的是"请求的模式"，不是"实际生效路径"）。

### 三种 AMI 实测（全部 compat）

| AMI | use_compat_mode | gdsio XferType | nvidia-fs Ops(前/后) | 结论 |
|---|---|---|---|---|
| EKS AL2023 | true | GPUD | Read=0/Write=0 恒0 | compat |
| DLAMI | true | GPUD | Read=0/Write=0 恒0 | compat |
| 纯净 Ubuntu 24 | true | GPUD/CPUONLY | Read=0/Write=0 恒0 | compat |

- 三种 AMI gdscheck 都报 "Platform verification succeeded" + "8xB300 supports GDS"，但这只代表 GDS 软件栈就绪，**不代表走了真 direct path**。
- EKS AL2023 上 gdsio 还额外报 `cuFile buffer deregister failed: device pointer lookup failure`（未影响吞吐输出，实例被 Capacity Block 回收前未及深挖，标为待查）。
- 曾尝试在 cufile.json 的 fs.lustre 段填 LNet IP + 开 rdma_dynamic_routing，均无法把 use_compat_mode 变 false。

### 根因【实测 + EFA 特性】
GDS direct path 依赖存储网络提供标准 RDMA verbs（InfiniBand/RoCE，如 mlx5）。本架构 Lustre 走 EFA：
```
ibv_devinfo -> EFA 设备 transport: unspecified (4)   <- 非标准 IB/RoCE verbs
```
EFA 用 SRD 协议 + libfabric，不是 cuFile/nvidia-fs 能用的标准 verbs RDMA。因此无论哪种 AMI、怎么配 cufile.json，cuFile 都找不到可用 RDMA 后端，只能 fallback 到 compat（数据经主机内存中转）。

### 待确认【推测】
未在 AWS/NVIDIA 官方文档中找到"FSx Lustre over EFA 支持/不支持 GDS direct path"的明确说明。"必须 IB/RoCE 或 NVMe-oF 等标准 verbs RDMA 存储才能走 direct path"是基于本次实测 + EFA transport 特性的推断，非官方背书。

---

## 4. NVIDIA GDS 官方定义（供参考）

来自 docs.nvidia.com GPUDirect Storage cuFile API Reference：
- GDS = "a direct data path for DMA transfers between GPU memory and storage, which avoids a bounce buffer through the CPU."
- compat mode = "When GDS is not functional for the IO target, the code that uses the cuFile APIs falls back to the standard POSIX read/write path."

即：compat mode = 回退到 POSIX 路径（经 CPU/主机内存），不是 GPU 显存直达。

---

## 5. 关联文档
- 配置脚本 + 中英文完整说明：见本目录 `configure-fsx-lustre-efa-gds.sh` / `README.md` / `README.en.md`
- 纯净 Ubuntu vs DLAMI 详细过程：`ubuntu24_vs_dlami_test.md`
