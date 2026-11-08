# ninfer 9B · 长 prompt NaN 排查 · round 40 交接

接续 `STATE-ROUND36.md`。本轮只补最后三格的定位结论，避免下一轮重复。

## 关键定位（本轮新得，读代码确认）

```text
src/models/qwen3_5/execution/text.cpp
  :1573   run_layers(x, Phase::Prefill, tap);      ← prefill 确实走 run_layers（没有第二套层循环）
  :1322   TextContext::run_layers(Tensor&, Phase, Tap&)  定义
  结构    try { if (!graphs_) { mixer(); post_mixer(); …逐层 NaN dump… continue; }
                …（graph / record 分支，且该分支里没有 dump）… }
```

**因此**：prefill 时 `graphs_` 非空 → 走 graph/record 分支 → **逐层 dump 从未执行**。
decode 打印出 `verify T=1` 是因为它走 `!graphs_` 那一支。三次插桩（attn_mix / run_layers / attn_dump）
只看到 decode 的根因就是这个分支覆盖差异，与 CUDA graph 本身无关。

## 下一轮唯一动作（10 行内）

```text
把「逐层 NaN 统计」从 `if (!graphs_)` 分支移到 try{} 之后的分支汇合处，
对 eager 与 graph/record 两条路径都生效，然后跑 chars=470（≈272 token）：
  layer-norm.txt 应出现 `Lnn prefill T=272 …`
  首个 nan≠0 的层号 = 病灶层；再在该层内看 gdn vs attention（按 full/linear 层判断）
```

## 收尾待办（必须做）

```text
text.cpp  kAttnDiag 当前为 true  → 定位完成后改回 false 并重编
          逐层 dump 的 gate 当前为 T<=512（原本 false && T<=4）→ 同样改回
decode.cpp NINFER_DUMP_IDS 打印（默认关，保留或删除皆可）
```

## 已确认的失败阈值与已否证变量（汇总，勿重试）

```text
阈值: (260, 272] token    260 OK / 272 FAIL("token outside the public token domain") → 之后引擎 503
已否证: --no-cuda-graph · 无 tools 的长 prompt · shape.cpp 阈值扩到 <=512 ·
        --no-prefix-reuse · --prefill-chunk 64 · grammar 词表/掩码宽度错配 ·
        采样踩 padding 区 · decode 绑定掩码全 0
```

## 五目标现状

```text
① ⚠️ ≤260 token 15/15；≥272 失败（口径需补长 prompt）
② ⛔ --vision → missing component vision（产物限制，需重做转换）
③ ⚠️ 与①同一根因（DSH 请求天然 300+ token）
④ ✅ 冷启 7.05s / 客户端 TTFT 25ms / 服务端 105ms
⑤ ⬜ graph 36.0–36.2 tok/s（无 graph 15.3–15.6）；再上需 k4096 GEMV-pair kernel 或带 MTP 的产物
```
