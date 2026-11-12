# train/lines · 两条训练线的真实目录（2026-11-01 物理迁移完成）

> 9B（OxCoder）与 27B（KittyRev GEN3）在同一 `train/` 下并行。
> 语料**同源**（kitty 部分重合 98.1%），但**文件已物理分开**：不是 junction、不是软链，是真目录。
> 迁移脚本 `train/lines/_migrate_real.sh` · 路径改写 `train/lines/_rewrite_paths.py`（409 个文件）

```text
train/
├─ lines/
│   ├─ 9b-oxcoder/     9B 线：models / out / data / eval / logs / tools
│   ├─ 27b-kittyrev/   27B 线：base / local-pack / data / kitty-rev / quant / merged
│   └─ _shared/        共享（只读）：data/nsfw · data/raw · scripts · hf · tools
├─ .venv/              共用 Python 环境（两线都用，不迁移）
├─ data/               空壳（内容已迁走，保留防旧脚本误写）
└─ logs/               两线日志混放（前缀区分：9B=z-*/2b-*/gate-*，27B=gen3-*/monitor-*）
```

## 快速对照

| 想找 | 去 |
|---|---|
| 9B adapter 与训练产物 | `train/lines/9b-oxcoder/out/` |
| 9B 语料 | `train/lines/9b-oxcoder/data/{kitty-reverse,agent-traj,nsfw-gated,eval}/` |
| 27B 量化成品 | `train/lines/27b-kittyrev/local-pack/gen*/` |
| 27B 打包数据集 | `train/lines/27b-kittyrev/data/versions/` |
| 两线共用脚本 | `train/lines/_shared/scripts/` |

## 规则（摘要，正文见根 `AGENTS.md §3.1`）

```text
1) 只在所属线目录内写文件，不跨线写
2) 产物落位：9B → lines/9b-oxcoder/out/；27B → lines/27b-kittyrev/local-pack|merged/
3) 数据集落位：9B → lines/9b-oxcoder/data/；27B → lines/27b-kittyrev/data/versions/
4) 评测集隔离：9B 只用 lines/9b-oxcoder/data/eval/；不跨线借用
5) 共享区只读；改前确认两线都没有训练在读
6) 新脚本带线前缀：9B=z_*/2b_*/p3_*；27B=gen3_*/local_*/convert_*/gsq_*
```

## 跨线事实（已核实）

| 比对 | 结果 |
|---|---|
| 27B gen3 ∩ 9B kitty-clean | 23221 / 23674 = 98.1% |
| 27B gen3 ∩ 9B 2B 门控集 | 6861 / 25862 = 26.5% |
| 9B 门控评测集 ∩ 27B gen3 | 0 |

```text
同源 ≠ 同文件：文件各自独立；跨线比分数没有意义（清洗 / 混配 / 模型规模都不同）。
```
