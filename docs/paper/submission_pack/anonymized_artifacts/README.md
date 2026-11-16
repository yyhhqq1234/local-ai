# Anonymized Artifact Package for "Beyond Surface Adaptation"

This directory contains the core experimental evaluation fixtures, scripts, and benchmark configurations accompanying the paper:
*"Beyond Surface Adaptation: Deconstructing Memorization, Stage Overwriting, and Gating Biases in Domain-Specialized System Agents"*.

## Directory Layout
- `scripts/`:
  - `augment_user_queries.py`: Multi-axis query perturbation protocol ($K=4$).
  - `re_clusters.py`: Hard-negative tool clustering ($k=8\sim 12$, 11 functional clusters).
  - `nsfw_gate_local.py`: Dual-state safety gating verification protocol.
- `data/`:
  - `eval_cases_re.py`: Standardized 40-case evaluation benchmark (L1=12, L2=12, L3=16).

## Environment Setup
```bash
pip install torch transformers trl peft liger-kernel
```

## Running Evaluation Benchmarks
1. To run candidate clustering tool evaluation:
```bash
python scripts/re_clusters.py
```

2. To run dual-state safety gating verification:
```bash
python scripts/nsfw_gate_local.py --adapter <path_to_checkpoint>
```
