# nsfw/ 清理台账（删除前记录）

- 生成时间: 2026-10-27T12:14:05.520Z
- 删除范围: _superseded / _re-strip-backup-20261027115222（仅历史版本与备份，活跃数据未动）
- 文件数: 18，合计 712.5 MB

| # | 路径 | MB | sha256(前16) | 判定理由 |
|---|---|---|---|---|
| 1 | _re-strip-backup-20261027115222/final-nsfw.jsonl | 72.1 | 78b59b9477f2f850 | 剔 re 之前的全量原件备份（含 4596 条逆向样本），当前训练集已不含 re |
| 2 | _re-strip-backup-20261027115222/_superseded/final-joint.jsonl | 72.1 | 2fe3bba493624310 | 剔 re 之前的全量原件备份（含 4596 条逆向样本），当前训练集已不含 re |
| 3 | _re-strip-backup-20261027115222/mix-nsfw.jsonl | 71.2 | 9627da25538afe4c | 剔 re 之前的全量原件备份（含 4596 条逆向样本），当前训练集已不含 re |
| 4 | _re-strip-backup-20261027115222/_superseded/mix-joint.jsonl | 71.2 | f99783276861e8a7 | 剔 re 之前的全量原件备份（含 4596 条逆向样本），当前训练集已不含 re |
| 5 | _superseded/nsfw.jsonl | 70.9 | fcc9128eeea2c86b | 无版本号基础语料，与 nsfw-v3 字节相同 |
| 6 | _superseded/structure-20261027-200103/nsfw-v3.jsonl | 70.9 | fcc9128eeea2c86b | 三份同源训练集，已拆分为 train-*.jsonl(13668) |
| 7 | _superseded/final-joint.jsonl | 70.5 | c9aed25f5b7b80fe | joint 版同源副本（剔 re 前） |
| 8 | _superseded/mix-joint.jsonl | 70.5 | 5c815fb34200848b | joint 版同源副本（剔 re 前） |
| 9 | _superseded/structure-20261027-200103/final-nsfw.jsonl | 70.5 | d5e95345308b0ebd | 三份同源训练集，已拆分为 train-*.jsonl(13668) |
| 10 | _superseded/structure-20261027-200103/mix-nsfw.jsonl | 70.5 | 5a49c1c7b6fcf37c | 三份同源训练集，已拆分为 train-*.jsonl(13668) |
| 11 | _superseded/structure-20261027-200103/pre-variant-merge/nsfw-lexicon-v7.json | 0.6 | 2e92f4bd2728203d | 变体归并前的 lexicon v7 |
| 12 | _superseded/structure-20261027-200103/pre-v9/nsfw-lexicon-v8.json | 0.6 | 781b1a671690933e | v9 升级前的 lexicon v8 |
| 13 | _superseded/structure-20261027-200103/nsfw-lexicon-v6.json | 0.3 | 2b0f3df8d392700c | v6 词表，已被 v9 取代 |
| 14 | _superseded/structure-20261027-200103/nsfw-glossary-v2.jsonl | 0.2 | 0af0d5b8ebbf6346 | glossary 三表原件，已合并为 merged(283) |
| 15 | _superseded/nsfw-glossary.jsonl | 0.1 | 47fe91f3341abc76 | glossary v1 旧格式（252 行无 id），已被 v2 取代 |
| 16 | _superseded/structure-20261027-200103/nsfw-glossary-r4.jsonl | 0.0 | 3adec4ef5d330b9f | glossary 三表原件，已合并为 merged(283) |
| 17 | _superseded/structure-20261027-200103/nsfw-glossary-v3-new.jsonl | 0.0 | 46383c0a9087a659 | glossary 三表原件，已合并为 merged(283) |
| 18 | _superseded/nsfw-coverage.json | 0.0 | cebce702644624f8 | 12:29 早期覆盖报告，已被后续覆盖统计取代 |

## 保留（未动）
```
train-{cont,scene,multi,style,expand}.jsonl
nsfw-glossary-merged.jsonl
nsfw-lexicon-v9.json
nsfw-v3-coverage.json  → 将更新为 nsfw-coverage.json
nsfw-index/  nsfw-triage/  → 将更新元数据
MANIFEST.json  → 将重写
```
