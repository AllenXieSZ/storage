# B300 (p6-b300.48xlarge) + FSx Lustre over EFA + GPUDirect Storage: Configuration & Verification

> 🌏 中文版见 [`README.md`](README.md)
>
> Tested: 2026-08-13 (UTC)  Region: us-west-2a
> Audience: anyone who needs to set up and verify FSx for Lustre over EFA + NVIDIA GPUDirect Storage (GDS) on a B300 instance.
> Companion script: `configure-fsx-lustre-efa-gds.sh` (real-machine-verified version, strictly aligned with the AWS official User Guide).
> Labels: **[Measured]** = obtained on the real machine this run; **[Inferred]** = not directly tested.
> Full command + output trace: `transcript-16efa-rebuild.log`.

---

## 0. Bottom line

> **Note**: As of 2026-08-13, the GDS supported-instance list in the AWS official User Guide and `configure` script **does not yet include `p6-b300.48xlarge`** (only p5/p5e/p5en/p6-b200). So the following is **not "officially declared support"** — it is a **real-machine configuration + verification that passed this run**.

**[Measured] On p6-b300.48xlarge, FSx for Lustre over EFA + NVIDIA GPUDirect Storage (GDS) was configured and verified successfully.**
All 16 EFA NIs came up, both OSTs IDLE; FIO seq-read **45.2 GB/s** / seq-write **10.9 GB/s**; `lnetctl -v 4` before/after diff proves traffic goes over EFA; `gdscheck -p` → Platform verification succeeded, all 8×B300 support GDS, gdsio GPUD path works.

### What you must change vs. what is pre-installed (assuming DLAMI)

| Item | Official User Guide | Action needed on B300 |
|---|---|---|
| Lustre client | Step 2 install | ✅ **Pre-installed in DLAMI** (2.15.6), no change |
| EFA driver | Step 2 install | ✅ **Pre-installed in DLAMI** (3.0.0g / installer 1.47.0), no change |
| CUDA / NVIDIA driver | — | ✅ **Pre-installed in DLAMI** (driver 595.71.05 / CUDA 13.2), no change |
| GDS driver nvidia-fs (≥2.24.2) | Step 2 GDS section | ✅ **Pre-installed in DLAMI** (2.29), no change |
| **GDS allowlist** | `GDS_SUPPORTED_INSTANNCES` in the script | ⚠️ **The only thing you must change**: manually add `p6-b300.48xlarge` to the allowlist array (because AWS has not listed b300 yet) |
| EFA config setup.sh | Step 3 run `setup.sh --optimized-for-gds` | ✅ Run as-is; no logic change once allowlist is patched |
| Mount / FIO / lnet / gdscheck | Step 4 + verification | ✅ Use official commands as-is |

> **Conclusion**: With DLAMI, **the only script-level change = add the GDS allowlist entry**; all drivers are pre-installed and every other command is used verbatim.
> (With a plain AMI you must additionally install Lustre/EFA/nvidia-fs drivers per Step 2 — that is environment prep, not editing this configure script.)
> There are also two **EC2-layer prerequisites outside this script**: declaring the 16 EFA NICs when launching the instance, and the special parameter for launching from a Capacity Block — see Appendix A/B.

---

## 1. Resources & Environment

| Item | Value |
|---|---|
| Instance type | p6-b300.48xlarge (us-west-2a) |
| GPU | 8 × NVIDIA B300 SXM6 AC (275040 MiB / ~268 GB each, bar1 512 GiB) |
| **AMI** | **`ami-0a7b058a8e9a433af`** (AWS Deep Learning AMI, Ubuntu 24.04.4, kernel 6.17.0-1019-aws; ships with Lustre client / EFA driver / CUDA / GDS tools, see version table below) |
| CPU/NUMA | 192 vCPU, 2 NUMA nodes |
| NIC layout | card0 = 1 plain interface (SSH/mgmt) + card1~16 = **16 EFA** (data transfer) |
| FSx Lustre | PERSISTENT_2, 250 MB/s/TiB, `EfaEnabled=true`, same AZ (us-west-2a), 2×OST 18.4T each, 36.8T total |

### Software / kernel / driver versions (measured on the instance)

| Component | Version [Measured] |
|---|---|
| OS distribution | **Ubuntu 24.04.4 LTS (Noble Numbat)** (VERSION_ID 24.04) |
| Kernel | **6.17.0-1019-aws** (x86_64) |
| NVIDIA driver | **595.71.05** (Nvidia Open Driver) |
| CUDA (driver-supported) | **13.2** (Cuda Driver Version 13020; instance has cuda-12.8/12.9/13.0/13.2, `/usr/local/cuda` → default) |
| EFA kernel module (efa kmod) | **3.0.0g** |
| EFA installer | **1.47.0** |
| kefalnd (P6+ LNet EFA driver) | **1.2.2** (requires ≥1.1.1) |
| Lustre client (userspace + kmod) | **2.15.6** |
| nvidia-fs (GDS kernel module) | **2.29** (insmod'd, requires ≥2.24.2) |
| libcufile (GDS userspace) | **2.12** |

> **Strongly recommend DLAMI**: Lustre client, EFA driver, CUDA and GDS tools are all pre-installed, so the script can use `--skip-driver` to skip the driver-install step.

Prerequisites (nothing works if these three are not met):
1. **The EFA client MUST be in the same AZ as the FSx Lustre** (cross-AZ → OST DISCONN).
2. **Security group self-referencing allow-all** (client SG and FSx SG must allow all EFA traffic from each other).
3. Client OS: AL2023 / RHEL9.5+ / Ubuntu22.04+ (kernel 6.8+).

---

## 2. Configure EFA + GDS (per the AWS official User Guide)

Official doc: <https://docs.aws.amazon.com/fsx/latest/LustreGuide/configure-efa-clients.html>

One command does it all (the script wraps official Step 1~4 + mount + verification):

```bash
sudo FSX_DNS=<fsid>.fsx.us-west-2.amazonaws.com \
     FSX_MOUNTNAME=<mountname> MNT=/fsx \
     bash configure-fsx-lustre-efa-gds.sh --gds --skip-driver
```

What the script does, following the official flow:
1. **Step 2b (GDS driver)**: if nvidia-fs is not loaded on the DLAMI, build & `insmod` from `github.com/NVIDIA/gds-nvidia-fs` per official docs (`NVFS_MAX_PEER_DEVS=128 NVFS_MAX_PCI_DEPTH=16`). Requires nvidia-fs ≥ 2.24.2.
2. **Add GDS allowlist** (B300-specific, see Appendix C).
3. **Step 3 (configure EFA)**: download AWS `configure-efa-fsx-lustre-client.zip`, run `sudo ./setup.sh --optimized-for-gds` — imports Lustre modules, configures TCP+EFA interfaces, creates a systemd service that re-configures on reboot.
4. **Step 4 (inspect interfaces)**: list EFA NICs + `lnetctl net show`.

### Configuration result [Measured]

`setup.sh --optimized-for-gds` automatically brings up all **16 @efa NIs**, with no "No EFA devices found for NUMA node X" error:

```
options libcfs cpu_npartitions=16 cpu_pattern="0[0..11] 1[12..23] 2[24..35] 3[36..47]
  4[96..107] 5[108..119] 6[48..59] 7[60..71] 8[72..83] 9[84..95]
  10[144..155] 11[156..167] 12[168..179] 13[180..191] 14[120..131] 15[132..143]"
```
- 16 EFAs cleanly map to 16 CPTs (CPU Partition Tables) across 2 NUMA nodes.
- `lnetctl net show`: 1 × tcp NI (card0, SSH/mgmt) + **16 × @efa NI** (data).

---

## 3. Mount FSx for Lustre (official mount command)

```bash
sudo mkdir -p /fsx
sudo mount -t lustre -o relatime,flock <fsid>.fsx.us-west-2.amazonaws.com@tcp:/<mountname> /fsx
```

**⚠️ After mounting, OSTs are briefly `CONNECTING` (~15s); you MUST wait until they turn `FULL`/`IDLE` before running IO**, otherwise IO fails / shows no traffic. Verify:

```bash
lctl get_param -n osc.*.ost_server_uuid
#  <mountname>-OST0000_UUID  IDLE
#  <mountname>-OST0001_UUID  IDLE      # FULL/IDLE = connected; DISCONN = broken (usually cross-AZ or missing SG self-ref)
lfs df -h /fsx
#  MDT 549.9G + 2×OST 18.4T = 36.8T
```

---

## 4. FIO performance test [Measured]

```bash
# sequential write
sudo fio --name=sw --directory=/fsx/fiotest --rw=write --bs=1M --size=8G \
  --numjobs=8 --ioengine=libaio --direct=1 --iodepth=32 --group_reporting
# sequential read (drop caches first)
sudo sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
sudo fio --name=sr --directory=/fsx/fiotest --rw=read  --bs=1M --size=8G \
  --numjobs=8 --ioengine=libaio --direct=1 --iodepth=32 --group_reporting
# random read
sudo fio --name=rr --directory=/fsx/fiotest --rw=randread --bs=64k --size=4G \
  --numjobs=4 --ioengine=libaio --direct=1 --iodepth=16 --group_reporting
```

Results:

| Test | Bandwidth |
|---|---|
| Seq write 1M×8jobs iodepth32 | **10.9 GB/s** (10.2 GiB/s) |
| Seq read 1M×8jobs iodepth32 | **45.2 GB/s** (42.1 GiB/s) |
| Rand read 64k×4jobs iodepth16 | **3.26 GB/s** (3112 MiB/s) |

> Seq read 45.2 GB/s ≈ 362 Gbps — aggregate bandwidth across 16 EFA NIs is high. Read >> write (writes must land on 2 OSTs + metadata sync).

---

## 5. Verify traffic actually goes over EFA, using LNet [Measured · hard proof]

**The most direct proof** = compare each EFA NI's LNet statistics before/after FIO (`lnetctl net show -v 4` is the most verbose level in the official Lustre/Whamcloud troubleshooting guide, printing `send_count/recv_count/drop_count` per NI). Two commands, each with a purpose:

**① Aggregate total** (quickly tell whether anything is being sent/received — run before & after FIO and see if the totals jump):
```bash
sudo lnetctl net show -v 4 | awk '/net type: efa/,0' \
  | awk '/send_count:/{s+=$2}/recv_count:/{r+=$2}END{print "send_count="s" recv_count="r}'
```

**② Per-NI detail** (see how much each EFA NIC carries — check whether all 16 NICs share the load):
```bash
sudo lnetctl net show -v 4 | awk '/net type: efa/,0' | grep -E 'nid:|send_count|recv_count'
```

② output looks like (one block per @efa NI, with nid header — see at a glance which NICs carry traffic):
```
- nid: <efa-nid-1>@efa
      send_count: 88471
      recv_count: 108468
- nid: <efa-nid-2>@efa
      send_count: 88536
      recv_count: 108517
... (16 EFA NIs)
```

① before/after FIO aggregate (sum of 16 NIs):

| LNet efa counters (sum of 16 NIs) | Before FIO | After FIO | Delta |
|---|---|---|---|
| send_count | 196,819 | **998,780** | +801,961 |
| recv_count | 262,355 | **1,211,772** | +949,417 |

> After heavy FIO read/write, send/recv_count surge → **hard proof that the Lustre data plane sends/receives over the EFA NIs**.
> [Measured] Using ② for detail: the 16 EFA NIs have **fairly balanced** send_count (~88k each), meaning all 16 NICs share the load.
> (Note: how much a single NI carries depends on OST count and concurrency; more OSTs / higher concurrency → more even spread.)

---

## 6. Verify GDS with gdscheck / gdsio [Measured]

```bash
sudo /usr/local/cuda/gds/tools/gdscheck -p        # platform self-check
sudo /usr/local/cuda/gds/tools/gdsio -D /fsx/gdstest -d 0 -w 8 -s 4G -i 1M -x 0 -I 1  # GPUD write
```

### Key gdscheck -p output
```
Platform verification succeeded          # core: full GDS stack works
DDN EXAScaler : Supported                # Lustre GDS path supported
fs.lustre.posix_gds_min_kb : 0
GPU index 0..7 NVIDIA B300 SXM6 AC : supports GDS   # all 8 GPUs support it
Nvidia Driver Info Status: Supported (Nvidia Open Driver Installed)
```

### gdsio throughput (8 threads, 1MB IO, 4G/thread)
| XferType | Read | Write |
|---|---|---|
| **GPUD (GPUDirect Storage, storage→GPU memory directly)** | **3.53 GiB/s** | **3.73 GiB/s** |
| CPUONLY | 4.56 GiB/s | 4.88 GiB/s |

> The GPUD path works (storage directly to GPU memory, bypassing the CPU bounce buffer). **CPUONLY being slightly faster here is normal** — GDS pays off at higher concurrency / larger IO / when saving CPU memory bandwidth matters; the point here is to **prove the GPUD stack is fully functional**.

---

## 7. Script usage

```bash
# Plain EFA (no GDS)
sudo FSX_DNS=<fsid>.fsx.us-west-2.amazonaws.com FSX_MOUNTNAME=<mountname> \
     bash configure-fsx-lustre-efa-gds.sh

# Enable GDS (B300 usage; DLAMI already has Lustre/EFA drivers, add --skip-driver)
sudo FSX_DNS=<fsid>.fsx.us-west-2.amazonaws.com FSX_MOUNTNAME=<mountname> MNT=/fsx \
     bash configure-fsx-lustre-efa-gds.sh --gds --skip-driver
```

The script performs all of Sections 2~6 automatically (including OST-ready wait, fio auto-install, EFA before/after comparison, gdscheck/gdsio).

---

## 8. B300 (16 EFA) vs B200 (8 EFA)

| Dimension | p6-b300.48xlarge | p6-b200.48xlarge |
|---|---|---|
| EFA interfaces | **16** [Measured] | 8 |
| MaximumNetworkCards | 17 [Measured via describe] | 9 [Inferred] |
| GPU | 8×B300 SXM6 (~268GB/card) [Measured] | 8×B200 |
| GDS official allowlist | not yet listed, must add manually [Measured] | already listed |
| Config flow | same as B200 (same setup.sh), only extra allowlist add | natively supported |

> B300 vs B200 = EFA NICs doubled (16 vs 8) + GPU generation bump. The FSx Lustre EFA/GDS config flow is identical; the only extra step is adding b300 to the GDS allowlist (removable once AWS updates the script).

---
---

# Appendix · Gotchas (not config-related, for avoidance)

## A. Gotcha: how to correctly attach B300's 16 EFA NICs

B300's 16 EFA interfaces are spread across 16 network cards (`MaximumNetworkCards=17`). **`run-instances` by default brings up only card0**, so inside the instance you see only 2 EFA devices — you must declare all NICs explicitly.

### ✅ Correct way (16 EFA at launch, one shot)
Use `--network-interfaces` at `run-instances` to declare all 17 NICs at once: card0 = plain interface (SSH/mgmt), card1~16 = 16 efa:

```bash
# NIC spec (card0 interface + card1~16 efa); note: multi-NIC cannot use AssociatePublicIpAddress
--network-interfaces \
  '{"NetworkCardIndex":0,"DeviceIndex":0,"InterfaceType":"interface","Groups":["<sg>"],"SubnetId":"<subnet>","DeleteOnTermination":true}' \
  '{"NetworkCardIndex":1,"DeviceIndex":1,"InterfaceType":"efa","Groups":["<sg>"],"SubnetId":"<subnet>","DeleteOnTermination":true}' \
  ... (card2~16 likewise)
```

Two accompanying gotchas:
1. **Multi-NIC cannot use `--associate-public-ip-address`** (returns `InvalidParameterCombination`) → drop it.
2. A multi-NIC instance **gets no auto public IP** → after launch, associate an EIP to card0's primary ENI to SSH:
   ```bash
   aws ec2 allocate-address --domain vpc
   aws ec2 associate-address --allocation-id <eipalloc> --network-interface-id <card0-eni>
   ```

### ❌ The wrong path (do not follow)
First attempt used `--associate-public-ip-address` with a single NIC → only 2 EFA, forcing after-the-fact attach: EFA NICs **can only be attached while the instance is stopped** (attaching while running returns `IncorrectState: Interface type 'efa' can only be attached to an instance in state stopped`). You'd have to `create-network-interface --interface-type efa` → `stop` → `attach-network-interface --network-card-index N` one by one → `start`, which also releases the public IP (needing EIP re-association), and still only produced 15. **The correct way is to declare everything at launch.**

## B. Gotcha: special parameter for launching from a Capacity Block

B300 on-demand capacity is scarce, so it is usually reserved via **Capacity Block**. Launching from a Capacity Block reservation with only `--capacity-reservation-specification` returns:
```
InvalidParameterValue: The market type (purchasing) option is not valid
```
- **Root cause**: this CR has `ReservationType=capacity-block` (an independent market type, not a normal on-demand CR).
- **Fix [Measured]**: `run-instances` must **also** include `--instance-market-options 'MarketType=capacity-block'`:
  ```bash
  aws ec2 run-instances ... \
    --instance-market-options 'MarketType=capacity-block' \
    --capacity-reservation-specification 'CapacityReservationTarget={CapacityReservationId=<cr-id>}'
  ```

## C. Gotcha: GDS allowlist does not include B300

`setup.sh --optimized-for-gds` returns `Instance type p6-b300.48xlarge does not support Lustre GDS`.
- **Root cause**: the `GDS_SUPPORTED_INSTANNCES` allowlist in AWS `configure-efa-fsx-lustre-client.py` only has `p5/p5e/p5en/p6-b200`, not b300.
- **Fix [Measured]**: add `"p6-b300.48xlarge",` to the allowlist array (the script does this idempotently); no other logic change and it runs through.
- **Script idempotency bug (fixed)**: do not use `grep -q '"p6-b300.48xlarge"'` to test "already added" (that string also appears elsewhere in the .py, causing a false positive). Match the exact allowlist line `^    "p6-b300\.48xlarge",$` instead.

## D. Gotcha: DLAMI does not ship fio by default

Under the `--skip-driver` path, if the script silently fails to install fio, all FIO runs fail with `command not found`. Fixed in the script: fio installation is independent of the driver-install step and `exit 1`s if it can't install.
