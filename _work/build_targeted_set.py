# -*- coding: utf-8 -*-
"""定向微调第 2 步：从修正版数据里挑「被修过的行」+ 等量保持样本，组成小配方

为什么不一锅端训 7562 行：
  错误只集中在 204 行（2.7%），整训一轮要 108 分钟且会把旧能力冲掉。
  定向微调只喂「改对的那批」+ 少量保持样本，20 分钟内完成，且不伤原能力。

配方（可调）：
  core   204 行 = 含错误 action 被修正的行（真正要学的）
  keep   N 行 = 从修正版里随机抽「参数本来就正确」的行，防遗忘、防只背这 204 条
  epochs 3 ⇒ 步数 = (core+keep)*3/4

产物：data/_legacy/mix-z-re-targeted.jsonl
"""
import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
OLD = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-fixed.jsonl")
NEW = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-actfix.jsonl")
OUT = os.path.join(L9B, "data", "_legacy", "mix-z-re-targeted.jsonl")

KEEP_N = 400      # 保持样本数
EPOCHS = 3
SEED = 42

rng = random.Random(SEED)
old = [l.strip() for l in io.open(OLD, encoding="utf-8") if l.strip()]
new = [l.strip() for l in io.open(NEW, encoding="utf-8") if l.strip()]
assert len(old) == len(new), "行数不一致 %d vs %d" % (len(old), len(new))

core = [n for o, n in zip(old, new) if o != n]
pool = [n for o, n in zip(old, new) if o == n]
print("=" * 92)
print("定向配方构建")
print("=" * 92)
print("  全量 %d 行 → core（被修过）%d 行 · pool（未变）%d 行" % (len(new), len(core), len(pool)))

keep = rng.sample(pool, min(KEEP_N, len(pool)))
mix = core + keep
rng.shuffle(mix)

with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for l in mix:
        f.write(l + "\n")

steps = len(mix) * EPOCHS // 4
print("  keep %d 行 → 合计 %d 行 × %d epoch = %d 步（ctx4096 约 %.0f min）"
      % (len(keep), len(mix), EPOCHS, steps, steps * 3.43 / 60))
print("  → %s" % OUT)
print()
print("  训练命令：")
print("""  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \\
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \\
  ./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/train_qlora9b.py \\
    --base  train/lines/9b-oxcoder/models/OxCoder-9B \\
    --data  %s \\
    --stage re \\
    --init-adapter train/lines/9b-oxcoder/out/z-re-v4/final \\
    --out   train/lines/9b-oxcoder/out/z-re-targeted \\
    --ctx 4096 --epochs %d --lr 8e-6 --ga 4 --bs 1 --seed 42 \\
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \\
    --save-steps 120 --save-total-limit 8""" % (OUT.replace("\\", "/"), EPOCHS))
