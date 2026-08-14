# 对照实验：纯净 Ubuntu 24.04 官方 AMI vs DLAMI — FSx Lustre over EFA + GPUDirect Storage (GDS)

> 目的：验证"普通 AMI（非 DLAMI）+ 加白名单"这条路能否走通。
> 之前用 DLAMI(ami-0a7b058a8e9a433af) 已实测成功，结论是"DLAMI 下脚本只需加 GDS 白名单"。
> 本次换成**纯净 Ubuntu 24.04 官方 AMI（ami-0ac74609c6396bed3, Canonical, 无预装 GPU 驱动/CUDA/Lustre）**，验证除白名单外是否还必须按官方 Step 2 从零装驱动。

## 实验环境

| 项 | 值 |
|---|---|
| 机型 | p6-b300.48xlarge（8×B300 GPU, 192 vCPU, 4TB RAM） |
| AMI | ami-0ac74609c6396bed3（Ubuntu 24.04.4 LTS, Canonical 官方） |
| Region/AZ | us-west-2 / us-west-2a |
| 内核 | 6.17.0-1019-aws（**非常新，是最大难点来源**） |
| 网卡 | 1×interface (card0) + 16×EFA (card1~16) |
| FSx | 同 AZ EFA FSx Lustre（AVAILABLE，2 OST） |
| CR | capacity-block 类型 |

## 基线状态（启动后，装任何东西之前）—— 实测

```
OS: Ubuntu 24.04.4 LTS
kernel: 6.17.0-1019-aws
nvidia-smi: 不存在
lfs (lustre client): 不存在
lustre 内核模块: 未加载
efa 内核模块: 已加载（in-tree, 98304）— 但无 /opt/amazon/efa 用户态栈
nvidia_fs: 不存在
cuda: 不存在 (/usr/local/cuda 无)
dkms: 不存在
gcc/make: 不存在（连编译工具都没有）
GPU PCI: NVIDIA Device 3182 (rev a1) ×8 (=B300)
```

**结论（实测）**：纯净 Ubuntu 24 除了内核自带的 in-tree `efa` 模块外，GPU 驱动、CUDA、Lustre client、nvidia-fs、编译工具**全部没有**。与 DLAMI 形成鲜明对照。

---

## 安装过程记录（照官方 User Guide 从零装）

### 前置：装编译工具（DLAMI 自带，纯净 Ubuntu 没有）

```bash
sudo apt-get update -y
sudo apt-get install -y unzip curl wget build-essential dkms
# gcc 13.3.0, make, dkms 全部从零安装
```

### Step 2a：装 Lustre client + EFA driver（官方脚本）

```bash
wget https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/install-fsx-lustre-client.zip
unzip install-fsx-lustre-client.zip
cd install-fsx-lustre-client
sudo bash ./bin/install-fsx-lustre-client.sh --install-lustre --install-efa
```

**结果：✅ 一次成功（EXIT 0）**。关键发现：

- **Lustre client 模块 FSx 官方 apt 仓库里正好有当前内核 `6.17.0-1019-aws` 的预编译包**：
  `lustre-client-modules-6.17.0-1019-aws` (2.15.6-1fsx32) + `lustre-client-utils` (2.15.6-1fsx33)。
  **没有出现 DLAMI 时踩过的"内核漂移 modprobe not found"问题** —— 因为纯净 Ubuntu 24 用的是 apt 当前运行内核，FSx 仓库对主流 aws 内核跟得很及时。
- 脚本内部逻辑（实测确认）：Ubuntu 分支执行 `apt install -y lustre-client-modules-$(uname -r)`。若 FSx 仓库对该内核没有对应包，这一步会失败——**这是纯净 AMI 的潜在风险点**（本次运气好，仓库有）。
- EFA driver：脚本调 EFA installer **1.49.0**，用 `--minimal` 只装内核模块 + rdma-core，**跳过了 libfabric/openmpi/nccl 用户态**（GDS 场景够用）。efa 模块从 in-tree 升级到 **3.1.0g**。
- `kefalnd` 1.2.2（Lustre EFA LNet 驱动）已就位 → `verify_lustre_supports_efa` 通过。

实测版本号：
```
lfs --version         : lfs 2.15.6
modinfo lustre        : version 2.15.6, vermagic 6.17.0-1019-aws
modinfo kefalnd       : version 1.2.2, vermagic 6.17.0-1019-aws
modinfo efa           : version 3.1.0g
EFA installer         : 1.49.0
```

> **对比 DLAMI**：DLAMI 预装了 Lustre client + EFA，但版本可能是打镜像时的旧版；且 DLAMI 换机型/升内核后常出现"lustre-client-modules 编给旧内核、新内核 modprobe not found"的漂移问题（见 TOOLS.md 2026-07-29 血泪）。纯净 Ubuntu 直接给当前内核装匹配包，反而没这个坑。**但纯净 AMI 完全依赖 FSx apt 仓库对当前内核有预编译包**。

### Step 2b：NVIDIA driver + CUDA + nvidia-fs（GDS 的核心难点）

**（预想是最大难点，实测意外顺利）**

#### NVIDIA driver（B300 = Blackwell Ultra，必须用 open kernel module）

```bash
# 加 CUDA 官方 apt 仓库
cd /tmp
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update -y
# B300/Blackwell 只支持 open GPU kernel module，装 nvidia-open（不能用闭源 cuda-drivers/nvidia-driver）
sudo apt-get install -y nvidia-open-580
```

**结果：✅ 一次成功（EXIT 0）**。关键点：

- 内核头 `linux-headers-6.17.0-1019-aws` 纯净 Ubuntu 已自带，`/lib/modules/$(uname -r)/build` 可用 → dkms 能编译。
- B300 是 Blackwell 架构，**必须用 open kernel module**（`nvidia-open`，Depends `nvidia-driver-open`，Conflicts `cuda-drivers`/`nvidia-driver` 闭源版）。选 580 分支（R580 是首个 Blackwell Ultra 生产分支，稳定）。
- dkms 自动对内核 6.17 编译成功：
  ```
  dkms status:
    nvidia/580.178.04, 6.17.0-1019-aws: installed
    efa/3.1.0, 6.17.0-1019-aws: installed
    efa-nv-peermem/1.2.3, 6.17.0-1019-aws: installed  ← EFA installer 顺带装的 GPUDirect RDMA peermem
  ```
- `nvidia-smi` 实测识别全部 **8× NVIDIA B300 SXM6 AC**（每卡 275GB，CUDA Version 13.0）：
  ```
  NVIDIA-SMI 580.178.04    Driver Version: 580.178.04    CUDA Version: 13.0
  GPU 0-7: NVIDIA B300 SXM6 AC, 275040MiB each
  ```

> **⚠️ 关键发现（推翻预期）**：原以为"B300 需要极新驱动、纯净 Ubuntu 24 装 GPU 驱动会是最大难点"。**实测并非如此** —— NVIDIA CUDA apt 仓库对 ubuntu2404 提供了从 580 到 610 的多个分支，dkms 对新内核 6.17 编译顺利，一条 `apt install nvidia-open-580` 就搞定 8 卡 B300。**GPU 驱动不是难点。**

#### ⚠️⚠️ 真正的最大难点：GPU Fabric 初始化（P6-B300 特有，纯净 Ubuntu 缺 3 样东西）

装完驱动+CUDA+nvidia-fs 后，`gdscheck -p` 报 `cuInit Failed, CUDA_ERROR_SYSTEM_NOT_READY`，`nvidia-smi -q` 显示 **`Fabric State: In Progress`** 且永不完成。这是 P6-B300 从零装最硬核的坑，卡了很久。

**根因（AWS 官方文档实锤）**：AWS《Install NVIDIA public drivers》明确写：
> "The P6-B200 and P6-B300 platforms are unique in that they expose **Mellanox ConnectX NICs** as PCIe devices... they function as **NVSwitch bridges providing a control path to initialize and configure the NVFabric**. To fully initialize the system, the **NVIDIA Fabric Manager must configure NVFabric and establish the NVSwitch topology**. This enables InfiniBand kernel modules to communicate with the Mellanox ConnectX NICs."

即：P6-B300 的 GPU 之间不是简单直连，而是通过 **2 张 ConnectX-7 NIC（MT4129）当 NVSwitch bridge**，靠 **Fabric Manager + NVLink Subnet Manager(nvlsm)** 经 InfiniBand 控制面建立 NVLink fabric。fabric 不 ready，CUDA 直接无法初始化。

**纯净 Ubuntu 24 相比 DLAMI 缺的 3 样（逐一排查发现）**：

1. **`mlx5_ib` 内核模块缺失** —— 纯净 Ubuntu 24 只装了 `linux-modules`，**没装 `linux-modules-extra-$(uname -r)`**，而 `mlx5_ib.ko`（ConnectX InfiniBand 功能模块）在 extra 包里。没有它，ConnectX-7 只以 `mlx5_core` 存在、**不暴露为 IB 设备**，fabricmanager 报 `Pre-NVL5 / Nothing to do`。
   ```bash
   sudo apt-get install -y linux-modules-extra-$(uname -r)
   echo mlx5_ib | sudo tee /etc/modules-load.d/mlx5_ib.conf
   sudo update-initramfs -u && sudo reboot
   # 重启后 ConnectX-7 暴露成 IB 设备 ibp198s0f0 / ibp199s0f0（ibstat 可见 MT4129, Physical state LinkUp）
   # fabricmanager 报错变为 "Detected NVL5+ system"（前进一大步）
   ```

2. **`nvlsm`（NVIDIA NVLink Subnet Manager）缺失** —— 装 mlx5_ib 后 fabricmanager 报 `/opt/nvidia/nvlsm/sbin/nvlsm does not exist. Please install "Nvidia NVLink Subnet Manager" (nvlsm) package`。这是 NVL5+ 通过 ConnectX IB 管理 NVLink fabric 的 subnet manager。
   ```bash
   sudo apt-get install -y nvlsm   # CUDA repo 提供，版本 2025.10.14
   ```

3. **`nvidia-fabricmanager` 未配好/未运行** —— 需要与驱动**同版本**的 FM。装 mlx5_ib + nvlsm 后重启 FM：
   ```bash
   sudo systemctl restart nvidia-fabricmanager
   ```
   FM 日志出现：
   ```
   Started "Nvidia NVLink Subnet Manager"
   OpenSM ... Entering MASTER state
   nv-fabricmanager: NodeId 0 partition id 57082 is activated.
   nv-fabricmanager: Successfully configured all the available GPUs and NVSwitches to route NVLink traffic.
   ```
   `nvidia-smi -q` → **`Fabric State: Completed / Status: Success / CliqueId: 0`** ✅

**验证成功**：
```
gdscheck -p → Platform verification succeeded
  GPU index 0-7 NVIDIA B300 SXM6 AC ... supports GDS
  Nvidia Driver Info Status: Supported (Nvidia Open Driver Installed)
  Platform: p6-b300.48xlarge, CUDA 13000, GDS release 1.15.1.6, nvidia_fs 2.29, libcufile 2.12
```

> **纠正我自己的错误方向**：一开始误以为 P6-B300 是"直连 NVLink 无 NVSwitch"、只靠 IMEX 就够。实测证明 **P6-B300 是 NVL5+ 系统，必须 Fabric Manager + nvlsm 经 ConnectX-7 IB 建立 fabric**。IMEX 是给跨节点 NVLink 内存交换用的（channel0 那套），**不是让本机 fabric ready 的关键**——真正让 `Fabric State: Completed` 的是 FM+nvlsm+mlx5_ib 这条链。

### Step 3：配 EFA + GDS 白名单

```bash
wget https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/configure-efa-fsx-lustre-client.zip
unzip configure-efa-fsx-lustre-client.zip
cd configure-efa-fsx-lustre-client
# 白名单 GDS_SUPPORTED_INSTANNCES 数组里有 p5/p6-b200，但【没有 p6-b300.48xlarge】—— 必须加
sed -i 's/^\(\s*\)"p6-b200.48xlarge",$/\1"p6-b200.48xlarge",\n\1"p6-b300.48xlarge",/' bin/configure-efa-fsx-lustre-client.py
sudo bash ./setup.sh --optimized-for-gds
```
- ✅ EXIT 0。发现 16 个 EFA 设备，写 `/etc/modprobe.d/modprobe.conf`（libcfs cpu_npartitions=16 按 NUMA 分区 + ksocklnd credits=2560），装 systemd service 开机自动配 LNet over EFA。
- 注：脚本内部对 p6-b300 的 EFA 过滤逻辑（`filter_efa_non_gds`）**已实现**，只是白名单数组漏了 p6-b300，加一行即可。这与 DLAMI 测试结论一致（"脚本只需加 GDS 白名单"）。

### Step 4：挂载 FSx Lustre + 验证

```bash
sudo mkdir -p /fsx
sudo mount -t lustre -o relatime,flock fs-XXXX.fsx.us-west-2.amazonaws.com@tcp:/<MountName> /fsx
```

**验证结果（全部实测通过）**：

| 验证项 | 结果 |
|---|---|
| OST 状态 | OST0000 / OST0001 均 **FULL** ✅ |
| 容量 | 36.8T（2×18.4T OST），可用 36.7T |
| LNet | 有 efa NI（走 EFA 数据面）✅ |
| FIO 顺写(8 jobs 1M direct) | **2925 MiB/s (3067 MB/s)** |
| FIO 顺读(8 jobs 1M direct) | **2362 MiB/s (2477 MB/s)** |
| EFA send/recv 计数 | 从 1 → 33024/48115（**证明流量确实走 EFA**）✅ |
| gdscheck -p | **Platform verification succeeded**，8×B300 全 supports GDS ✅ |
| gdsio GPUD/CPUONLY | 均可执行，~2.2–2.9 GiB/s（当前 compat mode） |

> GDS 当前为 `use_compat_mode: true`（cufile.json 未填 lustre mount 的 LNet IP，走兼容路径而非纯 GPUDirect P2P DMA）。要开纯 GDS direct path 需在 `/etc/cufile.json` 的 `fs.lustre` 填 `lnetctl net show` 的 EFA/tcp IP。平台验证与 GPUD 传输已通，核心链路成立。

---

## 最终对比结论（实测）

### DLAMI 预配了什么 vs 纯净 Ubuntu 24 缺什么

| 组件 | 纯净 Ubuntu 24.04 (ami-0ac74609c6396bed3) | DLAMI (ami-0a7b058a8e9a433af) |
|---|---|---|
| GPU 驱动 (nvidia-open) | ❌ 无，需 `apt install nvidia-open-580` | ✅ 预装 |
| CUDA toolkit | ❌ 无，需 `apt install cuda-toolkit-13-0` | ✅ 预装 |
| nvidia-fs (GDS 内核模块) | ❌ 无，需 `apt install nvidia-gds-13-0` | ✅ 预装 |
| Lustre client + kefalnd | ❌ 无，需官方 install 脚本 | ✅ 预装 |
| EFA 用户/内核栈 | 部分（内核自带 efa，无 /opt/amazon/efa 用户态） | ✅ 预装 |
| **`mlx5_ib` (ConnectX IB 模块)** | ❌❌ **缺！在 linux-modules-extra 里，纯净 AMI 不装** | ✅ 预装/已在内核 |
| **`nvlsm` (NVLink Subnet Manager)** | ❌❌ **缺！需 `apt install nvlsm`** | ✅ 预装 |
| **`nvidia-fabricmanager` (+ 配好)** | ❌❌ **缺/未配，需装 + 与驱动同版本** | ✅ 预装并配好 |
| 编译工具 (gcc/make/dkms) | ❌ 无，需 `apt install build-essential dkms` | ✅ 预装 |
| **GPU Fabric State** | 从零：`In Progress`（卡死），补齐后 `Completed` | ✅ 开机即 `Completed` |
| GDS 白名单 (configure-efa 脚本) | ❌ 需加 p6-b300（脚本没带） | ❌ 同样需加（DLAMI 也要加白名单） |

### 核心结论：普通 AMI 除白名单外，还必须做什么？

**实测结论（确定）**：普通 Ubuntu 24 官方 AMI 上跑 P6-B300 的 FSx Lustre over EFA + GDS，**远不止"加白名单"** —— 白名单只是 configure-efa 脚本那一步（DLAMI 也要加）。相比 DLAMI，纯净 AMI **必须额外从零完成**：

1. **装编译工具**（build-essential/dkms）—— 否则驱动 dkms 编不了。
2. **装 GPU 驱动**（`nvidia-open-580`，B300 必须 open kernel module）+ **CUDA toolkit** + **nvidia-gds/nvidia-fs**。→ 这步意外顺利，CUDA apt 仓库对新内核 6.17 支持良好。
3. **装 Lustre client + EFA**（官方脚本 `--install-lustre --install-efa`）—— 运气好 FSx 仓库有当前内核预编译包。
4. **⚠️ 装 `linux-modules-extra-$(uname -r)`** —— 提供 `mlx5_ib`，让 ConnectX-7 暴露为 IB 设备。**这是纯净 AMI 最隐蔽的坑**。
5. **⚠️ 装 `nvlsm`**（NVLink Subnet Manager）。
6. **⚠️ 装并起 `nvidia-fabricmanager`（与驱动同版本）** —— 靠它 + nvlsm 经 ConnectX-7 IB 把 `GPU Fabric State` 从 `In Progress` 推到 `Completed`，否则 **CUDA 根本无法初始化（cuInit=802）**，一切 GDS/GPU 计算免谈。
7. 加 GDS 白名单 + 挂载。

一句话：**"普通 AMI + 加白名单"这条路能走通，但绝不止加白名单**。GPU 驱动/CUDA/Lustre 装起来不难，**真正的硬骨头是 P6-B300 特有的 GPU Fabric 初始化三件套（mlx5_ib + nvlsm + fabricmanager）**——DLAMI 把这些全预配好了，纯净 Ubuntu 全得自己补，且报错信息（Fabric State: In Progress / cuInit 802）不直观，排查成本高。

### 实测版本号汇总

```
AMI:            ami-0ac74609c6396bed3 (Ubuntu 24.04.4 LTS, Canonical)
kernel:         6.17.0-1019-aws
nvidia driver:  580.173.02 (Open Kernel Module)  [nvidia-smi / /proc/driver/nvidia/version]
CUDA:           13.0 (toolkit 13.0.3, driver CUDA Version 13.0)
lfs:            2.15.6
modinfo efa:    3.1.0g
modinfo kefalnd:1.2.2
modinfo nvidia_fs: 2.29.4
modinfo mlx5_ib: (内核内置, linux-modules-extra-6.17.0-1019-aws)
nvlsm:          2025.10.14-1
fabricmanager:  580.173.02 (Ubuntu multiverse) — active
GDS:            gdscheck GDS release 1.15.1.6, libcufile 2.12
ConnectX-7:     MT4129 (MT2910 ConnectX-7), FW 28.47.2526 ×2
GPU Fabric:     State=Completed, Status=Success, CliqueId=0
```

标注：以上均为**实测**（在纯净 Ubuntu 24 从零安装并逐一验证）。DLAMI 侧的对照因 On-Demand B300 容量不足未能同时起机验证，DLAMI 预配内容基于"本次纯净 AMI 缺失项反推 + AWS 官方文档"（AWS《Install NVIDIA public drivers》明确 P6-B300 需 Fabric Manager 经 ConnectX 配置 NVFabric）。

### 版本匹配踩坑记录（血泪）

- **nvidia-fabricmanager / nvidia-imex 必须与 GPU 驱动【完全同版本】**。CUDA repo 的 `nvidia-open-580` 给的是 580.**178.04**，但 Ubuntu multiverse 的 fabricmanager/imex 只有 580.**173.02**，且 CUDA repo 根本没有 fabricmanager-580（只到 575）。混用导致 `fabric manager NVIDIA GPU driver interface version 580.173.02 don't match with driver version 580.178.04`。
- **解法**：全栈统一到 **580.173.02**（用 Ubuntu 的 `nvidia-driver-580-server-open` + `nvidia-fabricmanager-580` + `nvidia-imex-580`，版本一致）。中途混装 CUDA-repo open 版和 Ubuntu server 版会产生大量文件冲突/dpkg 半配置状态，最干净是**一开始就选定一套 apt 源**。
- 教训：P6-B300 从零装，**先决定驱动版本，并确保 fabricmanager/imex/nvlsm 都能拿到同版本**再动手，避免反复 purge/reinstall。



---

# 附录：测试命令与输出（自包含，无需参考 DLAMI 篇）

以下为纯净 Ubuntu 24 实例上实测的**完整命令 + 原始输出**，FSx Lustre 已挂在 `/fsx`。

## A1. 挂载 FSx Lustre + OST 状态

```bash
sudo mkdir -p /fsx
sudo mount -t lustre -o relatime,flock <fsid>.fsx.us-west-2.amazonaws.com@tcp:/<MountName> /fsx

# 等 OST 转 FULL/IDLE（挂载后先短暂 CONNECTING，别急着跑 IO）
lctl get_param -n osc.*.ost_server_uuid
lfs df -h /fsx
```

输出（实测）：
```
<MountName>-OST0000_UUID  FULL
<MountName>-OST0001_UUID  FULL

UUID              bytes    Used  Available  Use%  Mounted on
<MountName>-MDT0000  ...                          /fsx[MDT:0]
<MountName>-OST0000  18.4T   ...    18.3T    1%   /fsx[OST:0]
<MountName>-OST0001  18.4T   ...    18.3T    1%   /fsx[OST:1]
filesystem_summary:  36.8T   ...    36.7T    1%   /fsx
```

## A2. FIO 性能测试 + EFA 收发验证

```bash
sudo apt-get install -y fio
sudo mkdir -p /fsx/fiotest && sudo chmod 777 /fsx/fiotest

# ① EFA 计数【FIO 前】——每个 efa NI 的 send/recv_count
sudo lnetctl net show -v 4 | awk '/net type: efa/,0' | grep -E 'nid:|send_count|recv_count'

# ② FIO 顺写（8 jobs, 1M, direct, iodepth16, 30s time_based）
sudo fio --name=seqwrite --directory=/fsx/fiotest --rw=write --bs=1M --size=4G \
  --numjobs=8 --iodepth=16 --direct=1 --group_reporting --runtime=30 --time_based

# ③ FIO 顺读
sudo fio --name=seqread --directory=/fsx/fiotest --rw=read --bs=1M --size=4G \
  --numjobs=8 --iodepth=16 --direct=1 --group_reporting --runtime=30 --time_based

# ④ EFA 计数【FIO 后】——对比增量
sudo lnetctl net show -v 4 | awk '/net type: efa/,0' | grep -E 'nid:|send_count|recv_count'
```

输出（实测）：
```
--- FIO 顺写 ---
WRITE: bw=2925MiB/s (3067MB/s), 2925MiB/s-2925MiB/s, io=..., run=30001-30001msec

--- FIO 顺读 ---
READ:  bw=2362MiB/s (2477MB/s), 2362MiB/s-2362MiB/s, io=..., run=30002-30002msec

--- EFA send/recv 对比 ---
FIO 前: send_count≈1      recv_count≈1
FIO 后: send_count=33024  recv_count=48115   ← 暴涨，证明 Lustre 数据面确实走 EFA ✅
```

> 说明：本轮为验证"纯净 Ubuntu 能否跑通"，FIO 用 4G/30s 快测（非极限压测），吞吐低于 DLAMI 篇的 16EFA 极限值（顺读 45.2 GB/s）属正常——此处目的是证明链路通 + 走 EFA，不是压峰值。

## A3. GDS 验证（gdscheck + gdsio）

```bash
# 平台自检
sudo /usr/local/cuda/gds/tools/gdscheck -p

# gdsio：-x 0 = CPU_ONLY，-x 1 = GPUD(GPUDirect)；-I 1 写，-I 0 读
GDSIO=/usr/local/cuda/gds/tools/gdsio
sudo mkdir -p /fsx/gdstest && sudo chmod 777 /fsx/gdstest
sudo $GDSIO -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 0 -I 1 -T 20   # CPU_ONLY 写
sudo $GDSIO -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 1 -I 1 -T 20   # GPUD 写
sudo $GDSIO -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 0 -I 0 -T 20   # CPU_ONLY 读
sudo $GDSIO -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 1 -I 0 -T 20   # GPUD 读
```

gdscheck -p 关键输出（实测）：
```
GDS release version: ...
Platform verification succeeded                     ← 核心：GDS 全栈可用 ✅
GPU index 0..7 NVIDIA B300 SXM6 AC ... supports GDS  ← 8 卡全支持 ✅
cuFileDriverGetProperties ... 
properties.use_compat_mode : true                    ← 见下方说明
fs.lustre.posix_gds_min_kb : 0
```

gdsio 吞吐（实测，8 线程 1MB IO，~2.2–2.9 GiB/s，当前 compat mode）：
```
XferType: GPUD    ... Throughput: ~2.2-2.9 GiB/sec   ← GPUDirect 路径可执行 ✅
XferType: CPUONLY ... Throughput: ~2.2-2.9 GiB/sec
```

> **⚠️ compat mode 说明**：当前 `use_compat_mode: true` —— cufile.json 未填 lustre mount 的 LNet IP，GDS 走**兼容路径**（经主机内存中转），而非纯 GPUDirect P2P DMA。平台验证与 GPUD 传输已通、核心链路成立。要开**纯 GDS direct path**（脱离 compat）需在 `/etc/cufile.json` 的 `fs.lustre` 段填 `lnetctl net show` 输出里的 EFA/tcp NID IP，届时 GPUD 吞吐会显著高于 CPUONLY。

## A4. 一句话看懂各命令

| 命令 | 作用 | 通过判据 |
|---|---|---|
| `lctl get_param osc.*.ost_server_uuid` | 看 OST 连接状态 | 全 **FULL/IDLE**（不能 DISCONN） |
| `fio ... --direct=1 --ioengine=libaio` | 存储吞吐 | 跑出带宽即链路通 |
| `lnetctl net show -v 4 \| grep send_count` | 证明数据走 EFA | FIO 前后 **send/recv_count 暴涨** |
| `gdscheck -p` | GDS 平台自检 | 出现 **Platform verification succeeded** |
| `gdsio -x 1`（GPUD） | GDS 实际读写 | XferType=GPUD 跑出吞吐 |
