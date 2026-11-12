# 2B 门控训练集 v3 MANIFEST

| 项 | v2 | v3 |
|---|---|---|
| 总样本 | 25795 | **29281** |
| pos | 13951 | 13951 |
| neg | 8411 | 8411 |
| ctl | 3433 | **7200** |
| neg 中位长度 | 180 字 | **526 字** |
| neg token 占比 | 0.071 | **0.1548** |
| ctl token 占比 | — | 0.2043 |

## 针对的三条隐患

```text
① token 不平衡 → neg 180→450+ 字，neg token 占比 0.071→0.1548
② 模板句固定 → 20 套判定句 × 20 套解除提示 × 场景化四拍，逐条抽素材元素
③ ctl 过窄   → 3433(SWE) + 3000(kitty) + 1149(2A 轨迹) + 800(写作类非露骨)
```

## 训练命令（等 2B v2 收口后再起）

```powershell
train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py `
  --base train\lines\9b-oxcoder\out\z-2a-v7\final `
  --data train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated-v3.jsonl `
  --stage nsfw --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --lora-r 32 --lora-alpha 64 --seed 42 --use-liger-ce `
  --save-steps 300 --save-total-limit 8 `
  --out train\lines\9b-oxcoder\out\2b-nsfw-v3
```
