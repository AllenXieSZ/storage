import os
from datasets import load_dataset
from transformers import (AutoImageProcessor, AutoConfig, AutoModelForImageClassification,
                          TrainingArguments, Trainer)
import torch
from torchvision.transforms import (Compose,RandomResizedCrop,RandomHorizontalFlip,ToTensor,Normalize,Resize,CenterCrop)
MODEL="google/vit-huge-patch14-224-in21k"
OUT="/fsx/train/img_ckpt"
os.environ.setdefault("HF_HOME","/fsx/train/hf_cache")
MAX_STEPS=int(os.environ.get("MAX_STEPS","100"))
ds=load_dataset("ethz/food101",split="train")
labels=ds.features["label"].names
proc=AutoImageProcessor.from_pretrained(MODEL)
sz=proc.size.get("shortest_edge",224) if isinstance(proc.size,dict) else 224
mean,std=proc.image_mean,proc.image_std
tf=Compose([RandomResizedCrop(224),RandomHorizontalFlip(),ToTensor(),Normalize(mean,std)])
def xf(b):
    b["pixel_values"]=[tf(img.convert("RGB")) for img in b["image"]]
    return b
ds.set_transform(xf)
cfg=AutoConfig.from_pretrained(MODEL,num_labels=len(labels),image_size=224)
model=AutoModelForImageClassification.from_config(cfg)
def coll(ex):
    import torch
    return {"pixel_values":torch.stack([e["pixel_values"] for e in ex]),
            "labels":torch.tensor([e["label"] for e in ex])}
args=TrainingArguments(output_dir=OUT,max_steps=MAX_STEPS,
  per_device_train_batch_size=32,learning_rate=1e-3,warmup_steps=1000,
  lr_scheduler_type="cosine",weight_decay=0.05,
  save_strategy="steps",save_steps=1000,save_total_limit=30,
  logging_steps=50,report_to="none",bf16=True,tf32=True,
  dataloader_num_workers=8,ddp_find_unused_parameters=False,remove_unused_columns=False)
tr=Trainer(model=model,args=args,train_dataset=ds,data_collator=coll)
tr.train(resume_from_checkpoint=True)
if int(os.environ.get("RANK","0"))==0:
    tr.save_model(OUT+"/final"); print("IMG_TRAIN_DONE")
