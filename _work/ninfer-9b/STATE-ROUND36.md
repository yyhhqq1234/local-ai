# ninfer 9B · 长 prompt NaN 排查记录 round 33–36

## 核心事实（新增，覆盖此前“已达标”的口径）

```text
同一引擎、--greedy、max_tokens=4~6，只改 prompt 长度：
  chars=250 → prompt_n=150  OK
  chars=350 → prompt_n=205  OK
  chars=450 → prompt_n=260  OK
  chars=470 → prompt_n≈272  FAIL  "target returned a token outside the public token domain"
  更大的长度一律 FAIL，且失败后引擎转 503（service unavailable）
⇒ 失败阈值在 (260, 272] token 之间
⇒ 验收①“15/15 内容正确”只在 ≤260 token 的短 prompt 上成立
```

## 已被否证的触发因素（都做过对照，别再试）

| 变量 | 对照方式 | 结果 |
|---|---|---|
| CUDA graph | `--no-cuda-graph` | 同样 FAIL |
| tools / grammar | 无 tools 的长 prompt | 同样 FAIL（tools 只是“刚好 358 token”，落在阈值另一侧） |
| attention 投影 shape 分支 | 把 `n5120_n5120_k4096` 的 `<=15` 阈值扩到 `<=512` 全走 4 段独立路径 | 仍 FAIL（已回滚） |
| 前缀复用 | `--no-prefix-reuse` | 仍 FAIL |
| prefill 分块 | `--prefill-chunk 64` | 仍 FAIL |

## 仍成立但未解释的关联

```text
prompt 260 成功那条日志里有：cache 53 (20.4%, checkpoint) —— 前缀检查点在跑
272 = 16×17；260 = 16×16+4。两者在 Bf16KvPartition::live 下都是 5 splits，不构成分区差异
```

## 下一轮建议（按信息量排序）

```text
1. 把 attn_dump 的保护阈值从 count<=64*1024 提到 2M，并且只统计 nan 计数（不落 bits），
   开 kAttnDiag（text.cpp 里已置 true）跑 ~272 token 请求，看 proj/norm/rope/attn_out 哪个先 NaN。
   注意：现在 attn_dump 会因超限直接 return 而仍然消耗 attn_dump_n 配额，导致 prefill 调用空转。
2. 若 attn 段全部有限 → 转向 GDN 状态（recurrent/conv state 在长 prefill 上的槽位复用）
   与 lm_head/final norm（logits 直接越界的那一段）。
3. 修好判据：短 prompt（≈200 token）+ 长 prompt（≥600 token）各 3 轮全绿，才算①真达标。

## 本轮改动状态

```text
shape.cpp      ：阈值回滚到 <=15（保留 7e81e48 原修复），注释写明 <=512 已试过无效
text.cpp       ：kAttnDiag 置 true（临时，定位完必须改回 false）
decode.cpp     ：NINFER_DUMP_IDS=1 打印采样 id（诊断，默认关闭）
grammar*.cpp   ：accept 失败与全 0/单候选掩码降级（防御性，均已实测不改变短 prompt 行为）
```
