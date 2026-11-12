# 静默错回归集（silent-wrong regression）

这里的每个 `t_*.py` 都是一次**真实发生过**的「不报错但结果错」。它们不进正常单元测试，
因为当时没有任何用例失败 —— 只有把「当时错在哪」写成可执行断言，才能防复发。

```bash
# 全跑（纯 CPU，秒级，不加载模型、不读真实数据）
python scripts/regression/run_all.py

# 只跑匹配的
python scripts/regression/run_all.py t3 t6
```

退出码：0 = 全部 PASS，1 = 有 FAIL。

## 什么时候必须跑

改完下列任一文件后跑一遍（10 秒内知道有没有退化）：

```text
scripts/train_partial_lora.py      scripts/precompute_activations.py
scripts/plan_layers.py             scripts/probe_layers.py
scripts/pick_checkpoint.py         scripts/merge_forge.py
scripts/make_subsets.py            scripts/eval_re_extended.py
```

## 清单

| 脚本 | 曾经的错 | FAIL 说明什么 |
|---|---|---|
| `t1_plan_envelope.py` | plan 只认扁平 `{cat:{layer:score}}`，probe 写信封 → span 全 None → 静默走兜底 | 又只认一种形状了，或 probe 改了信封字段 |
| `t2_mix_foreign_pt.py` | 异源 `.pt` 混进 act-cache → hidden 配错 labels | manifest 守卫被绕过 |
| `t3_mask_batch_encoding.py` | `len(BatchEncoding)` 当 token 数 + 前缀法 → labels 全 -100 → 单 token | 掩码退回前缀法，或标签不再与正文对齐 |
| `t4_win_drive.py` | 裸 Windows 路径丢盘符 → 落到当前盘 | name/path 又被 `split(":",1)` 拆了 |
| `t5_dup_source.py` | 同名源 `of()/summary()` 只认第一个 | 重名检查被删，或索引键改成 root |
| `t6_eval_pairing.py` | train/val 按源名配对 → §14.8 与遗忘监控永远 N/A | 配对键又漂回源名 |
| `t7_pick_val_path.py` | `--val-data` 只吃单文件 + 打错路径静默空集 | `--val-data` 退回单文件/静默 |
| `t8_merge_eval_isolation.py` | 隔离基线缺失 → ABORT 永不触发；清单写死 OUTDIR | 缺失又被当空处理，或清单路径回到常量 |
| `t9_pick_eval_paths.py` | `--re-eval/--kitty-eval` 打错 → 主判据静默变 0 题 | 三套评测集没有统一的加载器 |
| `t10_make_re_eval_isolation.py` | `--val/--train` 打错 → 「eval 污染 train」检查空转，报告打「重叠 0 ✓」 | 隔离检查又退回 `if exists else []`，或泄漏只报不失败 |
| `t11_plan_cats.py` | 未知类别静默落 rest + 缺类别归因成「峰不分离」 | 未知类别又走 `.get(cat,"rest")`，或缺类不再 warn |

## 写新的一条

1. 命名 `t<编号>_<简述>.py`，编号只增不改。
2. 文件头三段：**缺陷现象 / 后果 / 正确的断言**，外加「如果这条 FAIL 说明什么」。
3. 自带最小输入（`tempfile` 造，不依赖仓库里的真实数据），CPU、秒级。
4. 退出码 0/1；最后一行打 `PASS: …` 或 `FAIL: [...]`。
5. 如果缺陷是"旧实现会退化"，把旧实现**内联写进测试**（见 `t3`），这样断言本身就证明了
   这条回归不是空跑。
