# Lustre (No RAID / No Replica) — EBS Loss & Replacement Test with Continuous fio I/O

**Region:** AWS Ohio (us-east-2a)  |  **Date:** 2026-07-18  |  **Cluster:** lustre2 (bare-EBS OSTs)
**Purpose:** Contrast with the RAID1 cluster. Here OSTs are on **bare EBS (no RAID, no replica)**. Test losing one EBS volume, then adding a new one, with fio I/O running throughout.

---

## Cluster (same scale as the RAID1 one)
- 1 MDS (MGS+MDT0000) + 2 OSS (OST0/1 on OSS1, OST2/3 on OSS2) + 1 client
- i7i.2xlarge, AlmaLinux 8.10, Lustre 2.15.8, ldiskfs OSD
- **Each OST = 1× bare gp3 EBS (no mdadm, no mirror)** — 4 OST, ~390 GB
- fsname `lustre2`, MDS NID <PRIVATE_IP>@tcp, LNet tcp0

### Deploy note (repeat of known gotcha)
`dnf install kernel --enablerepo=lustre-server` pulled the **stock AlmaLinux kernel (553.144.1)** instead of the patched lustre kernel, because stock had a higher NVR. **Fix: install the exact NVR explicitly** `kernel-4.18.0-553.82.1.el8_lustre` (+devel/core/modules/headers), `grubby --set-default`, add `exclude=kernel*` to dnf.conf, reboot. Client dkms needs EPEL + PowerTools.

---

## Test Procedure & Commands

### 1. Baseline data + fio load
```bash
# 40×10MB files, 10 pinned on OST0 (lfs setstripe -c 1 -i 0), md5 recorded
# continuous fio on a dir striped across OST1,2,3 (survives OST0 loss):
lfs setstripe -c 3 -i 1 /mnt/lustre2/fio
fio --name=l2load --rw=randrw --bs=64k --numjobs=4 --ioengine=libaio \
    --direct=1 --iodepth=16 --runtime=1800 --time_based ...
```

### 2. Simulate EBS loss (data really destroyed)
```bash
# on OSS1:
umount /mnt/ost0
# from control host:
aws ec2 detach-volume --volume-id REDACTED
aws ec2 delete-volume --volume-id REDACTED   # OST0 data GONE
# mark OST0 inactive so FS keeps serving:
lctl set_param osp.lustre2-OST0000-osc-MDT0000.active=0   # on MDS
lctl set_param osc.lustre2-OST0000-*.active=0             # on client
```

### 3. Add a new EBS and rebuild OST0 (data NOT recoverable)
```bash
aws ec2 create-volume --size 100 --volume-type gp3 ...    # REDACTED
aws ec2 attach-volume --volume-id <new> --device /dev/sdb
# fresh format (empty), --replace tells MGS it replaces index 0:
mkfs.lustre --fsname=lustre2 --ost --mgsnode=<PRIVATE_IP>@tcp --index=0 --replace --reformat /dev/nvme1n1
systemctl daemon-reload        # IMPORTANT (see RAID1 report's systemd pitfall)
mount -t lustre /dev/nvme1n1 /mnt/ost0
lctl set_param osp.lustre2-OST0000-osc-MDT0000.active=1   # MDS
lctl set_param osc.lustre2-OST0000-*.active=1             # client
```

---

## Results (all measured)

### Filesystem behavior during EBS loss (OST0 inactive)
| Check | Result |
|---|---|
| fio (on OST1/2/3) | **kept running, uninterrupted** ✅ |
| 30 files NOT on OST0 | read OK 30 / FAIL 0 ✅ |
| 10 files ON OST0 | **OK 0 / FAIL 10 — data permanently lost** (EBS deleted, no replica) |
| Other 3 OST + MDT | fully operational, FS stayed online |

### Recovery timing
| Phase | Time |
|---|---|
| EBS loss (umount + detach + delete) | seconds |
| **Replacement (create + attach + mkfs + mount + reactivate)** | **~74 sec** |
| Data resync | **N/A — no data to sync (fresh empty OST)** |

### fio throughout the whole event (loss + replace + recovery)
- **363,805 reads / 363,879 writes, dropped=0, ZERO errors** ✅
- Sustained **183 MiB/s** (3-stripe across the 3 healthy OSTs)
- Never interrupted; FS fully usable the entire time

### After recovery
- OST0 back **ACTIVE** (fresh, empty); new files write+read OK on it
- All 4 OST ACTIVE, 390 GB, healthy

---

## Key Conclusion — Bare EBS vs RAID1 (the whole point)

| Aspect | Bare EBS (this test) | RAID1 (previous test) |
|---|---|---|
| Lose one EBS | **data on that OST permanently lost** | **no data loss — mirror serves** |
| FS availability | stays up on other OSTs; failed OST's files gone | stays up, failed OST's files intact |
| Recovery action | add new EBS + **mkfs fresh OST** (empty) | add new EBS + **RAID auto-rebuild** (data restored) |
| Recovery time (100G) | **~74 sec** (nothing to sync) | **~14-20 min** (must resync 100G) |
| Trade-off | fast to re-add, but data lost | slower rebuild, but zero data loss |
| Space cost | 1× | 2× |

**Bottom line:** Without RAID/replica, an EBS loss = that OST's data is gone for good; re-adding is fast (just reformat) but you only get an empty OST back. RAID1 costs 2× space and a longer rebuild, but survives the same failure with zero data loss. This is the fundamental durability-vs-cost trade-off for Lustre OST backing storage.

**Note:** Lustre itself has no built-in replication (until FLR mirroring, which is per-file and delayed-write; erasure coding is 2.16+). Bare-EBS OST durability relies entirely on the single EBS volume's own persistence.
