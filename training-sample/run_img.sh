#!/bin/bash
export HF_HOME=/fsx/train/hf_cache
export OMP_NUM_THREADS=8
export TOKENIZERS_PARALLELISM=false
export MAX_STEPS=${MAX_STEPS:-80000}
cd /root
torchrun --nproc_per_node=8 img_train.py > /root/img_train.log 2>&1
echo IMG_EXIT=$? >> /root/img_train.log
