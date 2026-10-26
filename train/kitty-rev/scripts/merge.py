#!/usr/bin/env python
"""merge.py —— 合并 LoRA adapter 到全量权重（CPU 上做，避免吃显存）

用法:
  python merge.py --size 8b
  python merge.py --size 27b --adapter train\\out\\adapter --dest train\\merged\\merged-27b
  python merge.py --size 27b --delete-base-after   # 合并成功后删 base（省磁盘，谨慎）
"""
import argparse
import os
import shutil
import sys

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.join(TRAIN_ROOT, "hf"))

BASE = {
    "8b":  os.path.join(TRAIN_ROOT, "base", "Qwen3-8B"),
    "27b": os.path.join(TRAIN_ROOT, "base", "Qwen3.8-27B"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=["8b", "27b"], default="8b")
    ap.add_argument("--base", default=None)
    ap.add_argument("--adapter", default=os.path.join(TRAIN_ROOT, "out", "adapter"))
    ap.add_argument("--dest", default=None)
    ap.add_argument("--delete-base-after", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    base = a.base or BASE[a.size]
    dest = a.dest or os.path.join(TRAIN_ROOT, "merged", f"merged-{a.size}")

    for p, label in ((base, "base"), (a.adapter, "adapter")):
        if not os.path.isdir(p):
            print(f"[FATAL] {label} 不存在: {p}")
            sys.exit(1)

    ad_size = sum(os.path.getsize(os.path.join(a.adapter, f))
                  for f in os.listdir(a.adapter)
                  if os.path.isfile(os.path.join(a.adapter, f))) / 2**20
    free = shutil.disk_usage(TRAIN_ROOT).free / 2**30
    print(f"[base   ] {base}")
    print(f"[adapter] {a.adapter}  ({ad_size:.1f} MiB)")
    print(f"[dest   ] {dest}")
    print(f"[disk   ] 剩余 {free:.1f} GiB")

    need = {"8b": 16, "27b": 54}[a.size]
    if free < need * 1.1:
        print(f"[WARN] 合并约需 {need} GiB，剩余仅 {free:.1f} GiB —— 建议先删 gguf\\ 或旧 merged\\")
    if a.dry_run:
        print("[dry-run] 退出")
        return

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    print("[load] base on CPU (bf16)")
    model = AutoModelForCausalLM.from_pretrained(
        base, dtype=torch.bfloat16, device_map="cpu", trust_remote_code=True, low_cpu_mem_usage=True
    )
    print("[load] adapter")
    model = PeftModel.from_pretrained(model, a.adapter)
    print("[merge] merge_and_unload")
    model = model.merge_and_unload()

    print(f"[save] {dest}")
    os.makedirs(dest, exist_ok=True)
    model.save_pretrained(dest, safe_serialization=True, max_shard_size="5GB")
    AutoTokenizer.from_pretrained(a.adapter).save_pretrained(dest)
    print("[done]")

    if a.delete_base_after:
        print(f"[delete] {base}")
        shutil.rmtree(base, ignore_errors=True)
        print("[delete] done（如需再训练，重新跑 fetch_base.py）")

    print("下一步: 转 GGUF → convert_hf_to_gguf.py，再走 ninfer-v3 converter 回炉")


if __name__ == "__main__":
    main()
