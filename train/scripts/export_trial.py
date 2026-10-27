#!/usr/bin/env python
"""export_trial.py — 从 Heretic study journal 直接导出指定 trial 的 LoRA adapter。

绕开 questionary（后台无 Windows console → NoConsoleScreenBufferError）。

复刻 main.py 的确定性链路：
    Settings() → Model(settings) → load_and_init_modifiers(settings, model)
    → Context → modifier.modify_model(ctx, trial.user_attrs["parameters"])
    → model.model.save_pretrained(save_directory)

用法：
  train/.venv/Scripts/python.exe train/scripts/export_trial.py \
      --model D:/.../train/models/OxCoder-9B \
      --quantization BNB_4BIT \
      --study-checkpoint-dir D:/.../train/logs/heretic-smoke5 \
      --trial-index 0 \
      --save-directory D:/.../train/models/OxCoder-9B-abl-lora \
      --batch-size 1 --max-batch-size 4 --max-response-length 48

注意：
  · 必须先在 study 里存在至少一个 COMPLETE trial
  · init 阶段会重跑 good/bad prompts 的 module I/O 收集（400+400 条），
    这一步与 trial 评估同量级耗时，无法跳过（ARA 需要真实激活）
"""
import glob
import os
import sys

import optuna
from optuna.storages import JournalStorage
from optuna.storages.journal import JournalFileBackend

from heretic.config import Settings
from heretic.model import Model
from heretic.modifier import load_and_init_modifiers
from heretic.plugin import Context


def find_journal(study_dir: str) -> str:
    cands = sorted(glob.glob(os.path.join(study_dir, "*.jsonl")))
    if not cands:
        sys.exit(f"[FATAL] 找不到 study journal: {study_dir}/*.jsonl")
    if len(cands) > 1:
        print(f"[WARN] 多个 journal，取第一个: {cands[0]}")
    return cands[0]


def load_trial(study_dir: str, trial_index: int):
    path = find_journal(study_dir)
    print(f"[study] {path}")
    storage = JournalStorage(JournalFileBackend(path))
    study = optuna.load_study(study_name="heretic", storage=storage)
    done = [t for t in study.trials if t.state.name == "COMPLETE"]
    print(f"[study] 总 trials={len(study.trials)} 完成={len(done)}")
    if not done:
        sys.exit("[FATAL] 没有 COMPLETE 的 trial，先跑一轮优化")
    done.sort(key=lambda t: t.number)
    for t in done:
        print(f"  trial {t.number}: values={t.values} params={t.user_attrs.get('parameters')}")
    if trial_index >= len(done):
        sys.exit(f"[FATAL] trial-index {trial_index} 超界（可用 0..{len(done)-1}）")
    return done[trial_index]


def main() -> int:
    settings = Settings()  # pydantic-settings 从 sys.argv 读取
    if settings.seed is None:
        # ARA 在 modify_model 里用 torch.Generator().manual_seed(seed)，
        # seed=None 会直接抛 RuntimeError（expected a long, got NoneType）。
        settings.seed = 42
        print("[seed] 未指定 --seed，回填 42（ARA 需要非空 seed）")
    if not settings.study_checkpoint_dir:
        sys.exit("[FATAL] 需要 --study-checkpoint-dir")
    if settings.save_directory is None:
        sys.exit("[FATAL] 需要 --save-directory")

    idx = settings.trial_index or 0
    trial = load_trial(settings.study_checkpoint_dir, idx)
    raw = trial.user_attrs["parameters"]
    print(f"[pick] trial {trial.number} → parameters={raw}")

    print("[load] Model(settings) ...")
    model = Model(settings)

    print("[init] load_and_init_modifiers（含 module I/O 收集，较慢）...")
    entries = load_and_init_modifiers(settings, model)
    modifier = entries[0].modifier
    modifier_name = entries[0].name
    print(f"[init] modifier = {modifier_name}")

    ctx = Context(settings=settings, model=model)

    parameters = modifier.parameters_class.from_dict(raw)
    print("[apply] modify_model ...")
    modifier.modify_model(ctx, parameters)

    out = settings.save_directory
    os.makedirs(out, exist_ok=True)
    print(f"[save] {out} ...")
    model.model.save_pretrained(out, max_shard_size=settings.max_shard_size)

    # processor / tokenizer 一并存，便于后续 merge 与转换
    if getattr(model, "processor", None) is not None:
        model.processor.save_pretrained(out)
        print("[save] processor 已存")
    model.tokenizer.save_pretrained(out)
    print("[save] tokenizer 已存")

    print(f"[DONE] adapter → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
