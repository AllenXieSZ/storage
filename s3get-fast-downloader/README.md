# s3get — 高速并发下载 S3 大文件到本地磁盘

一个用 Rust + AWS SDK 写的**独立二进制** CLI 工具,把 S3 上的大文件用**并发 range GET** 快速拉到本地磁盘。读取 **AWS CLI 的凭证配置**(和 `aws s3 cp` 一样),开箱即用。

- 自动读 AWS 默认凭证链(`~/.aws/credentials`、环境变量、EC2/ECS IAM role)
- 并发分片下载 + `pwrite` 直接落盘到各自 offset(不占大内存)
- **每个分片独立重试**(5 次指数退避),容忍连接重置/瞬时错误
- **关闭 SDK stalled-stream 保护**,高并发拥塞下不误判 panic
- 下载后大小/md5 与源一致(已验证)

## 100GB 实测(生产级环境)

| 环境 | 结果 |
|---|---|
| EC2 c6in.8xlarge(50 Gbps 网络) + gp3(200G / 2000 MB/s / 20000 IOPS) + Ubuntu 24 | — |
| 100 GiB 对象(真实落盘到 gp3) | **78.8 秒 = 1.36 GB/s (10.9 Gbps)**,大小完全一致,零错误 |

> 瓶颈分析:1.36 GB/s(≈1360 MB/s)受 **gp3 卷写吞吐上限(2000 MB/s)** 约束,不是 50Gbps 网络。落盘场景要更快需用更高吞吐存储(io2 / 多卷 RAID0 / 实例本地 NVMe SSD)。


## 快速开始(无需编译,直接用预编译二进制)

`bin/` 下是 **musl 全静态二进制**(`statically linked`,零依赖,任何 Linux 发行版都能跑,无 glibc 版本问题):

| 文件 | 架构 | 适用 |
|---|---|---|
| `bin/s3get-linux-x86_64-musl` | x86-64 | Intel/AMD;Ubuntu / Amazon Linux / Rocky / CentOS / Debian 等**全部** |
| `bin/s3get-linux-aarch64-musl` | ARM64 | Graviton;ARM 全部发行版 |

> ⚠️ **为什么用 musl 静态版**:动态链接 glibc 的二进制**不跨发行版**——在新系统(如 Ubuntu 24 / glibc 2.39)编的,拿到旧系统(Amazon Linux 2023 / Rocky 9,glibc 2.34)会报 `GLIBC_2.39 not found` 跑不了。musl 全静态零依赖,彻底解决。**已在 Ubuntu 22/24、Amazon Linux 2023、Rocky 9 四发行版实测通过。**

## 多发行版实测(musl 静态版)

**x86_64 与 ARM64 各 4 发行版,共 8 组合全部实测通过**(二进制均 `statically linked` / `not a dynamic executable`,S3 流量走 VPC S3 Gateway Endpoint):

| OS | x86_64 (100MB md5 / 20GB) | aarch64 (100MB md5 / 20GB) |
|---|---|---|
| Ubuntu 22.04 | ✅ / ✅ (7.6 Gbps) | ✅ / ✅ (8.3 Gbps) |
| Ubuntu 24.04 | ✅ / ✅ (7.8 Gbps) | ✅ / ✅ (8.4 Gbps) |
| Amazon Linux 2023 | ✅ / ✅ (8.1 Gbps) | ✅ / ✅ (8.3 Gbps) |
| Rocky Linux 9.8 | ✅ / ✅ (8.1 Gbps) | ✅ / ✅ (8.2 Gbps) |

（x86 环境 c6in.2xlarge、ARM 环境 c7g.2xlarge,均 gp3。100GB 单独实测见下,c6in.8xlarge + gp3 2000MB/s = 10.9 Gbps。）

## S3 VPC Gateway Endpoint vs 走 IGW(实测对比)

同一批实例,分别在「S3 流量走 IGW(公网出口)」和「走 S3 Gateway Endpoint」两种路由下测 20GB 下载:

| OS(x86_64) | 走 IGW | 走 Gateway Endpoint |
|---|---|---|
| Ubuntu 22.04 | 7.6 Gbps | 7.6 Gbps |
| Ubuntu 24.04 | 7.8 Gbps | 7.8 Gbps |
| Amazon Linux 2023 | 8.1 Gbps | 8.0 Gbps |
| Rocky Linux 9.8 | 8.1 Gbps | 8.2 Gbps |

**结论(诚实):同 Region 内,走 Gateway Endpoint 与走 IGW 的下载速度基本一致(差异在测量噪声内)**,因为底层都是 AWS 内部网络。Gateway Endpoint 的价值**不在于更快**,而在于:

1. **省钱**:私有子网若靠 NAT Gateway 访问 S3,会产生 NAT 数据处理费($0.045/GB);Gateway Endpoint **免费**且绕过 NAT。
2. **私有子网可用**:无公网出口(无 IGW/NAT)的子网,靠 Gateway Endpoint 也能访问 S3。
3. **安全合规**:S3 流量不出 VPC 边界。

**配置方法**:给子网所在的路由表关联 S3 Gateway Endpoint 即可(在路由表加一条 `S3 prefix-list → vpce-xxx` 路由)。AWS 按最长前缀匹配,S3 流量会优先走该路由(优先于 `0.0.0.0/0`)。
```bash
# 确认/关联 S3 Gateway Endpoint 到子网路由表
aws ec2 modify-vpc-endpoint --vpc-endpoint-id <vpce-id> --add-route-table-ids <rtb-id>
```




```bash
# 1. 放到机器上并加执行权限
chmod +x s3get-linux-x86_64-musl
sudo mv s3get-linux-x86_64-musl /usr/local/bin/s3get

# 2. 确保有 AWS 凭证(和 aws cli 一样,任选其一):
#    - aws configure  (写 ~/.aws/credentials)
#    - export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
#    - 或 EC2 挂了 IAM role(免配置)

# 3. 下载
s3get <S3路径> <region> <本地路径>
```

## 用法

```
s3get [OPTIONS] <S3_PATH> <REGION> <LOCAL_PATH>

参数:
  <S3_PATH>     S3 路径: s3://bucket/key 或 bucket/key
  <REGION>      AWS Region, 例如 us-east-2
  <LOCAL_PATH>  本地输出路径(文件名; 若是已存在目录则用 key 的文件名)

选项:
  --part-size <MB>       每个分片大小 (MB), 默认 8
  --concurrency <N>      并发 range 请求数, 默认 256
  --profile <NAME>       指定 ~/.aws 中的 profile(默认用默认凭证链)
  --dry-run              只打印计划不下载
  -h, --help / -V, --version
```

## 示例命令(可直接复现)

仓库已上传一个 100MB 测试文件到 S3,可直接跑:

**测试数据**:`s3://<YOUR-BUCKET>/path/to/bigfile.bin`(替换为你自己的大文件对象)

```bash
# dry-run 看计划
s3get s3://<YOUR-BUCKET>/path/to/bigfile.bin us-east-2 /tmp/test.bin --dry-run

# 真实下载(默认参数)
s3get s3://<YOUR-BUCKET>/path/to/bigfile.bin us-east-2 /tmp/test.bin

# 自定义并发和分片
s3get s3://<YOUR-BUCKET>/path/to/bigfile.bin us-east-2 /tmp/test.bin --concurrency 256 --part-size 16

# 校验 md5(与源文件 md5 对比)
md5sum /tmp/test.bin

# 下载到目录(自动用 key 的文件名 testdata_100mb.bin)
s3get s3://<YOUR-BUCKET>/path/to/bigfile.bin us-east-2 /data/

# 用指定 profile
s3get bucket/key us-east-2 ./out.bin --profile myprofile
```

**实测输出**(aarch64,openclaw 小实例,100MB):
```
对象: s3://<YOUR-BUCKET>/path/to/bigfile.bin
大小: 0.10 GB (104857600 bytes)
输出: /tmp/test.bin
计划: 13 个分片 x 8MB, 并发 64
完成: 0.10 GB / 2.9s = 0.04 GB/s (0.3 Gbps)
```
> 注:吞吐受实例网络带宽和文件大小影响。小实例/小文件跑不出高吞吐;在高带宽实例(如 c7i.48xlarge/带 EFA)+ 大文件(数十 GB)上,256 并发可打满 ~96 Gbps。

## 生成自己的测试数据

```bash
# 生成 100MB 随机文件并上传
head -c 104857600 /dev/urandom > testdata.bin
md5sum testdata.bin                       # 记下 md5
aws s3 cp testdata.bin s3://<你的bucket>/path/testdata.bin --region us-east-2
# 下载回来校验
s3get s3://<你的bucket>/path/testdata.bin us-east-2 /tmp/back.bin
md5sum /tmp/back.bin                       # 应和上面一致
```

## 参数调优建议

| 场景 | 建议 |
|---|---|
| 大文件(>10GB)+ 高带宽实例 | `--concurrency 256 --part-size 8`(默认,实测最优) |
| 中小文件 / 小实例 | `--concurrency 32~64`(并发太高无收益还增开销) |
| 内存紧张 | 分片小一点(part-size 4~8),并发别太高 |

## 权限

工具用 `HeadObject` + `GetObject`。IAM 需要:
```json
{"Effect":"Allow","Action":["s3:GetObject","s3:HeadObject"],"Resource":"arn:aws:s3:::<bucket>/*"}
```

## 从源码编译

```bash
# 装 Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# 本机架构编译
cargo build --release
# 产物: target/release/s3get

# 交叉编译 x86_64(在 ARM 主机上):
#   装交叉链接器: sudo apt install gcc-x86-64-linux-gnu
#   .cargo/config.toml 里配 linker = "x86_64-linux-gnu-gcc"
rustup target add x86_64-unknown-linux-gnu
CC_x86_64_unknown_linux_gnu=x86_64-linux-gnu-gcc \
  cargo build --release --target x86_64-unknown-linux-gnu
```

## 说明

- x86_64 版在 ARM 构建机上无法本地运行验证,但与 aarch64 版**同一份源码**交叉编译而来;aarch64 版已实测 md5 与源一致。**建议在目标机首次用 `--dry-run` 验证后再正式下载。**
- 二进制动态链接 glibc(几乎所有 Linux 都有)。若目标是极简/musl 环境,可自行用 `x86_64-unknown-linux-musl` target 编静态版。
