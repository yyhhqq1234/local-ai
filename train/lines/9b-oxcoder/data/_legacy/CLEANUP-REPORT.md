# train/data 根目录清理台账

- 生成时间: 2026-10-27T12:30:50.643Z
- 范围: train/data/ 根（不含 nsfw/ 与 kitty-reverse/）

## 删除
| 文件 | 字节 | sha256(前16) | 理由 |
|---|---|---|---|
| dedupe-report.json | 28453 | 00c0fd72d16dc38f | dedupe_re.py 的产物，针对已重构前的 final-re 去重，脚本可重跑生成 |
| refine-report.json | 12388 | dd4b0eb19c16c294 | refine_re.py 的产物，针对已重构前的 final-re 精炼，脚本可重跑生成 |
| final-manifest.json | 555 | 336ca0c0c3b50e44 | 描述旧形态（final_re 1608 / final_nsfw 15276 含 re）；配比参数已继承至 MANIFEST.json |

## 保留并更新
| 项 | 处理 |
|---|---|
| `versions/` | 保留 4 份历史快照（final-joint / final-nsfw / final-re / mix-re，10-27 01:18~02:27）；**新增本代 8 份快照**（时间戳 20261027-203028）：nsfw 5 分片 + glossary-merged + lexicon-v9 + kitty-core，各配 .sha256 |
| `train.example.jsonl` | 保留（RUNBOOK 引用的格式冒烟样例，3 条） |
| `MANIFEST.json` | **新建**：两条训练线总览 + 训练配比（re_weight/replay/seed，继承旧 final-manifest）+ 快照索引 + 清理台账 |

## 依据
```
train/TRAINING-LINEAGE.md 铁律①：数据必须打快照 train/lines/27b-kittyrev/data/versions/<name>.<ts>.jsonl + .sha256
  → versions/ 是谱系锚点，不可删；本代数据此前缺快照，本次已补齐
scripts/dedupe_re.py · refine_re.py · build_final.py 会重新生成被删的 3 份报告
```
