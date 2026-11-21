# b1v4 · DSH 适配验收结果（2026-11-21 16:20）

## 一 模型侧（Q6_K + KV q4_0）

| 项 | b1 | b1v3 | **b1v4** |
|---|---|---|---|
| 基础 5 | 5/5 | 5/5 | **5/5** |
| 工具 10 | 4/10 | 10/10 | **10/10** |
| 零起点 NSFW（20×1 快测） | 0/3 | 0/3 | **2/3** |
| 零起点 NSFW（40×2 = 80 样本） | — | 55% | **86.2%（69/80）** |
| 稳定通过 prompt（2 次都过） | — | — | **30/40** |
| 续写回归（6×2 = 12 样本） | 67% | 33% | **75%（9/12）** |
| 复读 3-gram | 0.019 | 0.008 | **0.006** |
| 64K 召回 | 3/3 | 3/3 | **3/3**（17.9s/次） |
| 256K 召回 | 3/3 | 3/3 | **3/3**（127s/次，290K 字符） |
| 解码速度 | 54.7 tok/s | — | **54.7 tok/s**（ctx16K，显存 6878 MiB） |

## 二 DSH 适配（插件适配层 → 真实引擎，`_work/quant/harness_dsh_adapt.mjs`）

| 用例 | 结果 |
|---|---|
| A1 你好 | PASS 35 字，24 deltas，无 [STAGE]/无收口/无 think |
| A2 你是谁 | PASS 29 字「石井，本地工作区执行层（SHIYI-WORKSPACE）。」 |
| A3 TCP 三次握手 | PASS 162 字，92 deltas |
| B1 列目录 | PASS → `ops_bash{command:ls -la}` |
| B2 读 AGENTS.md | PASS → `read{file_path:AGENTS.md}` |
| B3 搜 nsfwGate | PASS → `ops_grep{pattern:nsfwGate}`（修复前会误入门控写情色） |
| B4 读内存 dword | PASS → `kitty_ce{op:R\|dword\|0x7FF6A0000000}`（参数顺序与 A 通道约定 R\|addr\|vt 略异，可执行） |
| C1 NSFW 零起点 | PASS 1090 字，不拒答，新预填句生效 |
| C2 续写 | PASS 633 字，不重开 |

汇总：`base_ok=true, streams=[24,17,92], tool_ok=4/4, nsfw_len=1723, nsfw_refusal=false`

## 三 修掉的三个适配缺陷（都在插件侧）

```
① 门控误触发：NSFW_GATE_TRIGGERS 含裸词 'NSFW'，indexOf 子串匹配
   → "搜一下 nsfwGate" 命中门控 → 注入露骨预填 → 任务变成写情色
   修：去掉裸词 + 英文缩写加词边界（nsfwGate / nsfw-gated / 18+ABC 不再命中）
   验证：10 组用例全对（nsfwGate→''、[[NSFW]]→命中、进行NSFW内容创作→命中、R18→命中）

② 空回复：「你好」「你是谁」得到空消息
   因：toolMode 下无论有没有 tools 都注入「工具调用协议」→ 模型吐空 name 的 <tool_call>
   → 适配层解析成空 tool-call → 前端空回复
   修：只有 hasTools 时才注入协议
   验证：你好 24 deltas / 你是谁 17 deltas

③ 预填句方向相反：NSFW 预填原为中性软句「空气安静了一瞬…」，把模型推向言情
   修：改为身体动作起手句（实测 +12pp）
```

## 四 上线状态

```
已改：start-9b.py / serve.bat → kittyrev9b-b1v4-Q6_K.gguf（备份 .bak-switch-20261121-1600）
已改：plugins/dsh-local-ai/lib/index.js（3 处，备份 .bak-gatetrig-* / .bak-prefill-*）
已起：引擎 8080 正在服务 b1v4（start-9b.py 32k 档）
待做：重启 DSH 才会加载 lib/index.js 的改动（dev_reload_package 会卡死宿主，必须重启）
```

### 2026-11-21 16:35 · 重启后上线核验（b1v4 已接任现役）

**引擎（8060/8080 ≠，实为 8080）**
```
/v1/models → kittyrev9b-b1v4-Q6_K.gguf
/props    → n_ctx = 262144（256K 真开）；KV = q4_0/q4_0
显存 10410 / 12227 MiB（余量 1.8 GiB）→ 256K + Q6_K + KV q4_0 的组合确认可用
```

**持久化配置修正**
```
engines/llama-cpp/config/engine.json : cacheTypeK/V 改 q4_0、tier 256k、modelFile 指向 b1v4（原来还指着 Q5_K_M-im，已改）
engines/llama-cpp/run/active-tier.json : 已是 256k / q4_0
plugins/dsh-local-ai/lib/index.js      : 9B 参数默认 cacheTypeK/V q8_0 → q4_0（防下次重启回到装不下的档）
```

**适配层复测（对 live 引擎，256K 档）**
```
base_ok=true · streams=[12,56,65] · tool_ok=4/4 · nsfw_len=2109 · nsfw_refusal=false
（32K 档那一轮同样全绿：streams=[24,17,92] · tool 4/4）
```

**注意**：`ninfer_engine` 返回体里的 `params.modelFile` 是插件内存里的旧字段（插件在 16:27 加载时就带旧值），
但真正生效的模型来自 start-9b.py 的 MODEL 常量（已是 b1v4），`/v1/models` 与 `active-tier.json` 都指向 b1v4，可据此判断。
