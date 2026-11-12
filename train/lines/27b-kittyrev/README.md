# 27B 线（KittyRev-27B GEN3）· 真实目录

> 2026-11-01 物理迁移完成：本目录里都是真文件（非 junction）。
> 原 `train/{base,local-pack,data/versions,kitty-rev,quant,merged,heretic-pareto}` 已整体搬入。

## 目录

```text
train/lines/27b-kittyrev/
├─ base/              Qwen3.8-27B 基座（52 GB）
├─ local-pack/        量化成品：gen2 / gen2v2 / gen3 / gen3_1 / gen3_1p / gen3_1q / gen3_1r（≈121 GB）
├─ data/versions/     GEN2/GEN3 打包数据集 + .sha256 + 审计
├─ kitty-rev/         部署 / 契约 / 运行手册
├─ quant/ · merged/ · heretic-pareto/
└─ README.md
```

## 归属

| 项 | 内容 |
|---|---|
| 模型 | Qwen3.8-27B（IQ2 量化部署 + LoRA adapter） |
| 计划 | 根目录 `PLAN-KITTYREV-27B-GEN3.md` |
| 脚本 | `train/lines/_shared/scripts/{local_*,build_gen2*,build_gen3,convert_gguf_safe,gsq_rco_plan,attach_mtp}.py` |
| 产物 | `local-pack/gen*` |
| 硬件 | 云端 GPU（A800 / 5090）；本机只做构建 / 量化 / 验收 |

## 数据（GEN3 口径）

```text
必带   data/versions/gen2-nsfw-kitty-v2.20261029-124315.jsonl   46,281 条（GEN2 同源，保证可比）
增量   train/lines/9b-oxcoder/data/kitty-reverse/re-qc/silver.jsonl   8,815 条（QC 精选；跨线只读取）
产物   data/versions/gen3-nsfw-kitty.20261030-003024.jsonl       47,105 条
```

## 硬规则

1. 只在本目录内写文件；不写 `train/lines/9b-oxcoder/**`，也不在 9B 的 `out/` 下产出。
2. 产物一律落 `local-pack/gen*`（新 GEN 用新后缀，不覆盖旧包）。
3. 数据集落 `data/versions/`，必须带 `.sha256` 与审计报告。
4. 与 9B 语料同源（kitty 重合 98%），但打包文件各自独立；不引用 9B 的训练产物。
5. 本机 12 GB 显存跑不了 27B 训练；启动引擎会占约 10.3 GB，与 9B 训练冲突
   （9B 侧脚本已内置「显存>1500 MiB 等 15 min 后接管」）。

## 当前成品

| GEN | 产物 | 备注 |
|---|---|---|
| gen2v2 | `local-pack/gen2v2/*.ninfer`（9.9 GB） | 已部署验证 |
| gen3 | `local-pack/gen3/*` | bf16 gguf → IQ2_S |
| gen3_1p | `local-pack/gen3_1p`（51 GB） | 体积最大，占磁盘主要份额 |
