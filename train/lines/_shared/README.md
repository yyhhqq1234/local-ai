# 共享区（两条线都读，写需双方确认）

> 2026-11-01 物理迁移完成。这里放的是**两线都要用**的东西：源语料、脚本、HF 缓存、工具。
> 只读为默认；确需修改时，先确认两条线都没有训练/评测在读它。

## 目录

```text
train/lines/_shared/
├─ data/nsfw/     NSFW 源语料（nsfw-lexicon-v9.json / glossary / triage / train-cont）
├─ data/raw/      原始未切分轨迹（两线上游）
├─ scripts/       两线脚本混放（按文件名前缀区分归属，见下表）
├─ hf/            HuggingFace 本地缓存
└─ tools/         共用工具
```

## `scripts` 归属表

| 归属 | 文件 |
|---|---|
| 9B | `train_qlora9b.py` · `eval_2a_code.py` · `eval_multi_adapter.py` · `nsfw_gate_local.py` · `check_*.py` · `mix_*.py` · `build_z_datasets.py` · `zb_*.sh` · `z2a_*.sh` · `2b_*.sh` · `p3_*.sh` · `watch_2b.sh` |
| 27B | `local_merge_lora.py` · `local_*.py` · `build_gen2*.py` · `build_gen3.py` · `convert_gguf_safe.py` · `gsq_rco_plan.py` · `attach_mtp.py` |
| 两线共用 | `build_nsfw_gated.py` · `build_gate_val_test.py` · `audit_gen2_data.py` · `nsfw_gate_eval.py` |

## 硬规则

1. 默认只读；修改前确认对方没有训练/评测在读同一文件。
2. 新增脚本必须带线前缀（9B：`z_*` / `2b_*` / `p3_*`；27B：`gen3_*` / `local_*` / `convert_*` / `gsq_*`）。
3. 共享语料改动会影响两线数据构建结果，改完需在两线 README 各记一行。
4. `train/logs/` 不在本区：两线日志混放，靠前缀区分（9B：`z-*` / `2b-*` / `gate-*`；27B：`gen3-*` / `monitor-*`）。
