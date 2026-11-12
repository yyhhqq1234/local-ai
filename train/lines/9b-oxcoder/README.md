# 9B 线（OxCoder-9B）· 真实目录

> 2026-11-01 物理迁移完成：本目录里的东西都是真文件（非 junction）。
> 原 `train/{models,out,data,...}` 已整体搬入这里，旧路径不再存在。

## 目录

```text
train/lines/9b-oxcoder/
├─ models/            Qwen3.5-9B 基座 + 各轮 LoRA adapter
├─ out/               训练产物：z-*（方案 Z）/ 2b-*（NSFW 门控）/ eval-*.json
├─ data/
│   ├─ kitty-reverse/   kitty 工具编排语料（train-kitty-v3-clean 等）
│   ├─ agent-traj/      2A 轨迹语料（traj-all-capped / lite / evalshape）
│   ├─ nsfw-gated/      2B 成对门控集（train-2b-gated.jsonl）
│   ├─ nsfw-gated-v1/   2B 旧版（neg:ctl=12:1，已判失败，留作对照）
│   ├─ eval/            固定评测集：val 85 / test 129
│   └─ _chunk-audit/    切片审计
├─ eval/               评测快照
├─ logs/ · tools/
└─ README.md
```

## 归属

| 项 | 内容 |
|---|---|
| 模型 | Qwen3.5-9B（`models/OxCoder-9B`） |
| 计划 | 根目录 `PLAN-OXCODER-POSTTRAIN.md` |
| 训练脚本 | `train/lines/_shared/scripts/train_qlora9b.py` |
| 评测脚本 | `_shared/scripts/{eval_2a_code,eval_multi_adapter,nsfw_gate_local,check_*}.py` |
| 硬件 | 本机单卡 12 GB |

## 硬规则

1. 只在本目录内写文件（日志 / ckpt / 临时产物）；不写 `train/lines/27b-kittyrev/**`。
2. 产物命名前缀：`z-*`、`2b-*`、`eval-*`，一律落 `out/`。
3. 训练必须带 `--seed`（默认 42）；无种子结果不可用于对比（实测同配置 cov 差 15 pt）。
4. 评测只用 `data/eval/`；禁止跨线借用 27B 的数据或产物。
5. 与 27B 语料同源（kitty 重合 98%），但文件各自独立：不跨线引用、不互相覆盖。

## 当前产物

| 用途 | 路径 | 成绩 |
|---|---|---|
| 逆向 / 带工具意图 | `out/z-re-v4/final` | hit 30/40 · 75.0% · 编造 0 |
| 纯编程问答 | `out/z-2a-v7/final` | 首版 cov 0.6462；重训版 0.4958（待 seed 42 重跑） |
| NSFW 门控 | `out/2b-nsfw-v2/final` | v1: leak 0 / FPR 1.0 FAIL；v2 训练中（迁移后从 ckpt-2700 续） |
