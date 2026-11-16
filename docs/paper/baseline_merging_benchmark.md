# Mainstream Baseline Comparison: Model Merging & Multi-Task Specialization

| Method | Category | Citation | Tool Acc (%) | Tool Evasion (%) | Code Pass (%) | Cross-Interference (%) | Notes |
|---|---|---|---|---|---|---|---|
| **Base Zero-Shot** | Baseline | Qwen Team, 2024 | 75.0% | 25.0% | 74.2% | 0.0% | High hallucination (10 fabricated tools), lacks low-level API syntax |
| **ReAct (Prompt-Only)** | Prompt Engineering | Yao et al., 2022 | 77.5% | 15.0% | 73.0% | 0.0% | Context dilution under full schemas; fails complex L3 diagnostics |
| **Sequential SFT** | Continual Learning | Standard Curriculum | 10.0% | 82.5% | 78.4% | 87.5% | Catastrophic Overwrite: Stage 2 completely destroyed Stage 1 router |
| **Task Arithmetic (tau=0.5)** | Model Merging | Ilharco et al., 2022 | 55.0% | 27.5% | 64.8% | 32.5% | Subspace interference: mutual degradation on both domains |
| **TIES-Merging (p=0.8)** | Model Merging | Yadav et al., 2023 | 62.5% | 22.5% | 69.1% | 22.5% | Sign trimming reduces collision, but low-entropy commands still dilute |
| **Joint Mix SFT (Scheme X)** | Multi-Task Tuning | Caruana, 1997 | 67.5% | 15.0% | 45.0% | 17.5% | Compromised dual-loss: coding ability significantly compromised |
| **DSDA Scheme Z (Ours)** | Dynamic Modular | This Work | 82.5% | 0.0% | 78.5% | 0.0% | Optimal dual-preservation: zero interference and zero evasions |
