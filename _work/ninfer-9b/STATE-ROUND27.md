# ninfer 9B · ③（tools/DSH）排查记录 round 23–27

接续 `STATE-20261108.md`。这一节只记 ③ 的证据与结论，避免下一轮重复试错。

## 现象演进（同一条 tools 请求，逐步修复）

| 阶段 | 表现 | 触发点 |
|---|---|---|
| 原始 | 进程全灭 `0xC0000409` + `cudaErrorLaunchFailure` | `sample/kernel.cuh:56,206` 的 `asm volatile("trap;")` |
| 去掉 trap 后 | HTTP 500 `selected token violates the request grammar` | `text/grammar.cpp:368` 的 `AcceptToken` 失败抛异常 |
| 降级不抛后 | HTTP 200，`finish=length`，`content=""`，`reasoning_content` 全是 U+FFFD | 采样拿到的 id 解码不出字符 |

## 已证伪的假设（别再试）

1. **掩码宽度不足**：`startup.cpp:227` 用 `ceil(public_tokens/32)`；实测 `mask_upload_bytes/mask_positions/4 = 7753` words → `public_tokens = 248,096`。
   logits 宽度 248,320 是 LM head 的 970×256 对齐 padding，不是词表。两者自洽。
2. **采样踩到 padding 区**：`distribution.cuh:72-77` 的 `sampling_candidate_cap` 会把上界钳到调用方传入的 `vocab`，而 decode 传的是 `public_token_count`（`decode.cpp:77`），不会遍历到 248,320。
3. **decode 绑定行全 0**：在 `bind_grammar_mask` 加了全 0 检查 + 降级 + `[grammar]` 日志；实测这条日志**一次都没打印**，说明该行非空。
4. **文本落点问题（思考段不回落正文）**：`--no-thinking` 时 24/32 个 token 直接消失（content 空、reasoning_len=0），`--preserve-thinking` 时全在 reasoning 且是 U+FFFD；而**无 tools 的 plain 请求完全正常出中文**。所以不是落点，是生成内容本身坏了。

## 当前唯一自洽的解释（待验证）

tools 请求的 prompt 为 358 token（含 tool 定义），生成被语法约束为 tool-call 形态；实际产出的 id 序列在 detokenizer 里解不出合法 UTF-8（U+FFFD），说明**采到的 id 与模型真实词表语义不一致**——可能是 grammar 的 token→id 映射（xgrammar 侧词表）与本模型 248,096 词表不是同一份。

## 下一轮的最小验证（三步，都不需要大改）

```text
1. 在 bind_grammar_mask / fill_grammar_mask 里把「被允许的第一个非零位对应的 token id」打出来，
   与 plain 情况下采样得到的 id（例如 "你好" 的首 token id）对比量级是否合理；
2. 打印 grammar provider 构造时的 vocab_size（src/text/grammar.cpp 的 prepare/构造处），
   确认等于 248,096；
3. 若 vocab_size 不同（例如按 248,320 或默认 151936），即可定位为 xgrammar 词表接错，
   修好即可让 tools 请求产出正常文本，随后 accept_final 3 轮 15/15 → 接 DSH。
```

## 本轮改动（未提交，待验证后一起提交）

```text
src/text/grammar.cpp:368                accept 失败不再 throw，改为放弃约束继续生成
src/models/qwen3_5/program/grammar_masks.cpp
  fill_grammar_mask: 全 0 → 返回空 mask（降级无约束）
  bind_grammar_mask: 新增全 0 检查 + [grammar] 日志（实测未触发）
```

当前五目标：① ✅（15/15 + 失败不挂死）· ② ⛔ 产物缺 vision · ③ ⚠️ 200 但内容为 U+FFFD · ④ ✅（冷启 7.05s / TTFT 25ms）· ⑤ ⬜ 36 tok/s（graph 已 2.3×）
