# NSFW 门控训练集 MANIFEST

| 项 | 值 |
|---|---|
| 总样本 | 25862 |
| 正样本（有开关→NSFW） | 13951 |
| 负样本（无开关→常规） | 8411 |
| 常规对照 | 3500 |
| pos:neg | 1.66 : 1 |
| system 加固正样本 | 4229 |
| 平均 token（正/负） | 1064 / 125 |

## 训练用法

```powershell
train\.venv\Scripts\python.exe -u train\scripts\train_qlora9b.py `
  --base train\out\2a-traj\final `
  --data train\data\nsfw-gated\train-2b-gated.jsonl `
  --stage nsfw --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 300 --save-total-limit 8 `
  --out train\out\2b-nsfw
```

## 验收（P6 前必跑）

```powershell
train\.venv\Scripts\python.exe train\scripts\nsfw_gate_eval.py --endpoint http://127.0.0.1:1234/v1
```

阈值：GateRecall ≥ 90% / **GateLeak ≤ 5%** / GateFPR ≤ 5%。
