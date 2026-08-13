# FSx for Lustre + GPUDirect Storage (GDS) 端到端搭建与验证

在 AWS GPU 实例（P5，8×H100）上，用 **EFA-enabled FSx for Lustre** 验证 **NVIDIA GPUDirect Storage (GDS)**：数据从存储经 DMA **直达 GPU 显存**，绕过 CPU bounce buffer。全流程跑通，`gdsio` 的 `XferType: GPUD` 证明 GPUDirect 直传工作正常。

> 数据通路示意见 `gds_datapath.png`（传统路径：存储→主机内存→显存两跳；GDS：存储→显存一跳直达 DMA）。

---

## 0. 关键前提（先看，省得白花钱）

- **GDS 官方仅支持 GPU 机型**：P5 / P5e / P5en / P6-B200（需 GPU + EFA + **与 FSx 同 AZ**）。无 GPU 的实例（i7ie/hpc6id 等）不能测 GDS。
- **GPU 容量极紧张**：p5.48xlarge 常年 `InsufficientInstanceCapacity`（即使配额够，也是物理无货）。解决办法是 **Capacity Block for ML**（见下）。
- **EFA 客户端必须与 FSx 同 AZ**（跨 AZ 会导致 EFA 数据面建 AH 失败、OST DISCONN）。GPU 在哪个 AZ，FSx 就建哪个 AZ。

---

## 1. 申请 GPU：Capacity Block for ML

```bash
# 1) 查询可用的 capacity block offering（最短块是 24h 档，1/6/12h 不支持）
aws ec2 describe-capacity-block-offerings \
  --instance-type p5.48xlarge \
  --instance-count 1 \
  --capacity-duration-hours 24 \
  --region <REGION>

# 2) 购买（预付、不可退）
aws ec2 purchase-capacity-block \
  --capacity-block-offering-id <OFFERING_ID> \
  --instance-platform Linux/UNIX \
  --region <REGION>
# → 得到 CapacityReservationId，例如 cr-xxxxxxxxxxxxxxxxx
```

⚠️ **启动 Capacity Block 实例时必须带两个参数**，否则报 `market type option is not valid`：
```bash
aws ec2 run-instances \
  --instance-type p5.48xlarge \
  --image-id <DLAMI_ID> \
  --instance-market-options '{"MarketType":"capacity-block"}' \
  --capacity-reservation-specification '{"CapacityReservationTarget":{"CapacityReservationId":"<CR_ID>"}}' \
  --subnet-id <SUBNET_SAME_AZ_AS_FSX> \
  --security-group-ids <SG_ID> \
  --key-name <KEY> \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":500,"VolumeType":"gp3"}}]' \
  --region <REGION>
```
> root 盘建议直接开 **500G**（原因见 §5：DLAMI 自带 4 套 CUDA 已快占满 300G）。

---

## 2. 创建同 AZ 的 EFA-enabled FSx for Lustre

```bash
aws fsx create-file-system \
  --file-system-type LUSTRE \
  --storage-capacity 38400 \
  --subnet-ids <SUBNET_SAME_AZ_AS_GPU> \
  --security-group-ids <SG_ID> \
  --lustre-configuration '{
      "DeploymentType":"PERSISTENT_2",
      "PerUnitStorageThroughput":250,
      "EfaEnabled":true,
      "MetadataConfiguration":{"Mode":"AUTOMATIC"}
    }' \
  --region <REGION>
```

关键点（均为实测/官方文档确认）：
- **EFA FSx 必须显式给 `MetadataConfiguration`**，否则报 *"EFA is only supported for PERSISTENT_2 filesystems with metadata configuration"*。
- **EFA FSx 最小容量随吞吐档变化**：`1000 MB/s/TiB` 档 → 最小 **4.8 TiB**；`250 MB/s/TiB`（最低档）→ 最小 **38.4 TiB**（吞吐档越低，最小容量越大）。
- `aws fsx create-file-system` **不支持 `--dry-run`**。

挂载（EFA Lustre 与普通 Lustre 挂载命令一致，靠前置 configure-efa 服务把 LNet 配到 efa）：
```bash
sudo mount -t lustre -o relatime,flock \
  <fsid>.fsx.<REGION>.amazonaws.com@tcp:/<MOUNTNAME> /fsx
```

---

## 3. 操作系统 AMI 与软件栈

**使用 Base Deep Learning AMI (DLAMI) — Ubuntu 24.04：**

```bash
# 通过 SSM Public Parameter 拿最新 AMI ID
aws ssm get-parameter \
  --name /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id \
  --region <REGION> --query 'Parameter.Value' --output text
```

- **OS**：Ubuntu 24.04
- **SSM 参数名**：`/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id`
- **预装**：8×H100 NVIDIA driver、CUDA（多版本 12.8/12.9/13.0/13.2）、EFA（installer 1.47）、Lustre client 2.15.6、**GDS 工具 `gdscheck`/`gdsio`（在 `/usr/local/cuda/gds/tools/`）**
- ⚠️ **未预装 PyTorch**；⚠️ **`nvidia-fs` 内核模块未预装/未加载**（见 §4）

---

## 4. 安装 nvidia-fs 内核模块（GDS 的核心，重点）

⚠️ **不要用 `apt install nvidia-gds`** —— 它会拉错内核 flavor（拉进 `linux-modules-nvidia-*-oracle`，而实例实际内核是 `*-aws`）→ DKMS 编译失败 → 卡死 dpkg（之后所有 apt 操作失败，需 `apt-get remove --purge` 坏包 + `dpkg --configure -a` 修复）。

**正解 = 针对当前 `-aws` 内核手动编译 nvidia-fs.ko：**

```bash
# 依赖
sudo apt-get update
sudo apt-get install -y build-essential git linux-headers-$(uname -r)

# 拉源码并编译
git clone --depth 1 https://github.com/NVIDIA/gds-nvidia-fs.git
cd gds-nvidia-fs/src
export NVFS_MAX_PEER_DEVS=128 NVFS_MAX_PCI_DEPTH=16
make

# 加载模块
sudo insmod nvidia-fs.ko
lsmod | grep nvidia_fs      # 确认已加载
```

**configure-efa 用 GDS 优化模式**（不是普通 `setup.sh`）：
```bash
sudo ./setup.sh --optimized-for-gds
```

---

## 5. 常见坑（DLAMI / 环境）

- **root 盘 300G 被 4 套 CUDA 占满**（每套 ~9-12G），装任何东西前就可能 100% 满。
  - 扩容：`aws ec2 modify-volume --volume-id <vol> --size 500` → 实例内 `sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/nvme0n1p1`（根盘满时用 `TMPDIR=/dev/shm`）。
  - 或临时删掉多余 CUDA 版本腾空间。
- **别把 Python 环境（torch 几万小文件）装到 Lustre 上** —— 比本地盘慢 10 倍+，连 SSH 都会被 Lustre I/O 拖卡。装本地根盘（先扩容）。
- **SSM RunCommand 在高负载/盘满时不可靠**（document-worker 反复崩 `ipc messaging received timeout signal`，即使 agent Online）。改用 **SSH 直连**。
- SSH 里 `pkill -9 -f torchrun/pip` 会连带把自己的 SSH 会话杀断（进程树关系）；后台任务用 `setsid nohup ... </dev/null &` 脱离会话。

---

## 6. 验证

### 6.1 gdscheck（平台自检）
```bash
/usr/local/cuda/gds/tools/gdscheck -p
```
成功应看到：
- 8×H100 全部 `supports GDS`
- `nvidia_fs version 2.29 (min 2.12)`
- `fs.lustre.posix_gds_min_kb: 0`（cuFile 已识别 Lustre）
- `Platform verification succeeded`

同时确认 Lustre OST 状态 FULL/IDLE（同 AZ、EFA 数据面通）：
```bash
lctl get_param -n osc.*.ost_server_uuid    # FULL/IDLE=通，DISCONN=断
lfs df -h /fsx
```

### 6.2 gdsio（吞吐实测）
```bash
# 参数：-d GPU号  -w 线程数  -s 每线程数据量  -i IO块大小
#       -x 0 = GPUDirect(GPUD)   -x 1 = CPUONLY
#       -I 1 = WRITE            -I 0 = READ
GDSIO=/usr/local/cuda/gds/tools/gdsio

# ⚠️ 读测试(-I 0)要求文件先存在 → 必须先写再读
sudo $GDSIO -D /fsx/gdstest -d 0 -w 4 -s 4G -i 1M -x 0 -I 1   # GPUDirect 写
sudo $GDSIO -D /fsx/gdstest -d 0 -w 4 -s 4G -i 1M -x 0 -I 0   # GPUDirect 读

# 对照：CPUONLY 路径
sudo $GDSIO -D /fsx/gdstest -d 0 -w 4 -s 4G -i 1M -x 1 -I 0   # CPUONLY 读
```
`XferType: GPUD` 即证明走 GPUDirect（绕过 CPU 直入 H100 显存）。

---

## 7. 实测结果与重要结论

**实测数字（p5.48xlarge，1×GPU / 4 线程 / 1MB 块，FSx Lustre 250MB/s/TiB）：**
- GPUDirect (GPUD)：写 2.5–2.9 GiB/s，读 ~2.87–2.96 GiB/s
- CPUONLY：读 ~3.08 GiB/s

### ⚠️ 重要发现：小规模下 GDS(GPUD) 吞吐反而比 CPU(CPUONLY) 略低 ~7%

复现两次，`GPUD 读 2.87` vs `CPUONLY 读 3.08 GiB/s`，CPUONLY 稳定快约 7%。原因分析：

1. 吞吐才 ~3 GiB/s，**远未到 CPU 瓶颈**，bounce buffer 拷贝开销可忽略。
2. **CPUONLY 走 CPU 内存能命中 page cache**（重复读同一数据集）；GDS 故意绕过 CPU 内存 = 也绕过 page cache，每次真读存储，无缓存加成。
3. GDS 直传有 DMA setup 固定开销，小规模不划算。

**结论：GDS 的价值不是"更快"，而是"绕过 CPU / 主机内存"** —— 省 CPU、省内存带宽（GPU 训练时 CPU 可去干别的）。只有**高吞吐（几十~上百 GB/s）或 CPU 本身很忙**时才明显反超。

**公平对比要点**：每轮前 `sync; echo 3 | sudo tee /proc/sys/vm/drop_caches` 清缓存 + 用 `mpstat` 看 CPU 占用（GPUD 的 CPU 占用应远低于 CPUONLY，这才是它真正的收益点）。

> **CPU bounce buffer**：传统存储→GPU 传输时数据被迫在 CPU 主机内存中转的缓冲区（存储→内存→显存，两跳）；GDS 消除它（存储→显存一跳直达 DMA）。

---

## 8. 清理提醒（GPU/FSx 很贵）

- 删 **p5 实例**（Capacity Block 到期会自动回收，但预付费用不退）
- 删 **EFA FSx**（38.4TB，约 $6–7/小时）
- 自制 AMI（若有）；DLAMI 公共镜像不用删

> 本文所有数字均为实测（非推测）。实例 ID / IP / 文件系统 ID / CR ID / 密钥路径 / SG / subnet 等已脱敏，请用你自己的环境值替换尖括号占位符。
