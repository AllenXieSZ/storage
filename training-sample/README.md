# Training Sample — ViT-Huge Image Classification (from scratch) on 8×H100

A minimal, production-style distributed training sample: train **ViT-Huge/14 (632M params)**
from scratch on the **food101** dataset using **8× NVIDIA H100** (PyTorch DDP + HuggingFace Trainer).

Runs verified on an AWS **p5.48xlarge** (8×H100 80GB, NVLink/NVSwitch) with checkpoints stored
on an **FSx for Lustre** filesystem.

## Files

| File | Purpose |
|------|---------|
| `img_train.py` | The whole training script (36 lines). Loads dataset, builds a from-scratch ViT-Huge, runs 8-GPU DDP training via HF `Trainer`. |
| `run_img.sh`   | Launcher: sets env vars + `torchrun --nproc_per_node=8`. Reads `MAX_STEPS` from env. |

## Key design points

- **From scratch**: uses `AutoModelForImageClassification.from_config(...)` (random init), NOT
  `from_pretrained`. Initial loss ≈ ln(101) ≈ 4.6 as expected for 101-way classification.
- **Lazy transforms**: `ds.set_transform(xf)` applies image augmentation (RandomResizedCrop +
  HorizontalFlip + Normalize) on-the-fly per batch — the 100k-image dataset is never fully
  preprocessed into memory. Data streams batch-by-batch from disk.
- **Distributed**: `torchrun --nproc_per_node=8` launches 8 workers; HF `Trainer` handles DDP,
  NCCL all-reduce, mixed precision, checkpointing and LR scheduling automatically.
- **Mixed precision**: `bf16=True, tf32=True` for H100 acceleration.
- **LR schedule**: peak `1e-3`, 1000-step linear warmup, then cosine decay to ~0.
- **Resumable**: `tr.train(resume_from_checkpoint=True)` auto-resumes from the latest checkpoint
  in `output_dir` — survives crashes/preemption.
- **`remove_unused_columns=False`**: required so the `image` column survives into the transform
  (a common HF Trainer gotcha with image datasets).

## Usage

```bash
# install deps (CUDA 12.4 build)
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install transformers datasets accelerate torchvision

# calibrate speed (100 steps)
MAX_STEPS=100 bash run_img.sh

# full run (e.g. 80000 steps)
MAX_STEPS=80000 bash run_img.sh

# watch progress
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
grep -oE "[0-9]+/[0-9]+" img_train.log | tail
```

## Reference run (8×H100, food101, ViT-Huge 632M)

- ~0.13–0.16 s/step, ~1950 samples/s, 8 GPUs at 90–100% utilization, ~30GB/GPU.
- 80000 steps ≈ 2.9h; loss 4.5 → ~3.08.
- Multi-GPU comms: NCCL 2.21.5 auto-detects **NVLS (NVLink SHARP)** over 24 NVLink channels +
  NVSwitch — no manual NCCL tuning needed for single-node 8-GPU.

## Notes / paths

Paths in the scripts (`/fsx/...` for Lustre, `/root/...`) are environment-specific — adjust
`OUT`, `HF_HOME` and the log path to your setup. Everything else is portable.

> ⚠️ Store checkpoints on the shared/networked filesystem (e.g. Lustre), NOT the OS root disk.
> If the shared mount silently drops, writes fall back to the root disk and can fill it — verify
> the mount (`stat -f -c %T <dir>` should report your FS type, not `ext2/ext3`).
