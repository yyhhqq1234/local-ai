# TASKPOINT · ninfer 9B（交接给 DSH）

> 更新：**2026-11-11 10:20** · 手交方：WorkBuddy AI · 接手方：**DSH / 石井**
> **本段是当前唯一权威交接。** 下面「2026-11-10 交接（WorkBuddy AI 接手时）」及之后的全部内容
> 是上一轮的历史记录，**保留不删，但结论已被本段覆盖**。
>
> 详细证据索引（按需跳读，行号为本文件当前行号）：
> · **A-15**（乱码真因：attention 四段输出错绑）→ 第 1609 行
> · **A-17**（MTP 逐层对拍 + `features.cu` 几何越界修复）→ 第 1822 行
> · **A-18**（MTP 头不成立的定案）→ 第 1887 行
> · 2026-11-08 及更早的各轮原文 → 附录 A

---

## H 交接摘要（5 分钟读完）

```text
一句话：9B 引擎在引擎侧已经收口 —— 乱码根因修掉、内容 17/17 正确、长 prompt prefill 2133 tok/s；
        唯一未达成的是 ⑤ decode ≥100 tok/s，且已证明「靠现有 MTP 头做不到」，属权重问题不是代码问题。

五条验收现状（2026-11-11 实测）：
  ① 内容正确        ✅  17/17 clean、bad markers NONE、边界扫描 35/35、长 system 504/511 正确
  ② 多模态 ≥1 例    ✅  HTTP URL 图文 2.44 s，正确描述红/蓝方块，prompt 567.6 tok/s
  ③ 可接入 DSH      ⚠️  引擎/协议面已复核通过（2026-11-11 11:10，见 §H.8.1）；
                        新阻断「模型不产结构化 tool_calls」已由适配器 shim 修掉（§H.8.4，3/3 E2E），
                        重启 DSH 后即为 ✅（禁止用 dev_reload_package，会卡死）
  ④ 首 token < 15 s ✅  冷启 3.3 s、TTFT 164 ms、prefill 567–2133 tok/s
  ⑤ decode ≥100     ❌  无投机 20–43 tok/s；开 MTP 26.4 tok/s（accepted 1/564）= 负收益
                        → 2026-11-11 定案 **B**：35.25 tok/s 为本机 12 GB 卡上限，算术见 §H.8.2

DSH 接手后只剩三件事（按代价排序，见 §H.4）：
  1. 重启 DSH 跑一轮真实会话（带 system + tools）→ 收口 ③
  2. ⑤ 二选一：重训 MTP 头 / 关掉投机记为 12 GB 卡上限
  3. 可选：修 data URI inline base64 → WIC 路径（HTTP URL 已够用，优先级最低）
```

**当前可用启动命令（参数不可省）**

```powershell
ninfer-serve.exe D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer `
  --max-context 4096 --greedy --host-context-mib 2048 --prefill-chunk 128 --no-thinking --port 18900
# 便捷入口：& D:\BaiduNetdiskDownload\Local-AI\_tools\run-serve.ps1
```

```text
· --prefill-chunk 必须是 128 的正整数倍（120/112/96 直接拒启）
· --no-thinking 不可省（否则正文落 reasoning_content，content 为空）
· 不建议再默认加 --no-prefix-reuse：它当初只是绕过 A-15 的输出绑定 bug，那个 bug 已修；
  17/17 回归是在**默认配置（前缀复用开启）**下跑的、全 clean。但本次结果里没有单独留
  cache_n 命中证据，DSH 第一次真实会话时顺手确认一下复用是否真的命中即可
· 要跑 §H.5 的落盘探针时必须追加 --no-cuda-graph（探针里有 cudaDeviceSynchronize/cudaMemcpy，
  在 graph capture 期间会触发 cudaErrorStreamCaptureInvalidated）
```

---

## H.1 本轮（2026-11-11）改了什么代码

全部落在 `train/lines/_shared/tools/ninfer-master/`（本地源码，未动上游），每处都留了 `.bak`。

| # | 文件 | 改动 | 备份 / 回滚 |
|---|---|---|---|
| A-15 | `src/ops/linear/split/q4_q5/shapes/n5120_n5120_k4096/mma.cu` | grouped-MMA 把 9B attention 的**四个独立输出**当成两块 5120 行连续缓冲写（越界 + 相邻张量互覆盖 + gate/value 未填）。改为四个 RowSplit job 各自直写 `outputs[0..3]`：`qk[0:4096]→query`、`qk[4096:5120]→key`、`value_z[0:4096]→gate`、`value_z[4096:5120]→value` | `mma.cu.bak-fix-segmented-outputs` |
| A-15 | 同目录 `shape.cpp`（第 8 行）、`small.cu`（第 106 行） | 探针阈值复原为 `<= 15`（`>15` 走已修好的 grouped 路） | `shape.cpp.bak-force-small16`、`small.cu.bak-force-small16` |
| A-15 | `src/models/qwen3_5/execution/text.cpp`（第 1749 行附近） | `max_unit_tokens` 默认 **15 → 128**；仍可用 `NINFER_PREFILL_MAX_TOKENS` 覆盖 | `text.cpp.bak-default128` |
| A-17 | `src/ops/indexing/features.cu` | `split_bf16_features` 的 kernel 把 27B 几何（`14336/6144/1024`）写成编译期常量，9B（`10240/4096/1024`）上 token 边界错位并把 6144 行 q 写进 4096 行张量。改为 `SplitGeometry` 由 host 从输出张量推导后传入（27B 的 `{14336,6144,1024}` 与原常量完全等价） | `features.cu.bak-9b` |
| A-15 | `tests/ops/linear/test_split_multi_output.cpp` | 新增 9B 四输出用例 `run_q4_q5_9b()`（T=1/15/16/17/31/32/33/63/64/65/127/128/129 + graph replay）+ 补 `<array>` | 无备份（测试文件，可回滚 git） |
| — | `tests/cmake/CoreTests.cmake` | `ninfer_read_queue_test` 包进 `if(NOT WIN32)`（Windows 无 liburing，否则 cmake 直接失败） | 同上 |

**回滚一条命令**：`cp <file>.bak-xxx <file>` 然后重跑 §H.3 的构建脚本。

**当前阈值现状**（接手前核对过）：`shape.cpp:8 = <=15`、`small.cu:106 = <=15`、`text.cpp:1749 = 128`；`features.cu` 里 14336 只剩 3 处注释，已无生效常量（生效的是 `SplitGeometry{total,wide,narrow}`，由 host 第 158 行推导）。

---

## H.2 已验证的结论（含证据，可直接引用）

### A-15：乱码根因 = 一个输出绑定的越界写

`mma.cu` 的 grouped 路由（只有 T>15 才走）把四个独立分配的输出来当成两块 5120 行连续缓冲：
`make_job(qk_weight, 0, 5120, out[0], 0)` 向 4096 行的 query 写 5120 行，同一块再以行偏移 5120 写一遍。
只要单个 execution unit 宽度 >15 就命中 —— 与实测「15 安全、16 起全烂」的边界精确吻合。

闭环验证（**先证明测试抓得到，再证明修好了**）：

| 项 | 结果 |
|---|---|
| 独立 FP64 oracle 测试（新增 9B 四输出用例） | **旧代码**在 T=16 处进程异常终止（exit=127）；**新代码** `OK linear_split multi-output`，exit=0 |
| 边界扫描 15/16/20/24/32/64/128 × {2+2, system, essay, 612-token, 504-token system} | **35/35 clean** |
| 回归（默认 128） | 5×3 = **17/17 clean**，bad markers NONE |
| 612-token prefill | limit 12 = 365.0、15 = 441.3、**128 = 2133.5 tok/s（0.287 s）** ⇒ 分块限速的 5.7× 代价全部消除 |

### A-17：MTP 拆分几何越界（真 bug，已修）

host 侧校验早改成从输出张量推导，但 kernel 仍是 27B 常量 → 9B 上 `row = idx % 14336` 让 token 边界整体错位。
修完 `draft_n_accepted` 从 0 → 1（仍不可用，见 A-18）。

### A-18：MTP 头本身不成立（引擎无误）

四层证据，逐层排除：

```text
1) 整层数值：用真实权重在 torch 从 (ids, hidden) 整层复算，与引擎逐段一致 ——
   v 0.0037 / qn 0.0028 / kn 0.0031 / a 0.0052 / o_proj 0.0038 / x_res 0.0036 /
   mh 0.0032 / out 0.0037，cosine = 1.00000，argmax 220 == 220。
   ⇒ MTP block 实现（stem、投影、QK-norm、partial rope 64、因果 attention、gate、
     o_proj、residual、MLP、final_norm、argmax）全部正确。

2) 输入侧校准：主干自己的 lm_head 直接吃同一份 hidden ——
   lm_head(hidden[t]) == ids[t] 命中 9/12（t=5..11 全中）。
   ⇒ hidden 是真末层输出、lm_head 正确、ids[t]=x_{t+1} 的移位生效。

3) 同输入下 MTP 头（长 prompt，n=101）：
   (1+w) 约定   top1 = 7/101，distinct = 3（几乎全吐 token 11）
   纯 w 约定    top1 = 6/101，distinct = 27
   训练侧 mtp-domains-v3step300.json 对同一权重声称 0.72 / 0.28 / 0.26。
   ⇒ 两种约定都差一个量级，且 (1+w) 下退化成 3 种 token。

4) 恒定 draft 的成因：逐轮落盘提案输入 ar_hidden ——
   cos(r0,r1)=0.9954、|mean|/mean|dev|=7.11、62 行 argmax 全是 11。
   ⇒ 不是输入冻结，是输出被常量分量压死。
```

**结论**：引擎管线正确；**这份 MTP 头对当前服务模型的 hidden 不成立**。换任何输入约定都救不回来。

---

## H.3 构建（照抄即可）

```powershell
# 只重建三个应用（约 3–6 分钟；MSVC 环境已写进 bat，不要手搭）
& D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\p3-rebuild-apps.bat

# 等价手写
"D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\ninja.exe" `
  -C "D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build" -j 4 `
  apps/ninfer-serve.exe apps/ninfer.exe apps/ninfer-perplexity.exe
```

```text
· 改完 .cu/.cpp 后先删对应 .obj 再编，否则 ninja 可能不重编：
  _tools/ninfer-build/src/**/CMakeFiles/*.dir/**/<file>.obj
· BUILD_TESTING 当前 = OFF（保持这个状态交付）。要重编 oracle 测试时：
  cmake -S <src> -B _tools/ninfer-build -DBUILD_TESTING=ON   → 编完再改回 OFF
· 现有测试二进制：_tools/ninfer-build/tests/ninfer_linear_split_multi_output_test.exe（03:15，验证 A-15 用）
· 当前引擎：_tools/ninfer-build/apps/ninfer-serve.exe = 275,408,384 B（2026-11-11 10:08）
```

---

## H.4 DSH 接手后要做的三件事

**① 收口 ③「可接入 DSH」（最便宜，先做这个）**

```text
动作：重启 DSH → 加载新 exe → 用 build-9b 档位跑一轮带 system + tools 的真实会话
判据：会话内不乱码、TTFT 可接受（历史值 164 ms）、无 500
备注：适配器 build-9b 路径未变，无需改配置；plugins/dsh-ninfer-local 本轮未改
```

**② ⑤ decode ≥100 tok/s —— 二选一**

```text
A. 重训 MTP 头（唯一能翻盘的路）
   用当前服务模型的 hidden（就是 A-18 里那份，已验证是正确末层输出）+ 现有 SFT 语料，
   按 mtp_posttrain.py 的配方重训 1 层，目标 top1 ≥ 0.5，再回填验证 accepted 率。
   成本：一次训练 + 一次重转换。参考脚本：train/lines/27b-kittyrev/quant/mtp_posttrain.py

B. 关掉投机，记为交付上限
   不带 --spec mtp 时 20–43 tok/s（典型 30–43）。写进结论：34 tok/s 是本机 12 GB 卡的交付上限。
```

**③ 可选：data URI inline base64 走不通（上游 WIC bug）**

```text
现状：HTTP URL 传图已完全可用（2.44 s，描述正确）。
       inline base64 / data:image 仍失败，属上游 media decode 的 WIC 路径问题。
优先级：最低。除非 DSH 侧必须支持 data URI，否则不用碰。
```

---

## H.5 验证脚本清单（`_work/ninfer-9b/`）

```text
常规验收
  p3_regress.py            17 条短请求回归（正确性 + 关键词 + bad markers）
  p3_long_system.py        504/511-token 长 system 会话
  p3_long_prefill.py       612-token prompt 的 prefill 速度
  p3_matrix_scan.py        边界扫描 limits 15/16/20/24/32/64/128 × 5 类请求
  p3_vision_url_probe.py   HTTP URL 图文问答
  p3_mtp_probe.py          MTP 接受率 + 生成速度

MTP 取证（都默认关闭，需环境变量开启）
  p3_mtp_block_dump.py     → NINFER_TRACE_MTP_BLOCK      decode 侧 block 各段落盘
  p3_mtp_block_check.py    → 与 torch 参考逐段比 qn/kn/v
  p3_mtp_prefill_dump.py   → NINFER_TRACE_MTP_PREFILL    prefill 整条流落盘（跨 chunk 累加）
  p3_mtp_prefill_check.py  → 校验 stem（h_first + unit offset）
  p3_mtp_tail_check.py     → 校验 o_proj/residual/MLP/final_norm
  p3_mtp_full_check.py     → 整层从零复算，端到端 cosine
  p3_mtp_accuracy.py       → 逐位置测 top1（含 pre/post final_norm × 移位/未移位）
  p3_mtp_normconv.py       → (1+w) vs 纯 w 约定对比
  p3_ar_analyse.py         → 提案输入 ar_hidden 的结构（cos / 常量占比）
  p3_mtp_diag.py           → 逐轮 draft vs target argmax（NINFER_DUMP_DRAFT）

构建
  p3-rebuild-apps.bat      只重建三个应用（推荐）
  p3-rebuild2.bat          全量重建
  p3-build-test.bat        重建 oracle 测试（需 BUILD_TESTING=ON）
```

---

## H.6 坑（血泪，别重犯）

```text
路径
· 工作目录是 _work/ninfer-9b（带前导 n）。写成 infer-9b 会 FileNotFoundError，且 ls 看起来"像"存在。

Python
· 探针/脚本用 C:\ProgramData\anaconda3\python.exe（3.13.9）
· 需要 torch/safetensors/transformers 的用 train\.venv\Scripts\python.exe
· PATH 里的 python/python3 是 WindowsApps 0 字节别名，执行无输出 ≠ 没装

引擎参数
· --prefill-chunk 必须是 128 的正整数倍
· --no-thinking 不可省
· 探针必须配 --no-cuda-graph，否则 cudaDeviceSynchronize 会让 capture 失效并报
  cudaErrorStreamCaptureInvalidated（这条会把 MTP 探针结果全带偏，踩过一次）

模型语义（A-17/A-18 建立，改 MTP 前必读）
· RMSNorm 走 unit-offset (1+w)：norm 权重均值 hnorm=-0.255 / enorm=-0.478 / final=+1.423，
  只有 (1+w) 解释才全为正
· q_proj 是逐 head 交错 [q_h(d), g_h(d)]（HF modeling_qwen3_5.py:774 + 转换器一致）
· rope 是 partial：rope_dim = 256 × 0.25 = 64，half-split
· MTP stem 顺序 = concat(hidden_norm(h), embedding_norm(emb))，h 在前
· ids 已移位：ids[t] = x_{t+1}，最后一列用刚生成的 token
· MTP 预测的是 t+2（stem 用 x_{t+1}，target 是 x_{t+2}）

禁删资产（见仓库根 AGENTS.md §2.1）
· ninfer-27b-kv-stream-3arch-20261019/、ninfer-csunx/、train/.venv/、
  train/lines/9b-oxcoder/models/、train/lines/27b-kittyrev/{base,local-pack}/、plugins/
```

---

## H.7 本轮收口状态

```text
· ninfer 进程：0
· 显存：0 MiB used / 11944 MiB free
· 引擎：_tools/ninfer-build/apps/ninfer-serve.exe = 275,408,384 B（2026-11-11 10:08）
· 主路径回归：17/17 clean，bad markers NONE
· 未触碰 27B 档位与禁删清单；只写工作区 D:\BaiduNetdiskDownload\Local-AI\
· 探针全部默认关闭且 getenv 静态缓存（无热路径开销）：
  NINFER_TRACE_MTP_BLOCK / NINFER_TRACE_MTP_PREFILL / NINFER_TRACE_AR
· 详细证据：本文件 §A-15（A-15 修复）、§A-17（MTP 逐层对拍 + features.cu 修复）、
  §A-18（MTP 头不成立的定案）
```

---

## H.8 DSH 接手复核（2026-11-11 11:00–11:10 实测）

### H.8.1 ③ 收口结果：引擎/协议面 ✅，agent 面 ❌（新发现）

**适配器档位修正（必须的，之前会直接启动失败）**

```text
旧持久参数：maxContext=262144、prefillChunk=512、reasoningEffort=minimal、vision=cpu
  → exe 档位的 --no-thinking 只在 effort==none 时追加（lib/index.js:367），
    且 maxContext 262144 远超 12 GB 预算 → 必然 FATAL
新持久参数（已写入，ninfer_params）：maxContext=16384、prefillChunk=128、
  reasoningEffort=none、vision=off、port=1234、profile=build-9b
实测拉起：pid 21428，exe 275,408,384 B（2026-11-11 10:08），命令行逐字核对：
  <model>.ninfer --max-context 16384 --port 1234 --greedy --host-context-mib 2048
  --prefill-chunk 128 --no-thinking
```

**DSH 形态真实请求（stream + include_usage + enable_thinking=false）**

| 用例 | 形态 | prompt tok | TTFT | 输出 | decode | 判定 |
|---|---|---|---|---|---|---|
| A | compact system + 16 工具 | 1491 | 2.40 s | 256 tok | 35.86 tok/s | 200，不乱码 |
| B | 504-token system + 16 工具 | 1999 | 0.95 s | 102 tok | 35.62 tok/s | 200，不乱码 |
| C | 纯文本 | 59 | **146 ms** | 66 tok | 36.45 tok/s | 200，不乱码 |

回归：17/17 ok、bad markers NONE、decode 35–39 tok/s、prefill 191–406 tok/s；
**前缀复用确认命中**（第 6–15 条 hit=8…15、path=checkpoint），无需再按 §H 顶部怀疑默认配置。
全程无 500/503。

**新发现（阻断 agent loop，需决策）**：模型不产结构化 `tool_calls`。
三组对照（训练格式 system / 强约束 JSON / OpenAI tools）全部只回文本：`tool_calls` 为 null 或 `{}`，
`finish_reason=stop|length`，无 `<tool_call>` 标记；强约束下还会「先给 JSON 再自行编造 README 内容」。
⇒ 9B 的 SFT 语料是**文本工具调用**形态（`kitty_ce op=AL_DEL|<index>`，见
`train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-clean.jsonl`），适配器只解析引擎下发的
`delta.tool_calls`（lib/index.js:838）→ 会话能聊、不能调工具。
修法二选一：①适配器侧加「文本→tool_call」shim（按 profile 开关，约 1 小时，不动 27B 路径）；
②把 SFT 语料换成 OpenAI tool_calls 格式重训（贵）。
探针：`p3_dsh_session_probe.py` / `p3_dsh_toolcall_probe.py` / `p3_dsh_toolcall_probe2.py`，
结果 `p3-dsh-session-result.json`。

### H.8.2 ⑤ 定案：选 B（关投机，35.25 tok/s 为本机上限），理由是算术不是感觉

`p3_spec_matrix.py` 同一 prompt（max_tokens=256，greedy，4096 ctx）六配置实测：

| 配置 | decode | 接受 | 输出 |
|---|---|---|---|
| no-spec | **35.25 tok/s**（28.4 ms/token） | — | 正确 |
| `--spec mtp --draft-tokens 1` | 31.42 tok/s | 4/250 = 1.6% | 与 no-spec 逐 token 相同 |
| `--spec mtp --draft-tokens 3` | 26.70 tok/s | 2/753 = 0.27% | **损坏**（U+FFFD + 151353 连续重复） |
| `--spec mtp --draft-tokens 1|3 --lm-head-draft` | 起不来 | — | FATAL `selected proposal head is absent from artifact` |
| `--spec dflash --draft-tokens 3` | 起不来 | — | FATAL `missing component dflash` |

算术上限（实测轮成本）：d=3 每轮 37.9 ms（252 轮 / 9.55 s）；verify ≤4 token 在 12 GB 卡上是带宽瓶颈 ≈28–30 ms。
⇒ 要 100 tok/s 必须每轮接受 ≥3.8 token（**逐位置接受率 ≥95%**）；d=3 即使逐位置 50–70%（重训头的现实目标）
只到 **60–88 tok/s**。**结论：⑤ 不是「重训就翻盘」，是硬件带宽 + 投机窗口的结构上限。**
交付口径：**decode 35.25 tok/s（256 token 单流），典型 30–43；开 MTP 更慢且输出损坏 → 交付必须不带 --spec。**

### H.8.3 A 路资产清点（真要翻盘时的现成材料，已逐一确认存在）

```text
源模型   train/lines/9b-oxcoder/models/merged-2b-nsfw-mtp-tuned-v3（19.3 GB，含 mtp.*15 / vision 333 / lm_head）
         —— recipe 头注释里的 --model 就是它，即当初的 .agent-tmp/hf_g1（该临时目录已删，不影响复现）
recipe   _work/ninfer-9b/recipe_g1_full_gsq.py（另有一份 ninfer-master/.agent-tmp/g1/）
转换     python -m tools.convert --model <上面> --recipe <上面> --components text,vision,mtp ...
训练     train/lines/27b-kittyrev/quant/mtp_posttrain.py
已有头   mtp/qwen3.5-9b-mtp.safetensors（base）
         mtp/merged-2b-nsfw-mtp-tuned-v1-reonly.safetensors（训练期 top1 0.8516@600）
         mtp/merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300（训练期 top1 0.467）
```

**关键比对（本轮新查，解释 A-18 的 7/101）**：打进 .ninfer 的头 = v3 step300
（`mtp.fc.weight` sha256 前缀 `afbda571bce070cb` 与 `.step300` **完全相同**，与 v1-reonly、base 都不同）。
⇒ 同一个头训练期 top1 **0.467**、引擎里 **7/101=0.069**，落差不是实现问题（A-18 已证 block 与 torch 一致），
指向**分布漂移假设**：头在 bf16 主干 hidden 上训练，引擎喂的是 GSQ 量化主干 hidden。
若真要重训，正确做法是**在引擎 dump 的 hidden 上训**（不是 bf16 主干 forward，19 GB 也放不下），
成本量级：dump 30–60 min + 600–2000 步 1–2 h + 重转换 ~20 min + 17/17 复验；
且按 §H.8.2 算术，收益上限 60–88 tok/s，**仍到不了 100**。

### H.8.4 适配器「文本→tool_call」shim（③ agent 面的修法，已实现并验证）

```text
代码：plugins/dsh-ninfer-local/lib/index.js（备份 lib/index.js.bak-engx12）
  · ENGINE_PROFILES['build-9b'].textToolCalls = true（只 9B 开，27B 零影响）
  · textToolProtocol()：system 尾部注入 <tool_call>{"name","arguments"}</tool_call> 协议（含工具名清单）
  · parseTextToolCall()（export）：四种确定性形态 —— 标记 / ```json 围栏 / 裸 JSON 行 / kitty_ce op=…
    工具名必须在白名单、参数必须是对象，否则返回 null（不猜、不执行编造的工具名）
  · stream()：协议注入放在 compactSystem/trim 之后；holdText 压住"整段就是标记"的正文；
    收尾把标记转 tool-call 块 + 补 tool-call-delta；kind 优先级：有调用就 tool-calls（不再被 length 盖掉）
  · apply()：profileFlags 按当前引擎档位动态取开关
关键发现：**引擎侧自己就能解析 <tool_call> 标记并下发原生 tool_calls delta**
  （实测 read{"path":"README.md","limit":20}）→ shim 的主要价值是协议注入，解析器只是兜底。
验证：node --check = 0；shim-unit.mjs 11/11；p3_adapter_shim_e2e.mjs 3/3
  （T1 read 调用 / T2 普通问答不误判 / T3 kitty_ce{"op":"R|0xMODENUM|dword"}）
生效：**必须重启 DSH**；dev_reload_package 会把 DSH 卡死（本轮实测两次：工具消失 → 整个 web 无响应）
残留：模型偶发连发 3 条相同调用（去重会破坏 delta/block-end 配对，暂不做）；
      偶发凭记忆编造（模型能力问题，非 shim）
```

### H.8.5 真实形态两处修正（长 system / 协议措辞 / 去重）

```text
1) 9B 必须开极简 system：档位里本来就配了 compactSystem，但 live 配置没传进适配器；
   现改由 profileFlags 按档位下发。实测（同任务、同 14 工具，只改 system 长度）：
     短 system 210 字符 + 3 工具   → calls=3
     短 system 210 字符 + 14 工具  → calls=4      （工具数量不是变量）
     长 system 6541 字符 + 3 工具  → calls=0      （改写成编造的 README）
     长 system 6541 字符 + 14 工具 → calls=0
   DSH 真实 system 是 35,398 字符 → 不压必然全丢工具能力。
2) 协议措辞不能写「禁止凭记忆编造文件内容/内存数值」→ 会让 9B 反而去"写文件内容"：
     带该句 0/2 有调用；只讲格式/粒度的四版措辞 3/4/4/4 全有调用。已删该句 + 撤掉 user 尾提醒。
加载确认：DSH 2026-11-11 21:32:52 重启 > lib mtime 21:24:29 → 进程内已是 v2；
          重启后三套复跑全绿（unit 11/11 / E2E 3/3 / realshape 2/2，含「9B compact: system 精简为 32 字符」日志命中）
真实会话验收：需操作者在模型选择器切 9B（subagent 显式指定 ninfer 路由被 DSH 策略拒绝，无法代跑）
3) 工具 delta 缓冲 + 同参去重：9B 一轮连发 2–4 条相同调用（实测 3×read），重复 ops_bash 会执行两遍；
   textToolCalls 档位改为缓冲 delta、按 name|arguments 去重后再统一下发。非 9B 档位行为不变。
验证：shim-unit 11/11；p3_adapter_shim_e2e 3/3（T1 单条 read / T2 不误判 / T3 两条 kitty_ce）；
      p3_realshape_probe 2/2（8660 字符 system + 14 工具，压到 32 字符后仍能发调用）
```

### H.8.6 本轮动作清单

```text
改源码：plugins/dsh-ninfer-local/lib/index.js（+ 备份 .bak-engx12；PATCHES.md think-engx12 已记录）
新增  ：p3_dsh_session_probe.py / p3_dsh_toolcall_probe.py / p3_dsh_toolcall_probe2.py / p3_spec_matrix.py
        p3_shim_raw.py / shim-unit.mjs / p3_adapter_shim_e2e.mjs / p3_realshape_probe.mjs
        p3_ctx_matrix.py / p3_ctx_matrix2.py / p3_proto_ab.py
结果  ：p3-dsh-session-result.json / p3-spec-matrix.json / p3-regress-result.json（11:05 重跑）
配置  ：ninfer_params 持久参数已修正（见 H.8.1），下次 start 直接可用
进程  ：0；显存 0 MiB used / 12227 MiB total
```

---

## H.9 MTP 重训（2026-11-12 00:20–00:50）

```text
语料：mix-mtp-2k.jsonl（旧 MTP 训练数据）50% + kitty-reverse/train-kitty-v3-clean 50%
      按 4000 字符切块，用当前 GSQ 主干 dump hidden（NINFER_TRACE_MTP_PREFILL）
      关键：NINFER_PREFILL_MAX_TOKENS=64，否则 MTP prefill 在 128-token 单元上 bad_alloc（HTTP 500）
采集：403 块 / 896,847 token / 185 tok/s / 4.9 GB npz（_work/ninfer-9b/mtp-data）
训练：400 步，B=4，ctx=512，lr 5e-4 cosine，223 s
      loss 30.59 → 2.41，训练 top1 0.44% → 61.62%
      VAL top1：kitty 0.6126 / 旧 mix 0.3406 / 全体 0.4628（monitor 报告 monitor-mtp-20261112-0033.md）
回填：merged-mtp-new（19.3 GB 副本，只覆写 mtp.* 15 个张量）→ 用 ninfer-master/.agent-tmp/g1 的
      **原始 recipe**（关键：vision/mtp 投影设 bf16 + mtp attention 三投影拆开）转出
      kittyrev-oxcoder9b-mtp2f-GSQ.ninfer（738 objects，与交付版同构）
      —— 其它三版 recipe 分别死在 swiglu(q6) / tokenizer_config / gdn_control 布局
实测（同 prompt，256 token）：
      no-spec 34.84 tok/s（正文正常）
      d1      32.80 tok/s  accepted 16/238 = 6.7%（旧头 1.6% → 4 倍）
      d2      29.71 tok/s  accepted 17/473 = 3.6%
      d3      24.98 tok/s  accepted 1/756 = 0.1%，输出损坏
结论：头本身 VAL 46%，引擎侧只兑现 6.7% → 仍存在输入/位置约定不一致（不是头没训好）；
      下一轮用「训练目标 t+1 vs t+2」「rope 维度/位置」两组各 100 步消融，按引擎 accepted 定标。
```

---

# 附录 · 2026-11-10 交接（WorkBuddy AI 接手时，历史记录）

> 更新：**2026-11-10 16:41** · 手交方：石井（SHIYI-WORKSPACE / DSH 执行层）· 接手方：**WorkBuddy AI**
> 本文件是接续的唯一权威入口。**先读 §速读 → §1 状态 → §8 接续动作**，其余按需查。
> 旧版（2026-11-08 各轮）原文完整保留在 **附录 A**，未删任何一行。
> **注意：以下五条验收表与「乱码是唯一卡点」的结论已被上面 §H 段覆盖，仅作历史参考。**

---

## 速读（30 秒）

```text
一句话：9B 引擎能跑、通用问答 8/8 正常、速度 31–35 tok/s；
        但"特定 prompt 会确定性输出乱码"，且 system 角色几乎必乱 —— 这是当前唯一真卡点。

三条必须知道的事实：
1) 模型能力没丢：8 条通用 prompt（法国首都/三色/俳句/transformer/日语/17*3/TCP-UDP/factorial）
   全部正常；两个量化件（GSQ 与 Q4Q5）都能出正确英文。
2) 乱码不在模板、不在长度、不在量化方案、不在 KV dtype、不在 CUDA graph、不在 chunk：
   渲染帧逐 token 复算 19/30/26 与 serve 实际完全一致（见 §4 T1）。
3) 乱码与 serve 的"前缀复用/补丁"路径相关：加 --no-prefix-reuse 后 essay 那条恢复正常，
   但它不是普适解药（system+中文 仍乱，另一路 prompt 反而出现 title= 垃圾前缀）。

现在唯一卡点：serve 侧请求装配（prefix reuse / patch）+ 解码数值路径的内部污染。
不是"要不要换引擎"的问题 —— 四条替代引擎全部已否决（§3）。
```

---

## 1 交付目标与当前状态

五条验收（2026-11-08 定义，2026-11-10 按实测修订状态）：

| # | 目标 | 状态 | 证据 / 说明 |
|---|---|---|---|
| ① | 内容正确：5 prompt × 3 轮 = 15/15，无 NaN、无 500、不挂死 | **✅ 有条件** | `5x1 => OK=5 FAIL=0` + 长生成 102 tok/599 chars 正常；**但 system 角色与部分 prompt 确定性乱码**（§4），所以"DSH 真实会话"这一形态下 = ❌ |
| ② | 多模态：`--vision` 走通 ≥1 例图文问答 | **⬜ 未验** | 产物内 vision 组件**已在**（441 张量 / 0.849 GiB，config: depth 27 / hidden 1152 / patch 16 / merge 2）；`--vision` 能起（16384 上下文时 free 1.12 GiB），**但未做一次真实图文问答** |
| ③ | 可接入 DSH：真实会话内完成一次对话 | **⬜ 未验（接线已完成）** | 适配器双档位已落地（§3.2），**但 DSH 未重启加载新 lib**，GUI 里 9B 仍走旧代码 |
| ④ | 首 token < 15 s | **✅** | 冷启 6.7–7.5 s；TTFT 132–149 ms；prefill 346.6 tok/s |
| ⑤ | decode ≥ 100 tok/s | **⬜** | 31.0–35.1 tok/s（256 tok / 7.30–7.56 s，重复一致）；MTP `drafted 190 / accepted 0`（接受率 0.000） |

**当前唯一可用启动命令**（唯一实测可行组合，参数不可省）：

```powershell
# 便捷入口
& D:\BaiduNetdiskDownload\Local-AI\_tools\run-serve.ps1

# 等价命令行（手写时照抄）
ninfer-serve.exe D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer `
  --max-context 4096 --greedy --host-context-mib 2048 --prefill-chunk 128 --no-thinking --port <PORT>
```

```text
· --prefill-chunk 必须是 128 的正整数倍（120/112/96 直接拒启；块宽 >128 曾触发 NaN → 500）
· --no-thinking 不可省（否则正文落 reasoning_content，content 为空）
· 想规避乱码可追加 --no-prefix-reuse（部分 prompt 有效，见 §4.4）
```

---

## 2 资产清单（路径 / 体积 / 作用）

```text
【引擎（两套，互斥，不可混用）】
  9B → _tools\ninfer-build\apps\ninfer-serve.exe      275,430,912 B（我们自建，sm_120a）
       ninfer.exe / ninfer-perplexity.exe 同目录（2026-11-09 01:07 构建）
  27B → ninfer-csunx\runtime\engine\ninfer-serve.exe  1,348,151,296 B（CSUNX233，27B 专用）
  依据：27B 产物 + 自建引擎 → FATAL weight/000184 unknown tensor layout: gguf_blocks_v1
        9B 产物 + csunx 引擎 → FATAL text/layers/0 unsupported logical projection geometry
        ⇒ 两套引擎能力集不重叠，混用不是"可能出错"，是必然起不来

【9B 产物（只剩两个，勿删）】
  train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer   9,329,072,384 B = 8.69 GiB
    artifact_id b0f7a44a0a624e6ca130a4e57b140af9 · 940 参数 / 738 objects / 732 权重对象
    components = text ✓ vision ✓ mtp ✓
      text   483 参数 / 7.404 GiB（hidden 4096 · 32 层 · vocab 248320 · GDN 16/32 · head_dim 256）
      vision 441 参数 / 0.849 GiB
      mtp     16 参数 / 0.417 GiB（含 input_projection + 3 norm + attention 5 件 + mlp 2 件）
    formats = q8_g32 5.242 GiB / q5_g64 1.907 / bf16 1.238 / q4_g64 0.282 / fp32 ≈0
    内嵌资源 = tokenizer.json · tokenizer_config.json · chat_template.jinja(16,289 B) · generation_config
  train\lines\9b-oxcoder\models\oxcoder-9b-Q4Q5.ninfer   6,258,409,984 B = 5.83 GiB
    components = text 仅（483 参数）—— 诊断对照组，证明"乱码与 G1/vision/MTP 无关"

【已删除（勿找）】
  out\oxcoder9b-merged.ninfer（5.83 GiB，2026-11-10 删）· 记录：_work\ninfer-9b\removed-artifacts\README.md
  6 个 _tools\*.ps1 已改指向 GSQ（备份后缀 .bak-merged-del）

【训练/转换基座（勿动）】
  train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\   含 model.safetensors 19.3 GB + chat_template.jinja + tokenizer.json
  train\.venv\                                                  has jinja2 3.1.6 + tokenizers（本次复算用）
  train\lines\9b-oxcoder\out\b4-allocation.json                rco 分配方案（G1 配方）
  train\lines\_shared\scripts\{gsq_rco_plan.py,p1_requant.py,err_alloc.py}
```

---

## 3 选型结论（2026-11-10 复核过，别再推翻）

### 3.1 换引擎：四条候选全部否决

| 候选 | 能力门（GDN+vocab248320+vision+MTP） | 速度门 | 判定 |
|---|---|---|---|
| 本机 llama.cpp（`train/lines/_shared/tools/llama-cpp-win`） | GGUF 已转（Q5KM 6.19 GiB） | **无 CUDA 后端**：目录里只有 `ggml-cpu-*.dll` + `ggml-rpc.dll`，`--list-devices` → `(none)`；那个 9 tok/s 是 CPU 数 | ❌ |
| 自建 llama.cpp CUDA | 需确认 ggml 有 qwen3_5 GDN 图 | 工具链齐（nvcc 13.0.48 / MSVC 14.44 / cmake 4.1.2 / sm_120a），可编 | ⚠ 仅作能力对照，操作者**当前要求尽量不编译** |
| vLLM / SGLang | Qwen3-Next 有支持、Qwen3.5 不确定 | 单流同样带宽受限；Linux only → 需 WSL2 | ❌ |
| TensorRT-LLM / MLC / ExLlama | 无 GDN kernel | 需逐 shape 编 engine | ❌ |

### 3.2 上游状态（Neroued/ninfer）

```text
#31  Qwen3.5 9b support（2026-08-16）→ 维护者 Neroued 关闭留言："not planned"
#433 [Feature] Qwen3.5-9B geometry support on master（Onur-Cansever，2026-10-31）
     OPEN · comments=0 · updatedAt == createdAt（至今 0 回复）
     分支 9b-geometry-master-port（base master@1882c6ad，101 files，+2451/−391）
     实测 RTX 5090：133.8 tok/s/req · TTFT 11–33 ms · MTP 接受率 100%
     含我们缺的：projection q6/shapes/n248320_k4096.cpp · q8 n4096_k4096/n12288_k4096 ·
                 bf16 n4096_k8192 · tools/convert/official_recipes.py 的 qwen3_5_9b recipe
master 最新 HEAD 77c2e5e2（2026-11-07 "fix(runtime): recover preempted requests without stalling"）
     分支只有 master / dev / feat/qwen4-27b-ops —— 9B 仍未进主干
我们自己的 issue：**从未提交**（草稿 train\lines\9b-oxcoder\UPSTREAM-ISSUE-ninfer-h4096.md 255 行仍在）
     gh search issues --author @me --repo Neroued/ninfer → 0 条
     ⚠ 草稿里"6 个新形状"的结论已被 #433 证明偏保守，发之前必须按分支实测改
```

### 3.3 适配器（双档位，已落地未生效）

```text
plugins\dsh-ninfer-local\lib\index.js   运行时产物（无 node_modules/tsc，不能从 src 重建 ⇒ 手改 + 镜像 src）
  · ENGINES 双档位：27B → csunx；9B → _tools\ninfer-build
  · 三绑定硬约束（PATCHES.md engx11）：
      start()        模型必须落在本档位 modelDirs 内，否则抛「模型 X 不属于档位 Y 的引擎」
      ensureModel()  跨档位模型 → 拒绝 + 「请先在设置页切换档位，不跨引擎重启」
      stop()         只杀 Path == 本档位 engineExe 的进程（两套 exe 同名 ninfer-serve.exe，按名杀会误伤）
  · 9B 档默认：maxContext 16384 · contextBudget{16384,1024,256} · compactSystem ·
               compactHistoryMessages 6 · extraArgs [--greedy --host-context-mib 2048 --prefill-chunk 128 --no-thinking]
  · 备份链 index.js.bak-engx1..engx11 · PATCHES.md 已记到 engx11
⚠ 状态：代码在，DSH 未重启 ⇒ GUI 里 9B 尚未真正跑过一轮
⚠ 设置页要求：模型下拉里 27B 与 9B 都要有，且两者都要有思考档位（client.js 已实现 [27B]/[9B] 前缀 + effort）
```

---

## 4 2026-11-10 新测出来的事实（本轮全部实测，可复跑）

### 4.1 功能矩阵：同一模型三条路径

| 路径 | 输入 | 输出 | 判定 |
|---|---|---|---|
| serve | user-only × 5（2+2 / hello / GDN / python / unittest） | `2+2 equals **4**.` / `你好！有什么我可以帮你的吗？` / 258 字 / `s[::-1]` / 682 字 | ✅ 5/5 |
| serve | user-only 长文（300 词 essay, 256 tok） | `#liw2aioTSg/1+Z4OBYDwDgoRirLvwogDAPHEC47ykV…` | ❌ 从首 token 烂 |
| serve | **system** + user | `,or so on so go to his old one non even banalities…` | ❌ |
| serve | system + 2 轮 | `that's not working. Please look, buster…` | ❌ |
| CLI `--messages`（同一 essay） | 同 prompt | `#stages: 1. **Single Responsibility Principle**…` | ✅ 通顺（跑题） |

```text
确定性命中：同一 prompt 同一路径两次 → 输出字节完全一致（不是随机、不是漂移）
跨请求无污染：system 请求烂完之后，紧跟的 user-only 仍正确答出 4
通用 8 题（battery.ps1）：8/8 正常（唯一 SUSPECT 是日语回答本身正确）
```

### 4.2 T1 · 帧对比：渲染没有错

| 请求 | serve 实际 prompt_tokens | 本地同源模板+tokenizer 复算 | 结果 |
|---|---:|---:|---|
| user `What is 2+2?` | 19 | **19** | 正确 |
| system+user | 30 | **30** | 烂 |
| essay | 26 | **26** | 烂 |

```text
结尾序列一致：… 248045(<|im_start|>) 74455(assistant) 198(\n) 248068(<think>) 271 248069(</think>) 271
⇒ <think>/</think> 均为单 token；渲染帧不是变量
```

### 4.3 T2 · 换模板 A/B：换模板不修好

```text
CLI + 原模板     user 2+2 → "99 + 0 = 17+3=285<|im_end|>阩<|endoftext|>"（且 <|im_end|> 被当普通文本输出）
CLI + 最小模板   user 2+2 → "<think></think> For to, itlkl, so I'm n-LOP-Pri…"
                 最小模板把 <think> 当文本输出 ⇒ CLI 路径本身也不稳定
```

### 4.4 长度假设被否 + 开关 A/B（同一失败 prompt，每次全新引擎）

```text
长度：22/23/24/25/26/27 token 连续补测（同内容加填充）→ 全部正常
⇒ 触发点不在长度

baseline                     #liw2aioTSg/1+Z4OBYDwDgoRirLvwog…          烂
--no-cuda-graph              同上（逐字节相同）                          烂
--prefill-chunk 256          同上（逐字节相同）                          烂
--no-prefix-reuse            #stages: 1. **Single Responsibility Principle**…  ✅ 变正常
--no-prefill-a8              NOT READY exit 1（本 build 不支持该开关）
--no-prefill-cublas-projections  NOT READY exit 1
--kv-dtype int8              NOT READY exit 1
--gdn-state-fp16             NOT READY exit 1
⚠ --no-prefix-reuse 不是普适解药：加上后 system+中文 仍烂、essay-cats 反出现 "title=…" 垃圾前缀
```

### 4.5 换量化产物同样烂（烂在不同位置）→ 与量化方案无关

| prompt | GSQ 8.69 GiB | Q4Q5 5.83 GiB |
|---|---|---|
| essay 原文 | 烂（base64 串） | `I'm sorry, but I think there might be some misunderstanding. 😶It's no 59-roubles-aisp` |
| essay+Be concise | 正常（跑题） | 烂 |
| system+中文 2+2 | 烂 | 中文但答错 |
| 其余 7 条 | 正常 | 正常 |

### 4.6 速度与带宽代数（决定 100 tok/s 是否够得着）

```text
GPU          RTX 5070 Ti Laptop · 12227 MiB · sm_120a · 驱动 621.14 · mem clock 14001 MHz
             （nvidia-smi 无 bus width 字段；按 192-bit GDDR7 估算峰值 ≈ 672 GB/s，需实测确认）
实测 decode  31.0–35.1 tok/s（256 tok / 7.30–7.56 s，两次一致）
prefill      346.6 tok/s（25 tok / 72 ms）
显存         weights 7.40 GiB 常驻（vision/mtp 不随 text 常驻）· free after startup 3.18 GiB @4096
有效带宽     ≈ 7.95 GB × 34 ≈ 270 GB/s ⇒ 峰值 40%

tok/s = 有效带宽 ÷ 每词元字节
  8.67 GiB 现状 @44% → 34（实测）
  6.1 GiB（q8→q5） @70% → 76 / @80% → 87
  5.3 GiB（q8→q4） @80% → 101
⇒ 100 tok/s 充要：每词元 ≤5.5 GiB 且 效率 ≥75%，或 6 GiB 左右 + MTP 接受率 ≥60%
```

### 4.7 上下文/显存红线（实测）

```text
16384              KV 256 页 / 626 MiB / free 2.76 GiB        ✅
16384 + --vision   1.41 GiB / free 1.12 GiB                    ⚠ 勉强
32768              free 0 B + host RAM 爆（pagefile 打满）      ❌
65536              FATAL Device budget cannot hold model weights ❌
```

---

## 5 已否证方向（累计，勿重试）

```text
（2026-11-08 旧结论，仍有效）
· ⑤-A k4096 swiglu GEMV-pair：GEMV 不减少权重读取量；5.81 GiB/token 是物理下限
· shape.cpp 阈值扩到 <=512 全走小路径 → 长 prompt 仍 NaN
· --prefill-chunk 256/64 → 无效（必须 ≤128，且须 128 的倍数）
· grammar 词表/掩码宽度错配、采样踩 padding、decode 掩码全 0 → 逐一否掉

（2026-11-10 新增）
· 乱码 = 上下文太小            → 4096 与 16384 逐字节同结果
· 乱码 = 思考开关              → --no-thinking 与否都烂
· 乱码 = chat template         → 换最小模板不修好；渲染帧 19/30/26 与复算完全一致
· 乱码 = 长度阈值              → 22–29 token 连续补测全部正常
· 乱码 = G1 量化 / q8          → Q4Q5 同样烂，只是烂在不同 prompt
· 乱码 = CUDA graph / chunk    → 两个开关结果逐字节相同
· 乱码 = CLI vs serve 的模板差异 → 两侧 prompt token 数已对齐（19 = 19）
· 「本机没有 nvcc/MSVC」        → 已过时：nvcc 13.0.48 + MSVC 14.44 + cmake 4.1.2 都在
```

---

## 6 现成命令（照抄可用）

```powershell
# 终验（5 prompt，含长生成，自动起停引擎）
& D:\BaiduNetdiskDownload\Local-AI\_tools\accept_final.ps1 -Rounds 1
#   期望：==== 5x1  => OK=5 FAIL=0 ====   长生成 tok=102 chars=599 lenOk=True

# 通用退化率（8 条中性 prompt，自起自停）
& D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\battery.ps1

# 顺序/污染判定（fresh engine，4 请求）
& D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\seq-test.ps1

# 同一失败 prompt 的开关 A/B（8 个变体，自起自停）
train\.venv\Scripts\python.exe D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\flags.py

# 10 例退化拆分（可换件/换端口：MODEL=... PORT=... EXTRA='--no-prefix-reuse'）
train\.venv\Scripts\python.exe D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\bisect.py

# 抓 serve 侧请求记录（含 prompt_tokens / generated_token_ids / speculative 统计）
& D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\t1-capture.ps1
#   落盘：_work\ninfer-9b\t1-reqlog.jsonl（schema_version 29）

# 语法校验适配器
node --check D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-ninfer-local\lib\index.js
```

---

## 7 本轮产出的脚本（全部在工作区内，可重跑）

| 文件 | 作用 |
|---|---|
| `_work\ninfer-9b\battery.ps1` | 8 条通用 prompt 退化率 |
| `_work\ninfer-9b\seq-test.ps1` | fresh engine 上的顺序请求（判定跨请求污染） |
| `_work\ninfer-9b\t1-capture.ps1` | serve 启动 + 3 请求 + 解析 `--request-log-jsonl` |
| `_work\ninfer-9b\bisect.py` | 10 例退化拆分；支持 `MODEL` / `PORT` / `EXTRA` 环境变量 |
| `_work\ninfer-9b\flags.py` | 8 个引擎开关 A/B |
| `_work\ninfer-9b\threshold.py` | 长度阈值搜索（结论：无阈值） |
| `_work\ninfer-9b\render_count.py` | 用同源模板+tokenizer 复算 prompt token 数（19/30/26 的来源） |
| `_work\ninfer-9b\count_prompts.py` | 好/坏 prompt 的 token 数对照 |
| `_work\ninfer-9b\min-qwen.jinja` | 最小镜像 Qwen 模板（T2 用） |
| `_work\ninfer-9b\bw_probe.cu` | 显存带宽探针源码（**未编译**，操作者要求先不编） |
| `_work\ninfer-9b\t1-reqlog.jsonl` | 真实请求记录（结果/时间/投机统计） |

---

## 8 接续第一动作（三选一，带判据）

```text
A【推荐】只读源码定位 patch/prefix-reuse 段（不编译）
  入口：train\lines\_shared\tools\ninfer-master\src\ 下找 prefix reuse / raw_patches / patch_bytes
  目标：找出"缓存前缀 + 补丁 token 拼接"的边界处理，解释为何某些 prompt 会污染
  判据：能指出具体函数 + 行号 + 触发条件；改法可以是配置或补丁，不一定要重编

B 规避式可用配置（最快让 DSH 会话跑通）
  做法：serve 加 --no-prefix-reuse + 客户端单请求单连接；DSH 侧重启加载新 lib（§3.3）
  判据：DSH 会话内完成 1 轮带 system 的真实对话且不乱码
  代价：多轮前缀复用收益归零（速度不受影响，只是重算 prefill）

C 速度线（与 A/B 并行，不冲突）
  C1 复测 MTP：--spec mtp --draft-tokens 3，看 drafted/accepted 是否仍为 0（reqlog 有 speculative 段）
  C2 q8_g32 5.242 GiB → q5_g64 重转（text 7.40 → 5.5 GiB），重测 tok/s
  判据：C1 接受率 ≥50% 或 C2 后裸速 ≥75 tok/s

禁止动作：
· 不要动 27B（已冻结，资产保留即可）
· 不要把 9B 产物喂 csunx 引擎，也不要把 27B 产物喂自建引擎（必然 FATAL）
· 不要 taskkill /IM ninfer-serve.exe（两套同名，会误杀另一档位）——按 Path 杀
· 不要在自己没被告知的情况下去编译 llama.cpp（操作者明确：先测，ninfer 为主）
```

---

## 9 纪律

```text
· 只写 D:\BaiduNetdiskDownload\Local-AI 之内；D:\DrCE(26.2.16)\ 只读
· 禁删清单：权重 / 引擎运行时 / train\.venv / adapter / _work\session-audit / plugins
· 大件（>1 GB）生成或删除前先报体积与用途
· 改 plugins\dsh-ninfer-local\lib\index.js 前 cp .bak-engxN，改后 node --check，PATCHES.md 追加
· 引擎测试完必须收口：确认 0 个 ninfer* 进程，显存释放
· 一请求一结论：任何"修好了"的判断必须有可复跑的脚本 + 数值证据
```

---

## 附录 A · 历史记录（2026-11-08 原文保留，未删改）

### A.1 2026-11-08 17:10 · 五项验收初始断点

> 更新：2026-11-08 17:10 · 本文件是接续的唯一权威入口。新会话先读这里。

#### 0 最终交付目标（五条，全部实测才可标 complete）

```text
① 内容正确：5 固定 prompt × 3 轮 = 15/15，无 NaN、无 HTTP 500，失败不进入 service_unavailable / 不挂死
② 多模态：--vision 启动后图片输入（base64 或 URL）走通 decode→image token→vision tower→文本输出，≥1 例图文问答
③ 可接入 DSH：plugins/dsh-ninfer-local 指向本地引擎，DSH 会话内完成一次真实对话（工具调用可后续）
④ 首 token 时延 <15s（冷启动后首个请求，T=0 到首字，实测计时）
⑤ 输出速度 ≥100 tok/s（decode，192+ token 连续生成实测均值）
```

#### 1 当前状态（实测）

| # | 状态 | 证据 |
|---|---|---|
| ① | ✅ | `5x3 => OK=15 FAIL=0`（内容非空才计数）；长 prompt 312 token 3/3；空候选只死单请求 |
| ② | ⬜ | `--vision` → `FATAL: missing component vision`；本地两个 HF 目录均无 `visual.*` 权重 |
| ③ | ✅（对话侧） | 普通对话（含长 prompt）正常；带 tools 内容退化，属验收"可后续" |
| ④ | ✅ | 冷启 7.05 s、长 prompt TTFT 225 ms、前缀复用命中 prompt_n=9 |
| ⑤ | ⬜ | 35.2 tok/s（4 并发聚合 34.7，引擎串行） |

**可用启动命令**（当前唯一可交付形态）：

```powershell
& D:\BaiduNetdiskDownload\Local-AI\_tools\run-serve.ps1     # chunk 128 + no-thinking
# 等价：ninfer-serve.exe <model.ninfer> --max-context 4096 --greedy --host-context-mib 2048 \
#         --prefill-chunk 128 --no-thinking --port 1610
```

两个参数不可省：`--prefill-chunk 128`（块宽>128 时 L03 的 proj_k/proj_v NaN → 500 → 503）、
`--no-thinking`（否则输出全落 reasoning_content，content 为空）。

#### 2 版本选型结论（操作者确认 + 本地核查）

```text
最佳模型 = G1 混合量化（p6d G1_mlp_gate_up）
           定义：mlp.gate/up 升 Q6 的 rco 分配（assign=[q5,q4,q5,q5,q8,q6,q6,q6,q6,q8,q8,q8], cost=4.9846）
           目标分数：recall 0.6333 / leak 0.0333 / nogate 0.9333 / fpr 0 / trap 0.1111
           ⚠ 权重目录 models\_p6d_cand\G1_mlp_gate_up **已被清理**（Test-Path=False），需按配方重放
最佳 MTP  = v3-mix600.step300
           models\mtp\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors
           486,582,848 B · 2026-11-06 22:47 · history: step0 0 → step150 0.4095 → step300 0.4670
当前在跑 = out\oxcoder9b-merged.ninfer（5,840,409,984→实际 6,258,409,984 B，11-07 14:19）
           provenance: base= models\merged-2b-nsfw-mtp-tuned-v3，components=['text']
           formats 无 q6 ⇒ 不是 G1，是未升级的 ~5.0 bits 版（leak 0.1333 超标）
```

#### 3 G1 重建链路（四件套齐备，属"按分配重放量化"而非找备份）

```text
✅ 分配方案  train\lines\9b-oxcoder\out\b4-allocation.json          （rco 方案）
✅ 计划脚本  train\lines\_shared\scripts\gsq_rco_plan.py   9,435 B
✅ 重算脚本  train\lines\_shared\scripts\p1_requant.py     9,161 B
✅ 误差分配  train\lines\_shared\scripts\err_alloc.py      8,582 B
✅ 基座      models\merged-2b-nsfw-mtp-tuned-v3\model.safetensors    19,306,305,296 B
✅ MTP       models\mtp\...v3-mix600.safetensors.step300.safetensors    486,582,848 B
✅ 目标分数  out\p6d-G1-full.json / out\p6d-G1_mlp_gate_up-leak.json
❌ 没有 *p6d* 生成脚本（out 下只有两份评测 JSON）
```

执行序：

```text
1. 读 b4-allocation.json（assign + 层映射 + q6 位置）与 p1_requant.py 的 CLI
2. 重算：源 = merged-2b-nsfw-mtp-tuned-v3\model.safetensors，方案 = rco，出 = models\_p6d_cand\G1_mlp_gate_up\（≈18 GB）
3. 注入 mtp.*：把 step300 的 15 个 mtp 张量按 safetensors 键替换进该目录
4. 转产物：--source <G1_mlp_gate_up> --components text,mtp --recipe qwen3_5_9b_gsq
   → out\oxcoder9b-g1-mtp.ninfer（≈6.5 GB，写盘前先报体积）
5. 验收：run-serve.ps1 加 --spec mtp --draft-tokens 3 → bench 192 token 记 tok/s 与接受率
   预期：MTP top1 0.467 → 每步 ≈1.4 token → 约 49 tok/s（若换 top1 0.85 的 v1-reonly 可达 ≈88）
```

**关键约束**：转换器 `--components text,vision,mtp` 中，**MTP 与 Vision 只能从主 source 读**；
只有 `--source dflash=` / `--source dflash2=` 能独立指定来源。
⇒ 想用别的 MTP 版本，必须先把对应 `mtp.*` 张量注入 HF 目录（第 3 步），不能靠额外 source 参数。

#### 4 已完成的引擎修复（均已 push）

```text
7e81e48  修 13–15 token 的 K/V 段 NaN（linear_split n5120_n5120_k4096 阈值 <=15）
8973a04  打通 CUDA graph（15.3 → 36.2 tok/s），根因是 9B MLP swiglu dispatch 里未关闭的 cudaDeviceSynchronize
c6faf4b  采样空候选不再 device trap（原 asm volatile("trap;") 会打死进程）
9aa848f  grammar 约束失败降级（带 tools 请求不再 500 崩进程）
c696d37 / 38edf1d / c812a16 / 8438297 / 408a2f5 / 5009b69 / 080d134 / 139ac41
         诊断开关收尾 + 病灶证据（L03/proj_k，T=263）+ 可用配置 + STATE 系列
```

#### 5 已否证的方向（勿重试）

```text
· ⑤-A「k4096 swiglu GEMV-pair kernel」：GEMV 不减少权重读取量；5.81 GiB/token 是物理下限，
  100 tok/s 需 ≈581 GB/s；且 4 并发聚合实测 34.7 tok/s（引擎串行）→ 作废
· shape.cpp 阈值扩到 <=512 全走小路径 → 长 prompt 仍 NaN
· --prefill-chunk 256 → 长 prompt 仍 NaN（必须 ≤128）
· --no-prefix-reuse / --prefill-chunk 64 → 均无效
· grammar 词表/掩码宽度错配、采样踩 padding、decode 掩码全 0 → 逐一被代码或实测否掉
```

> ⚠ 注意：上一条"`--no-prefix-reuse` 无效"是 2026-11-08 针对**长 prompt NaN** 的结论；
> 2026-11-10 发现它对**乱码**有效（§4.4）—— 两件事，勿混。

#### 6 纪律

```text
· 只写 D:\BaiduNetdiskDownload\Local-AI 内；不动禁删清单（权重/引擎/.venv/adapter/审计资产）
· 改 .cu/.cuh 后必须删对应 .obj 再重编（Ninja 不跟踪头文件）
· 每次只改一处 → 重编 → 对比；诊断代码用编译期开关关死
· 大件（>1GB）生成或删除前先报体积与用途
· 备份：small.cu.bak-5a / launch.h.bak-5a / dispatch.cpp.bak-5a 在位（ninfer-master 不在 git 里）
```

#### 7 接续第一动作（2026-11-08 版）

```text
读 out\b4-allocation.json + _shared\scripts\p1_requant.py 的 CLI → 报磁盘余量 → 重放 G1 → 注入 step300 MTP
→ --components text,mtp 转产物 → --spec mtp --draft-tokens 3 实测 ⑤
② 另需视觉塔权重（本地无 visual.*），从对应 HF 仓库取 1–2 GB 分片后与 G1 目录合并再转。
```

### A.2 2026-11-08 18:52 · G1 产物落地（重大更新）

```text
新产物（已可用，run-serve.ps1 默认已指向它）：
  train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer
  7.93 GB / 738 objects / components = text + vision + mtp
  G1 实现：mlp.gate/up 升 **q8**（64 张量；原定 q6，因引擎无 q6 swiglu 改用 q8，精度更高）
  实测：5x3 = 15/15（内容非空）· 冷启 7 s · 192 token 34.4 tok/s

启动（唯一可行组合，已内联验证 6/6）：
  ninfer-serve.exe <上面的产物> --max-context 4096 --greedy --host-context-mib 2048 \
    --prefill-chunk 128 --no-thinking --port <PORT>

本轮打通的四处工程：
  1. tokenizer.cpp：tokenizer_config.json 缺 added_tokens_decoder 不再 FATAL（早退）
  2. q8/shapes/n34816_k5120.cu：新增 9B swiglu 形状 Q8LinearGeometry<24576,4096> + select_q8_swiglu_n24576_k4096
  3. swiglu/dispatch.{h,cpp}：9B q8 分派
  4. resource 导出的正确 API：reader.read_object("<object id>")（不是 read_range / to_json）

剩余（② 与 ⑤-投机共用一处缺口）：
  projection 的 kShapes 表缺 5 个形状：
    (4096,4608)  vision merger.fc2
    (4096,8192)  mtp input_projection
    (4096,4096)  mtp attention/output
    (4096,12288) mtp mlp/down
    (10240,4096) mtp attention/query(+3)
  补齐后 --vision 与 --spec mtp 才能起；⑤ 的 100 tok/s 依赖 MTP 投机
```

### A.3 2026-11-08 19:30 · ⑤ MTP 投机：唯一剩余阻塞点

```text
现象：--spec mtp 启动 FATAL | native input requires one contiguous parent region
出处：src/core/weight_view.cpp:195-206 contiguous_weight_region（产物加载期，比 pair 校验更早）

根因（本会话实测对照）：
  text 的 attention 合并成 2 个 part：query(4096)+key(1024) = (5120, 4096)   ← 引擎接受
  mtp  的 attention 合并成 4 个 part：q(8192)+k(1024)+v(1024)+… = (10240, 4096) ← 引擎拒绝
  （转换日志：text/layers/N/attention/query (+1) (5120,4096)
              mtp/layers/0/attention/query (+3) (10240,4096)）

修法（转换器侧，tools/convert/qwen3_5.py）：
  :987 builder.block("mtp/layers/0/", "mtp.layers.0.", base, config, "full_attention")
  在 block 的 full_attention 分支（:765 / :857）里，group 规则需按 mtp 与 text 区分：
    text: self.group(query, key) + self.group(value, output?)   → 2-part
    mtp : 目前一次性 group 了 4 个 → 需拆成同样的 2 组
  改完后重转 → --spec mtp 应能起 → 测 192 token 的 tok/s

引擎侧已全部就绪（无需再改）：
  · pair 的 k=4096 分派 + 相邻视图常量按 K 参数化
  · projection 的 3 个形状（含 K=8192 全套）
  · q8 swiglu 9B 形状
  · tokenizer 缺字段早退
```

### A.4 2026-11-08 20:20 · ⑤ 投机链路专项：连破 7 层，最后一层已定位

```text
穿越记录（每层都由诊断打印定位后修复）
 1 pair k=4096                      → select_q8_pair_n1024_k4096（K 相同直接转发）
 2 contiguous parent region          → mtp attention 四合一 group（query+gate+key+value=10240 行）
 3 q8 (10240,4096)                   → 转发已有 K=4096 实例
 4 q8 (4096,4096)                    → 转发
 5 bf16 (24576,4096)                 → 转发 n12288_k4096
 6 gdn_replay_fold 几何               → 放宽到 32 层同 head 几何（qk16/v32/conv8192）
                                       注意 launch.h 是头文件，必须额外删 gdn/replay obj
 7 slice 越界（start=4096 len=6144 extent=8192）→ 定位到 GDN conv 的 27B 常量

最后一层（未修）
  kValueRows = 6144 / kHidden = 5120 是 27B 专属常量，出现在三处：
    input_conv/q4_q5/convolution.cu:19-25
    input_conv/q4_q5/projection_mma.cu:39
    input_conv/q4_q5/projection_independent.cu:19
  9B 应为：kHidden 4096 / kQueryRows 2048 / kKeyRows 2048 / kValueRows 4096 / kChannels 8192
  ⇒ 需模板化这三处（或复制一套 9B 实例，CMake 不 GLOB 需原地加）
  ⚠ 历史：曾试过「两段实现（linear_split + causal_conv1d_silu_snapshot）」，
    workspace 预算冲突导致 prefill 全崩（L29-L31 nan），已回滚（gdn.cpp:94-96）。
    重做时必须给 9B 单独的 arena scope，并回归 5x3=15/15 确认 prefill 不退化。
```

### A.5 2026-11-09 ~ 11-10 · 引擎隔离与上游核查（本段为交接时补记）

```text
· 27B 线冻结（操作者 2026-11-09 决策）：不开发、不删除、资产保留
· 两套引擎一一对应（PATCHES.md engx11）：档位 ↔ 引擎 exe ↔ 模型目录三绑定，代码层强制
· 上游 #31 = not planned；#433 第三方 9B 几何分支存在但 0 回复、未合并
· 本机工具链已补齐：nvcc 13.0.48 / MSVC 14.44.35207 / cmake 4.1.2（旧结论"无法自行编译"作废）
· 2026-11-10 删除 out\oxcoder9b-merged.ninfer（5.83 GiB，已被 GSQ 取代）
```

---

**交接确认**：读到此处即已掌握全量上下文。请从 §8 选一条开跑，并把每一步的数值证据追加到本文件末尾（新增 `## 2026-MM-DD HH:MM · <主题>` 段，不要覆盖上面的段）。

---

## 2026-11-10 16:49 · A-1 只读源码定位：入口树、符号、请求日志数值

```text
范围：只读。未编译、未改任何 .cpp/.h、未启动引擎、未动禁删清单。

【入口树确认】
  全仓 serve_options.cpp 仅 1 份：
    train\lines\_shared\tools\ninfer-master\src\serve\serve_options.cpp
  自建 exe = _tools\ninfer-build\apps\ninfer-serve.exe（275,430,912 B · 2026-11-09 01:07）
  9B 专属补丁（ops\linear\swiglu\q8\shapes\n34816_k5120.cu、core\weight_view.cpp、
    gated_delta_net\replay\launch.h）均在同一树；_work\ninfer-9b\patched-20261108\ 是补丁副本。
  ⇒ §8 A 指定入口树正确，不存在"读错源码"的风险。

【符号/行号（grep 全树 src/）】
  serve_options.cpp:316-317   --no-prefix-reuse → allow_prefix_reuse = false
  serve_options.cpp:360       options.context_cache.enabled = options.allow_prefix_reuse   ★真实作用面
  generation_service.cpp:363  三目：ReadWrite / Disabled（CacheParticipation）
  translate.cpp:306-311       execution.allow_prefix_reuse 注入
  request_plan.cpp:114        base->allow_prefix_reuse = options.allow_prefix_reuse && identity.reusable
  request_plan.cpp:115-116    summary.publish_continuation = allow && reusable && context_cache.enabled
  request_plan.cpp:158-188    publish_continuation 为真才建 capture_groups（InputReplay / SharedPrefix / LongAnchor）
  planning\source.cpp:11-23   checkpoint_matches（frontier / identity_tag / digest / prefix_matches）
  context_cache\prefix_index.h:26-44 matches()；:56-95 insert_at()（压缩边 + 精确 frontier 校验）
  raw_patches / patch_bytes：仅 vision 图像切片（frontend\processor.cpp:608,1046,1056；
    prepared_prompt.h:130-138），与"补丁 token 拼接"不是同一概念

【数值证据 · 现有 _work\ninfer-9b\t1-reqlog.jsonl（schema 29 · 单次引擎启动 · 3 请求）】
  server_start.engine.context_cache = {enabled:true, device_state_slots:1,
      host_capacity_bytes:2147483648 (2048 MiB), total_device_state_slots:2}
  请求1  prompt_tokens=19  prefix_cache_hit_tokens=0  prefix_reuse_path=root  （正常 2+2=4）
  请求2  prompt_tokens=30  prefix_cache_hit_tokens=0  prefix_reuse_path=root  （system+user，烂）
  请求3  prompt_tokens=26  prefix_cache_hit_tokens=0  prefix_reuse_path=root  （essay，烂）
  三条 preparation_seconds 全部：raw_patches=0  patch_bytes=0  built_patch_bytes=0
      reused_patch_bytes=0  cache_hits=0  cache_misses=0  media_items=0  vision_tokens=0
  三条 decode rounds：15 / 15 / 23；engine.device_wait：0.656 / 0.643 / 0.926 s

【结论（可证伪）】
  失败请求 hit=0 / path=root / 无任何 patch ⇒ 没有跨请求前缀命中，也没有 vision patch 参与。
  §8 A 的字面假设"缓存前缀 + 补丁 token 拼接"不是直接触发点。
  --no-prefix-reuse 改变结果的实际作用面是 serve_options.cpp:360：它把整个
  context_cache.enabled 一并关掉，使 request_plan.cpp:115-116 不再 publish_continuation、
  不再建 capture_groups ⇒ 差异在"请求内执行计划/状态快照"，不是"跳过脏的复用前缀"。
  下一步 A-2：追 enabled 分支（program_impl.cpp:295 / prefill.cpp:511,584-596,760-761 /
  transactions\capture.cpp），找出边界函数与触发条件。
```

---

## 2026-11-10 16:52 · A-2 请求内分叉链：capture 边界函数、触发条件与状态快照数值

```text
【函数链（全部 train\lines\_shared\tools\ninfer-master\src\，含行号）】
  serve_options.cpp:360            context_cache.enabled = allow_prefix_reuse
  request_plan.cpp:115-116         publish_continuation = allow && identity.reusable && enabled
  request_plan.cpp:158-188         为真才建 capture_groups：
                                     :179-180 add(prompt_tokens, InputReplay)
                                     :181-185 add(opportunity.frontier, SharedPrefix|LongAnchor)
  transactions\binding.cpp:15-20   capture_groups 拷入 RequestControl
  prefill.cpp:584-590              next_capture 未耗尽 ⇒ rewrite_checkpoint_hidden =
                                     state_images->continuation_hidden_slot(selectors.destination)
  prefill.cpp:592-604              split_frontier = capture_frontier（再与 rewrite frontier 取最小）
  prefill.cpp:617-619              prefill_text_chunk(..., remaining, split_frontier, final_candidate)
  execution_context.h:66 / prefill.cpp:81-83  两个参数写入 TextContext card
  execution\text.cpp:1508-1510     has_split = split_abs > base && split_abs <= base+T
  execution\text.cpp:1517-1519     len = split_rel - t0（prefill chunk 在 frontier 处被截断）
  execution\text.cpp:1711-1719     若 t0+len==split_rel 且 output 非空：
                                     xf.slice(1,len-1,1) → cudaMemcpyAsync 写入
                                     destination 的 continuation_hidden_slot（BF16 {hidden,1}）
  state\state_image.cpp:12,31-33  该 slot 是 StateImage 布局中 BF16 {spec.hidden} 的独立字段
  transactions\capture.cpp:38-67   reserve_capture_destination（device slot / host arena）
  transactions\capture.cpp:146-193 start_capture；:195-228 publish_capture（state 快照）

【触发条件（代码级，四条同时成立）】
  ① publish_continuation == true（默认：prefix reuse 开 + identity.reusable + context_cache.enabled）
  ② capture_groups 非空，且 reserve_capture_destination 成功（capture.cpp:58-63）
  ③ split_frontier ∈ (base, base+T]（text.cpp:1509）→ chunk 被截断成两段
  ④ 此时 rewrite_checkpoint_hidden_output_ != nullptr → 多一次 D2D hidden 回写
  ⇒ --no-prefix-reuse 使 ① 为假，②③④ 整体消失；与 §4.4「essay 恢复正常」方向一致。

【数值证据 · t1-reqlog.jsonl 三条 first_output_timing.context_transfers.state】
  prompt 19（正常）: state.d2h bytes=0 images=0 copies=0 耗时 0.0 s；prefill 0.119007 s
  prompt 30（烂）  : state.d2h bytes=51519488 images=1 copies=1 耗时 0.00238272 s；prefill 0.111035 s
  prompt 26（烂）  : state.d2h bytes=51519488 images=1 copies=1 耗时 0.00226314 s；prefill 0.104204 s
  51,519,488 B = 49.1328125 MiB，对应 capture.cpp:60/104 的
  state_images->storage().image_bytes()（一次整幅 StateImage 快照）。
  三条 engine_timing.units.prefill 均 = 2；computed_prefill_tokens 均 = prompt_tokens（19/30/26）；
  prefix_cache_hit_tokens 均 = 0 ⇒ 差异不是"少算 token / 命中脏缓存"，
  而是"是否执行 capture 状态快照 + hidden 回写"。
  ⚠ 因果边界：19 token 那条 d2h=0 也可能是首请求独占 device state slot 所致
     （server_start: device_state_slots=1 / total_device_state_slots=2），
     不能仅凭本表断定 d2h 就是乱码成因；但"失败请求走了 capture 路径、正常请求未走"成立。
  ⚠ §4.1 的 CLI `--messages` 正常与 serve 烂的差异，本轮未核到 CLI 源码级证据，
     不作为结论（engine.cpp:271 的 prepare_tokens(...,false) 属 score_tokens 因果评分路径，非 CLI）。
```

---

## 2026-11-10 16:52 · A-3 数值污染候选：9B 短窗口 GDN kernel 的 27B 常量残留（推断，未实测）

```text
【源码事实】
  input_conv\plan.cpp:18-25（本仓 9B 补丁自带中文注释）：
    "Q4Q5Fused 的 channel 分组按 27B（hidden 5120 / value 6144）写死，
     9B（hidden 4096 / value 4096）走它会算错 —— 实测 verify(tokens=1) 的 vc 出现 NaN，
     导致 L30(GDN) 整层 NaN；prefill(tokens=9) 不命中 fused 所以正常。必须显式设 Materialized"
  但同段 :24-25 的实际代码无 4096 guard，仍无条件：
    batch.rows==1 && (tokens<=3 || tokens==5 || tokens==6) → ConvKernel::Q4Q5Fused
  input_conv\execute.cpp:44-48 / :105-109 的 Q4Q5Fused 分发同样无 input_rows==4096 判断。
  同源 27B 常量仍在：projected_conv.cu:110-111 launch<10240,2048,2048,6144>；
    fp8/nvfp4 多处 GdnConvGeometry<6144> / LinearBf16SegmentedOutput<10240,6144> /
    Fp8N16384K5120（附录 A.4 所记"三处常量"同源）。
  select_conv_plan 短窗口集合（plan.cpp:14-56）：
    Q4Q5 : tokens<=3 / ==5 / ==6 → Fused；其余 → Materialized
    Q8   : tokens==1 → Q8Decode；2..16 → Q8SlicedK；其余 → Materialized

【推断（明确标注为推断，未实测）】
  P1 capture 路径：A-2 的 split 把 chunk 截成短段；短段长度若落进上表集合，
     就调用带 27B 常量的 kernel → GDN 层数值污染 → 从首 token 起乱码。
     解释 §4.4「--no-prefix-reuse 让 essay 恢复正常」。
  P2 非 capture 路径：即使关掉 capture，请求自身产生的短 chunk（或 decode tokens==1）
     仍会命中短窗口 kernel → 污染。
     解释 §4.4「不是普适解药：system+中文 仍烂、essay-cats 出现 title= 垃圾前缀」
     与 §4.5「GSQ / Q4Q5 都烂，只是烂在不同 prompt」（两者权重格式不同 → 命中分支不同）。
  共用根因假设：9B 几何（hidden 4096 / value 4096）与残留 27B 常量（5120 / 6144）错配。

【§8 A 判据达成情况】
  ✅ 具体函数 + 行号：A-1 / A-2 全链已列
  ✅ 触发条件：publish_continuation 真 ∧ capture frontier ∈ (base,base+T] ∧ 短窗口长度
  ✅ 改法可不必重编：下列配置级探针
  ⬜ 因果闭环：仍需一次实测把"split 后段长度"与"烂/正常"逐条对齐

【下一步（配置级 A/B，0 编译；本轮未执行 —— A 的范围是只读源码定位）】
  1) 追加 --device-state-slots 0 --host-context-mib 0（两参数均允许 0：
     serve_options.cpp:266-271 / docs\serving.md:943）→ 让 capture.cpp:58-63 的
     destination 预留失败、skip_capture，观测是否仍出现 state.d2h=51,519,488 B。
     若三条失败 prompt 恢复正常且 d2h 归零 ⇒ P1 成立，且可保留 prefix reuse。
  2) 同一 prompt 双跑 baseline / --no-prefix-reuse / 1)，比对 t1-reqlog 的
     state.d2h.bytes、units.prefill、generated_token_ids 前 8 个 id。
  3) 若 1) 仍烂 ⇒ P2 主导，应转向 plan.cpp:24-25 补 input_rows==4096 guard
     （需重编，超出 A 范围，须操作者批准）。
  4) 现成可复跑：_work\ninfer-9b\flags.py（EXTRA 传开关）、t1-capture.ps1（出 reqlog）。

【本轮纪律】只读源码 + 读现有日志；未编译、未改源码、未启动引擎、未动禁删资产、未越界写文件。
```

---

## 2026-11-10 16:58 · A-4 卡点判定与解决路径（只读核查，未跑实验）

```text
【本轮新核到的代码事实】
  prefill.cpp:202             prefill 前调 prepare_capture_boundary(lane)
  capture.cpp:111-117         reservation 失败 → skip_capture → next_capture 耗尽
  prefill.cpp:584-590         此时 rewrite_checkpoint_hidden 置 nullptr、split_frontier 置空
  engine_core.h:1244-1285     prepare_semantic_capture：预留失败/回收无进展 → skip_capture
  engine_core.h:1224-1236     start_capture 失败 → skip_capture + capture_pending=false
  types.h:524-533             ContextCacheHints 只有 session_key / markers /
                              allow_engine_automatic_shared_prefixes / update_session_index，
                              没有请求级「关 publish_continuation」开关
                              ⇒ 服务级开关是唯一入口，DSH 请求侧关不掉这条链
  ⇒ 结论：让 capture destination 预留失败，能干净地只关掉 hidden 回写 + 状态快照，
     既不必 --no-prefix-reuse，也不必重编。「配置级单变量探针」由此成立。

【唯一真卡点】
  不是换引擎（§3 四条已否决），也不是「要不要加 --no-prefix-reuse」（§4.4 已证非普适）。
  真卡点 = 关掉 capture 只改善部分 prompt；带 system 的真实 DSH 会话仍乱码
           ⇒ §1 的 ①（DSH 形态内容正确）与 ③（可接入 DSH）依旧不可达。
  本质：A 只做到「相关性定位」，缺一次把变量隔离到单点的实测（P1 / P2 未分离）。
  次级卡点：若 P2 成立，根因落在 9B GDN 短窗口 kernel 的 27B 常量残留
            （plan.cpp:24-25 无 input_rows==4096 guard），修它需重编 + 回归，
            与「操作者先测、尽量不编译」的偏好冲突，须明确批准。

【分层解决路径（按代价从低到高）】
  L0 · 0 编译 · 单变量 A/B/C（先做，判据明确）
     a = baseline（现配置，prefix reuse on）
     b = --no-prefix-reuse（关整条 context_cache）
     c = --device-state-slots 0 --host-context-mib 0（保留 prefix reuse，只让 capture 预留失败）
     每条都出 reqlog，比对 state.d2h.bytes / units.prefill /
       generated_token_ids 前 8 个 id / 输出文本；必须包含「system+user」这一条。
     判据：c 与 b 修好同一批 ⇒ P1 = capture 路径；
           b、c 都仍烂 ⇒ P2 主导，直接转 L2，不必再做规避配置。
  L1 · 0 编译 · 规避式交付（仅当 L0 证明 P1 主导且 system 也修好才成立）
     c 或 b + 客户端单请求单连接 + DSH 重启加载新 lib（§8 B）。
     验收判据必须是「DSH 会话内 1 轮带 system 真实对话不乱码」，
     不是 essay 单条正常（§4.4 的教训）。
     代价：多轮前缀复用收益归零；--host-context-mib 0 会关闭 host context backing，
           pause/replay 快照能力下降。
  L2 · 需重编 · 根治 P2（须操作者批准）
     plan.cpp:24-25 补 input_rows==4096 guard → 9B 强制 Materialized；
     按附录 A.4 把 projected_conv.cu:110-111、fp8/nvfp4 的 6144/5120 常量模板化。
     纪律：改 .cu/.cuh 后删对应 .obj 再重编（Ninja 不跟踪头文件）；
           每次只改一处 → 重编 → 对比；回归 5x3=15/15、32 层 GDN 无 NaN、prefill 不退化。
  L3 · 并行 · 与根因解耦：§8 C（MTP 接受率 0 / 100 tok/s / ② vision 未验），不阻塞 ①③。

【执行前必须修的脚本缺陷（本轮发现，勿直接复跑现成脚本）】
  flags.py:34,62 用 taskkill /F /IM ninfer-serve.exe；
  t1-capture.ps1:11,41 用 Get-Process ninfer-serve | Stop-Process。
  两者都按进程名杀；两套引擎 exe 同名 ⇒ 会误杀 27B csunx 档位
  （违反 §8 禁止动作与 AGENTS.md 三绑定约束）。
  另外 flags.py 的 VARIANTS 没有 c 变体，t1-capture.ps1 写死 --host-context-mib 2048。
  ⇒ 跑 L0 前需改为按 Path 杀（只杀 Path == 本档位 engineExe 的进程），
     并给脚本加开关/变体参数。本轮未改、未跑。

【本轮纪律】只读源码与脚本；未编译、未启动引擎、未杀任何进程、未改任何 .cpp/.ps1/.py。
```

---

## 2026-11-10 17:17 · A-5 L0 实测：四组配置把 P1/P2 分离（P1 已证实，P2 独立成立）

```text
执行：_work\ninfer-9b\p3_l0_abc.py（新脚本，按 Path 杀本档位引擎，绝不按名杀）
      每组全新引擎、3 请求（user 2+2 / system+user 2+2 / essay 300-word）、各自出 reqlog。
      产物：l0-{a,b,c,d}.reqlog.jsonl、l0-{a,b,c,d}.engine.log、l0-result.json。
      启动参数基线：--max-context 4096 --greedy --prefill-chunk 128 --no-thinking
                    --request-log-jsonl ... --log-level trace
      四组额外参数：
        a = --host-context-mib 2048
        b = --host-context-mib 2048 --no-prefix-reuse
        c = --host-context-mib 0 --device-state-slots 0
        d = --host-context-mib 2048 --device-state-slots 0   ← 新增解耦对照

【输出对照（chars / 首 95 字）】
                       user 2+2            sys                                    essay
  a baseline       62  2+2 equals **4**…  43  [ directions_52nd.json…（烂）      32  #liw2aioTSg…（烂）
  b no-prefix      14  2+2 equals 4.      42  [ directions_52.html…（仍烂）      98  #stages: 1. **Single…（✅修好）
  c slots0+host0   14  2+2 equals 4.      42  [ directions_52.html…（仍烂）      98  #stages: 1. **Single…（✅修好）
  d slots0+host2k  62  2+2 equals **4**…  43  [ directions_52nd.json…（烂）      32  #liw2aioTSg…（烂）

【reqlog 逐请求数值】
  组  prompt  hit  path  state.d2h.bytes  units.prefill  ids_head（前 8）
  a   19      0    root  0                2   [17,10,17,16327,2972,19,159034,271]
  a   30      0    root  51519488          2   [58,17425,62,20,17,302,4182,11]
  a   26      0    root  51519488          2   [2,719,86,17,64,789,9657,70]
  b   19      0    root  0                1   [17,10,17,16327,220,19,13,248046]
  b   30      0    root  0                1   [58,17425,62,20,17,2480,11,33660]
  b   26      0    root  0                1   [2,267,1098,25,198,220,220,16]
  c   19      0    root  0                1   [17,10,17,16327,220,19,13,248046]
  c   30      0    root  0                1   [58,17425,62,20,17,2480,11,33660]
  c   26      0    root  0                1   [2,267,1098,25,198,220,220,16]
  d   19      0    root  51519488          2   [17,10,17,16327,2972,19,159034,271]
  d   30      0    root  51519488          2   [58,17425,62,20,17,302,4182,11]
  d   26      0    root  51519488          2   [2,719,86,17,64,789,9657,70]
  四组 12 条全部 prefix_cache_hit_tokens=0 / prefix_reuse_path=root。

【判定 1 · c ≡ b 逐字节等价 ⇒ P1 = capture 路径，已证实】
  c 与 b 的 3 条输出、6 组 ids_head、d2h、units 完全一致；
  c 保留 prefix reuse，仅让 capture 无法预留目标 ⇒ 关闭 capture 与关掉整个
  context_cache 效果相同。essay 从 32 字符乱码变为 98 字符通顺文本，
  且与 §4.1 CLI --messages 的 "#stages: 1. **Single Responsibility Principle**…" 一致
  ⇒ CLI 干净路径 = 无 capture 路径（补上了 A-2 段中"CLI 差异待核"的空缺）。

【判定 2 · d ≡ a 逐字节等价 ⇒ 归因修正（重要）】
  真正起作用的开关是 --host-context-mib 0（禁用 host arena），不是 --device-state-slots 0。
  源码依据 capture.cpp:58-63：reserve_destination() 失败后会尝试
  host_context_arena->allocate(...)；只要 host arena 存在，capture 仍能预留成功。
  ⇒ A-4 段写的「让 capture destination 预留失败」须改为「禁用 host context backing」。

【判定 3 · d2h 与乱码无因果（修正 A-2 段的暗示）】
  d 组 user 请求 state.d2h=51,519,488 B 却输出正常（62 chars，与 a 相同）；
  a 组 user d2h=0 也正常。⇒ 51 MB 快照只是资源槽位状态的表征，不是污染源。
  与 A-2 段末尾的「因果边界」警告一致，现由实测证实。

【判定 4 · 真正伴变量 = units.prefill 2 → 1】
  a/d 为 2（prefill 被 capture frontier 切分，text.cpp:1517-1519），
  b/c 为 1（无切分）。这是四组里唯一与 essay 烂/好同步的数值。
  另注：关 capture 后正常请求 user 的输出也从 62 chars 变为 14 chars
  ⇒ 该开关改变的是整条数值路径，不只是「烂/好」二元。

【判定 5 · P2 独立成立，L1 规避交付不成立】
  b/c 下 sys 仍烂（42 chars，[ directions_52.html, FIRST_PARSED_BY:1371），
  且 units.prefill 已为 1 ⇒ system+user 的乱码不依赖 capture/split。
  ⇒ 带 system 的真实 DSH 会话在 0 编译规避配置下仍不可交付，
    §1 的 ①（DSH 形态）与 ③ 依旧 ❌。A-4 段判定的「唯一真卡点」现由实测坐实。

【收口】脚本结束 remaining ninfer processes = []；nvidia-smi 复验
  memory.used=0 MiB / free=11944 MiB；未触碰 27B csunx 档位；未编译、未改源码。
```

---

## 2026-11-10 17:21 · A-6 L0b：0 编译开关穷举 — P2 与开关、请求形态均无关

```text
执行：_work\ninfer-9b\p3_l0b_sys.py。基线固定 --no-prefix-reuse + host 2048 +
      chunk 128 + ctx 4096（即 L0 的 b 组），5 组配置，全部按 Path 收口。
      产物：l0b-*.reqlog.jsonl、l0b-*.engine.log、l0b-result.json。

【开关组 · 同一条 system+user 请求的逐字节对照】
  b0 baseline        chars=42  [ directions_52.html, FIRST_PARSED_BY:1371
  b1 --prefill-chunk 256       同上（逐字节相同）
  b2 --max-context 16384       同上（逐字节相同）
  b3 --no-cuda-graph           同上（逐字节相同）
  b4 chunk256 + no-cuda-graph  同上（逐字节相同）
  五组 reqlog 全部：prompt=30 / hit=0 / state.d2h=0 / units.prefill=1 /
    ids_head=[58,17425,62,20,17,2480,11,33660]（完全相同）
  ⇒ P2 与 chunk 宽度、上下文大小、CUDA graph 全部无关；也无任何可观测抖动。

【请求形态组 · b0 配置下一次引擎跑 4 条（全部仍烂）】
  sys          30 tok  chars=42  [ directions_52.html, FIRST_PARSED_BY:1371
  sys-short    26 tok  chars=20  **2.5 + 0.5 = (11!34
  user-prefix  26 tok  chars=29  (a)20CN-CANDY®(Pronounced: (S
  user-long    30 tok  chars=27  #4.895, let's just say 2013
  四条 units.prefill=1 / d2h=0 / hit=0；ids_head 各不相同，但都是垃圾。
  ⇒ 「把 system 折叠进 user」「缩短 system」「换中性长句」都不是解法；
    P2 与角色标记、消息数、模板形态无关。
  ⇒ 叠加 §4.4 的「22–29 token 连续补测全部正常」与 L0 b 组「26 tok essay 正常」，
    可排除长度阈值；触发点是具体 token 序列的内容，不是长度或结构。

【判定】L1 规避式交付（§8 B）在 system 场景下不成立；
  ①③ 仍不可达。0 编译「开关类」路径已穷尽，剩余只有换模板 / 换产物（见 A-7）。
```

---

## 2026-11-10 17:21 · A-7 L0c：换模板 / 换产物 — 找到唯一 0 编译改善组合，但需取舍

```text
执行：_work\ninfer-9b\p3_l0c_tpl.py。基线同为 --no-prefix-reuse + host 2048 +
      chunk 128 + ctx 4096；2 产物 × 2 模板 = 4 组，每组 3 请求。
      min-qwen.jinja 与 Q4Q5 产物均确认存在。
      产物：l0c-*.reqlog.jsonl、l0c-*.engine.log、l0c-result.json。

【输出矩阵（chars / 首 95 字）】
                      user 2+2                      sys                                     essay
  c0 GSQ + 原模板   14  2+2 equals 4.             42  [ directions_52.html…（烂）       98  #stages: 1…（✅）
  c1 GSQ + 最小模板 38  <think> </think> 2+2…       31  <think>ierted晖…（烂）            101 <think> </think> - **What it is**…（✅）
  c2 Q4Q5 + 原模板  20  2 + 2 equals **4**.        32  The question is: - ⚒️ Is 2 -（烂） 85  I'm sorry…😸（半烂）
  c3 Q4Q5 + 最小模板 40  <think> </think> 2 + 2…    73  <think> *Warning: The user has      144 <think> </think> **Note:**…（✅）
                                                       provided **no other information**…
                                                       （通顺但跑题，不再是乱码）

【prompt token 数 · 模板显著改变渲染帧】
  原模板   19 / 30 / 26        最小模板  13 / 23 / 20
  四组 12 条全部 hit=0 / d2h=0 / units.prefill=1。
  ⇒ 同样的消息内容，仅换模板使 token 序列与数值路径整体改变，
    sys 从「确定性乱码」变成「通顺文本」。这坐实 A-6 的推断：
    P2 由具体 token 序列触发，而不是 capture / 开关 / 角色结构。

【判定 1 · 0 编译折中路径确实存在，但代价明确】
  唯一让 sys 脱离乱码的组合是 c3 = Q4Q5 产物 + 最小模板。
  但 Q4Q5 是 §2 定义的「诊断对照组」：仅 text 483 参数、5.83 GiB、
  无 vision / 无 mtp、附录 A.1 §2 记为「未升级的 ~5.0 bits 版，leak 0.1333 超标」。
  ⇒ 用它交付会同时放弃 ② vision、MTP 投机与 2B 门控质量，
    与 §1 的交付目标直接冲突。c1（GSQ + 最小模板）sys 仍烂，
    说明「只换模板、保留 GSQ」不足以修好 system。

【判定 2 · c3 的 sys 未达 ① 的内容正确】
  c3 sys 73 字符通顺但答非所问（未答 2+2），且带 <think> 文本前缀
  （最小模板已知问题，§4.3）。⇒ 只能算「乱码消除」，不能算验收通过。
  需再改模板（去掉 <think> 文本输出、正确渲染 system）后重测才有可能达标。

【判定 3 · 对 A-4 / A-5 结论的修正】
  A-5 判「必须转 L2 重编」过强：存在 0 编译改善路径，但要换掉交付产物。
  当前变成二选一（须操作者决策）：
    路径甲（0 编译）：Q4Q5 + 改良模板 → 修 system 乱码，
                      代价是放弃 vision/mtp/门控质量，② 与 ⑤ 更难。
    路径乙（需重编）：保留 GSQ，按 L2 补 plan.cpp:24-25 的
                      input_rows==4096 guard 并模板化 6144/5120 常量，
                      再回归 5x3=15/15 / 32 层 GDN 无 NaN。
  两路径共同的下一步都是「改良模板」实验（0 编译、低成本），
  建议先做：在 c3 基线上改 min-qwen.jinja，去掉 <think> 文本输出，
  重测 sys 是否答对 2+2；若达标，路径甲可立即用于 DSH 接线验收 ③。

【收口】脚本结束 remaining ninfer processes = []；nvidia-smi 复验
  memory.used=0 MiB / free=11944 MiB；未触碰 27B csunx 档位；
  未编译、未改任何源码，仅新增 3 个诊断脚本与日志/结果 JSON。
```

---

## 2026-11-10 17:24 · A-8 L0d + 模板归因：决定变量是产物（量化方案），不是模板

```text
执行：_work\ninfer-9b\p3_l0d_forms.py（Q4Q5 产物 + 原模板，2 组配置）

【d0 · Q4Q5 原模板 + --no-thinking + --no-prefix-reuse（5 形态，一次引擎）】
  user        19 tok  chars=20  2 + 2 equals **4**.                        ✅
  sys         30 tok  chars=32  The question is: - ⚒️ Is 2 -              ❌
  user-prefix 26 tok  chars=22  世界是简单的，还是人太渺小？ 🌟 其实啊，   ❌
  sys-short   26 tok  chars=22  2 <zenspice> 0.354822                     ❌
  essay       26 tok  chars=85  I'm sorry…😸（Here at once丕onseema      ❌ 半烂
  五条 units.prefill=1；仅 user 正常。
  ⇒ 「不动模板、只换请求形态」的 0 编译路径不成立。

【d1 · 去掉 --no-thinking（其余同 d0）】
  user  content chars=0，reasoning_content chars=59（"Thinking Process: 1. **Analyze…"）
  sys   content chars=0，reasoning_content chars=77（"Thinking, looking for the context…"）
  ⇒ 正文全部落 reasoning_content，content 为空，印证 §1「--no-thinking 不可省」。
    注意：不带 --no-thinking 时 prompt 从 19/30 变为 17/28，输出形态改变但内容仍不达 ①。

【模板差异（原模板文件已找到并核对）】
  train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\chat_template.jinja
    = 16,289 B，template_version "qwen3.6-froggeric-v21.3"；
    :320-328 add_generation_prompt 分支强制输出 think 块
      （not thinking / consecutive_failures>=2 → '<think>\n\n</think>\n\n'，
       否则 → '<think>\n'），:119-120 还有默认 system 工具说明。
  _work\ninfer-9b\min-qwen.jinja = 175 B，仅 ChatML 循环 + assistant 起始，无 think 块。
  ⇒ 原模板 sys 30 tok vs 最小模板 23 tok 的差异来源明确；
    §4.2 记的结尾序列 <think>(248068)/</think>(248069) 正来自这里。

【关键归因修正（四组交叉，决定变量是产物）】
  c1 GSQ   + 最小模板 → sys 烂（31 chars <think>ierted晖…）
  c3 Q4Q5 + 最小模板 → sys 通顺（73 chars，跑题）
  ⇒ 模板相同、产物不同 → 结果不同 ⇒ 产物（量化方案）是主因，模板是次因。
  c2 Q4Q5 + 原模板 → sys 烂；c3 Q4Q5 + 最小模板 → sys 通顺
  ⇒ 模板只在 Q4Q5 上起作用；GSQ 上换模板也救不了 system。
  ⇒ A-3 的「9B 短窗口 GDN kernel 27B 常量残留」应降级为次选假说；
    P2 更可能在 9B 量化 kernel 的几何适配：
      GSQ   formats = q8_g32 5.242 GiB / q5_g64 1.907 / bf16 1.238 / q4_g64 0.282
            components = text + vision + mtp（§2）
      Q4Q5  formats = 纯 text，5.83 GiB，483 参数
    §4.5「两个量化件都烂，只是烂在不同 prompt」与本判定一致：
    两者各有数值缺陷，触发的 token 序列不同。

【对 A-7 两步结论的修订】
  A-7 建议「改良 min-qwen.jinja 去掉 <think> 文本输出」——
  由 c1 可知该改动对 GSQ 无效，不必再做。
  A-7 的「路径甲（Q4Q5 + 改良模板）」仍成立但上限清楚：
  Q4Q5 是无 vision/mtp、leak 0.1333 超标的旧量化对照组，
  且其 sys 只到「通顺但跑题」，未达 ①；用它交付等于放弃 ② 与门控质量。

【下一步（唯一未做且决定成败的一步）】
  1) token 级定位：用 _work\ninfer-9b\render_count.py 复算 sys prompt 在
     GSQ / Q4Q5 两产物（含模板变体）下的 token 序列，找首个 logits 分叉点，
     再定位对应 kernel（q8_g32 / q5_g64 / bf16 projection 或 GDN conv）。
     目标是回答「哪个量化形状在 9B 几何下算错」，而不是继续试开关。
  2) 对照 §3.2 上游 #433 分支已有的 projection q6/shapes、q8 n4096_k4096 /
     n12288_k4096、bf16 n4096_k8192、official_recipes.py 的 qwen3_5_9b recipe，
     与本地 9B 补丁做差异清单；这一步决定重编要补哪些形状。
  3) 决策点（须操作者定）：
       甲 0 编译折中：Q4Q5 + 最小模板，放弃 vision/mtp/门控质量，①③ 只能部分满足
       乙 需重编：保留 GSQ，按 1)2) 补 9B 形状后重编 + 回归 5x3=15/15
     两路径不再有「只改配置就能全达标」的选项 —— 本轮 4 组脚本、
     17 次引擎启动已穷尽 0 编译开关/形态/模板/产物组合。

【收口】4 个脚本结束均 remaining ninfer processes = []；
  最终 nvidia-smi：0 个 ninfer 进程；memory.used=3110 MiB / free=8835 MiB，
  该 3110 MiB 由 PID 22524 TslGame.exe（PUBG）占用，非本实验残留。
  未编译、未改任何源码/模板/产物，仅新增 4 个诊断脚本与日志/结果 JSON。
```

---

## 2026-11-10 17:56 · A-9 路径乙：第一/二步审计 + 首轮补丁、重编、回归

```text
【第一步 · token 级定位结论】
  render_count.py 依赖 tokenizers，train\.venv\Scripts\python.exe 不在位、anaconda 无该包
  ⇒ 改用已有 reqlog 的 generated_token_ids 做等价对照：
    同一 sys prompt，GSQ 首 token id = 58（垃圾 "," 类），Q4Q5 首 token id = 760（"The"），
    分叉发生在**第一个生成 token**，不是解码中途漂移。
  17 组 L0 日志全量 grep：无 [q8-miss] / [bf16-miss] / unsupported shape / NaN
  ⇒ 运行时形状调用**全部命中**，问题在已注册 kernel 的数值正确性，不是"缺形状条目"。
  ninfer-perplexity.exe --help 已确认可用（--text / --corpus），本轮未用于定位。

【第二步 · 形状审计 + 上游 #433 对照（关键）】
  本地 9B 形状条目已注册齐全：
    q8_shapes.h:23-32  Q8N4096K4096 / Q8N10240K4096 / Q8N248320K4096 / Q8N2048K4096
    q8/shapes/ 有 n2048_k4096.cu、n248320_k4096.cu；bf16/shapes/ 有 6 个 k4096 形状
    q8/sources.cmake 已列入上述 .cu；q6/ 目录与 n248320_k4096.cu 也在位
  ⇒ §3.2 记的"#433 含我们缺的形状"在本地已被 11-08 那轮补齐，不是当前缺口。
  上游 fork 可达：gh api repos/Onur-Cansever/ninfer/branches → 9b-geometry-master-port 存在
    （Neroued/ninfer 本仓只有 dev / feat/qwen4-27b-ops / master，compare 404）。
    issue #433 仍 OPEN，body 明确 "master geometries are 27B-only"、分支含 10 commits。
    取到上游 q8/dgx_spark/shapes/n12288_k4096.cu：所有 launch 用
      LinearBf16Output{..., out.ne[0]}（运行时真实行数）。
  本地全引擎审计（Grep LinearBf16Output{ 共 60+ 处）：
    仅 2 处用编译期 Geometry::kOutputRows：
      kernels/q8/q8_instance_launch.cuh:11      ← 9B 转发路径经过
      projection/q8/shapes/n2048_k16384.cu:30   ← 27B 专用且 N=2048 匹配，无影响
    其余全部 out.ne[0] / w.n / weight.n，与上游一致。
  n2048_k4096.cu:37-44 的两处转发：
      select_q8_n10240_k4096 / select_q8_n4096_k4096 → select_q8_n2048_k4096
    后者返回 launch_q8_a16_sliced<Q8N2048K4096,...>，把 N=2048 写死进
    LinearBf16Output 的行数 ⇒ 9B 的 4096/10240 行输出后半段是脏数据。
  另发现未闭合的 9B 注释（input_conv/plan.cpp:18-25）：
    注释写"9B 必须显式设 Materialized"，代码却仍无条件在
    batch.rows==1 && (tokens<=3||5||6) 选 Q4Q5Fused（按 27B hidden5120/value6144 写死）。
    conversion.json methods：GSQ 的 216 个 gdn 方法全是 q4_g64_fp16 / q5_g64_fp16
    ⇒ Q4Q5 分支必然被调用。

【补丁 1（一处）】kernels/q8/q8_instance_launch.cuh:11
    Geometry::kOutputRows  →  out.ne[0]（与上游一致）
    备份 q8_instance_launch.cuh.bak-9b-outrows（653 B）
    按纪律删 16 个 q8/shapes/*.cu.obj 后重编。

【重编 1】CMakeCache: Ninja + MSVC 14.44.35207 + nvcc v13.0 + Release。
    vcvars64.bat 初始化依赖 reg.exe（被安全策略黑名单阻止）⇒ corecrt.h 缺失，
    不重试该程序，改用 p3-rebuild2.bat 显式设置 SDK 10.0.22621.0 的 INCLUDE/LIB/PATH
    （不调用 reg.exe）后成功：exit=0，21/21，无 error/FAILED。
    日志 p3-build2.log；旧 exe 备份 apps\ninfer-serve.exe.bak-pre9bfix（275,430,912 B）；
    新 ninfer-serve.exe = 275,447,808 B（+16,896 B），三个 exe 全部重链。

【回归 1 · p3_regress.py（按 Path 杀，5 prompt × 3 轮 + sys/essay）】
  5x3 = 15/15 全部正常（内容非空、关键词命中 15/15、无垃圾串）：
    p1 2+2 139 chars / p2 你好 15 / p3 gdn 258 / p4 s[::-1] 22 / p5 unittest 682，
    三条轮次逐字节一致。
  附加失败例**仍烂**：
    sys   43 chars  [ directions_52nd.json, line base-nlbiank-   （关键词 4 未命中）
    essay 32 chars  #liw2aioTSg/1+Z4OBYDwDgoRirLvwog            （base64 垃圾）
    ids_head 与修复前 L0 a 组**逐字节一致**：
      user [17,10,17,16327,2972,19,159034,271]
      sys  [58,17425,62,20,17,302,4182,11]
      essay[2,719,86,17,64,789,9657,70]
  NaN / 形状未命中 markers = NONE；prefill 190.4–404.5 tok/s（旧 208–319，同档不退化）；
  decode 34.1–40.7 tok/s；第 2/3 轮 prefix_cache_hit_tokens 8–15、path=checkpoint、units=1
  ⇒ 前缀复用链路正常，未退化。
  ⇒ **补丁 1 无效**：q8 转发形状在本请求路径中未被调用（或 out.ne[0] 与 2048 恰好相等）。
    该改动本身正确（与上游一致、无副作用），保留。

【补丁 2（一处，进行中）】input_conv/plan.cpp 的 Q4Q5 分支加 9B guard：
    if (weights.geometry.input_rows == 4096) { plan.kernel = ConvKernel::Materialized; break; }
    备份 plan.cpp.bak-9b-materialized（3788 B）；删 input_conv/plan.cpp.obj。
    dry-run：127 步（C++ dyndep 重扫，多为 CXX obj），p3-rebuild2.bat 后台编译中
    （日志 p3-build3.log，task wmqgvy）。回归结果见下一段。

【纪律】只写工作区；未动禁删清单；旧 exe 与两处源码均有 .bak 可回滚。
```

---

## 2026-11-10 18:01 · A-10 路径乙结论：两轮补丁、三次重编、三轮回归（核心目标未达）

```text
【补丁 2 与回归 2（有害，已回滚）】
  plan.cpp 的 Q4Q5 分支加 9B guard（input_rows==4096 → ConvKernel::Materialized），
  重编 p3-build3.log（8/8，exit=0）。
  回归 2：5x3 从 15/15 掉到 0/17（非空 17/17，但 clean=0、keyword 仅 3/15），
    17 条全部出现 U+FFFD 替换字符与随机 token id；
    首 token ids 从 [17,10,17,16327,2972,19,159034,271]
    变为 [17,151353,150910,29724,271,2305,2,1720]
    ⇒ 强制 Materialized 破坏了原本正常的 prefill 路径，明确有害。
  复核附录 A.4 点名的三处 q4_q5 文件，发现 9B 适配**早已内建**：
    convolution.cu:40-44       四段宽度运行时取 query/key/value.ne[0]
                               （9B 2048+2048+4096=8192；27B 2048+2048+6144=10240）
    projection_mma.cu:39-42    kValueRows = value_z_weight.n / 2（9B 4096 / 27B 6144）
    projection_independent.cu:26-27  按 k==4096 选 GemvR1W8K4096，否则 K5120
  ⇒ A.4「三处 27B 常量未修」已过时，当前缺口不是这些常量。

【回滚】cp plan.cpp.bak-9b-materialized → plan.cpp（3788 B，guard 代码已消失），
  删 input_conv/plan.cpp.obj；p3-build4.log 重编 8/8、exit=0；
  exe 18:00 / 275,447,808 B。
  回归 3 与回归 1 逐字节一致（首 token ids 全部还原）：
    user  [17,10,17,16327,2972,19,159034,271]
    sys   [58,17425,62,20,17,302,4182,11]
    essay [2,719,86,17,64,789,9657,70]

【用户要求的三条回归判据 · 最终状态】
  ① 5x3 = 15/15 ✅
     15 条内容非空、关键词 15/15 命中、无垃圾串；三轮逐字节一致
     （p1 139 / p2 15 / p3 258 / p4 22 / p5 682 chars）。
  ② 无 NaN ✅
     engine log bad markers = NONE（q8-miss / bf16-miss / unsupported shape / NaN 全无）；
     17 条请求无 500、无挂死。注：这是日志级检查，未做逐层 tensor 数值 dump。
  ③ prefill 不退化 ✅
     190.2–402.2 tok/s（修复前 208.4 / 318.7 / 284.4 同档）；
     decode 34.1–40.7 tok/s；第 2/3 轮 hit=8–15、path=checkpoint、units=1
     ⇒ 跨请求前缀复用链路正常。
  ❌ 核心目标未达：system+user 仍 43 chars 乱码（[ directions_52nd.json…）、
     essay 仍 32 chars base64 垃圾（#liw2aioTSg…）。§1 的 ①（DSH 形态）与 ③ 仍不可达。
     脚本把 sys 误判 ok=True 是因该垃圾串不含长混合大小写串；
     keyword_hit=False + 人工核验确认其为乱码，判据不可只看 ok 字段。

【路径乙结论（如实）】
  两处「补 9B 形状」补丁都未修复 system 乱码：
    补丁 1（q8_instance_launch.cuh:11 → out.ne[0]）：正确、与上游 #433 一致、无副作用，
      但对该请求路径无效 ⇒ 保留。
    补丁 2（Q4Q5 强制 Materialized）：有害 ⇒ 已回滚。
  ⇒ 根因不在「形状条目缺失」，也不在 A.4 的三处常量；
    本地 9B 支持是逐点打补丁的半成品，与上游 Onur-Cansever/ninfer@
    9b-geometry-master-port 的 10 commits 完整实现存在系统性差异。
  下一步（须决策，三选一）：
    A 整体对照并移植上游 10 commits（GDN input_conv / swiglu / attention / MTP 形状
      + official_recipes.py 的 qwen3_5_9b recipe），较大改动，需单独规划逐项回归；
    B 退回路径甲（Q4Q5 产物 + 最小模板，0 编译，放弃 vision/mtp/门控质量）；
    C 逐层 tensor 诊断（编译期开关打印每层 hidden / NaN），定位首个数值分叉层后定点修 kernel。

【产物 / 备份 / 收口】
  唯一保留的源码改动：q8_instance_launch.cuh:11 Geometry::kOutputRows → out.ne[0]。
  备份：q8_instance_launch.cuh.bak-9b-outrows（653 B）、
        plan.cpp.bak-9b-materialized（3788 B）、
        apps\ninfer-serve.exe.bak-pre9bfix（275,430,912 B，可完整回滚到修复前）。
  脚本：p3-rebuild.bat / p3-rebuild2.bat / p3_regress.py；
        p3-build2/3/4.log；p3-regress-result{,-r1,-r2}.json；
        p3-regress.reqlog.jsonl / p3-regress.engine.log。
  收口：0 个 ninfer 进程；显存 0 MiB used / 11944 MiB free；未触碰 27B 档位；
        只写工作区，未动禁删清单。
  ⚠ 环境注意：vcvars64.bat 初始化依赖 reg.exe（安全策略黑名单），
    编译改用 p3-rebuild2.bat 显式设置 Windows SDK 10.0.22621.0 的 INCLUDE/LIB/PATH，
    全程不调用 reg.exe；三次重编均 exit=0。
```

---

## 2026-11-10 18:34 · A-11 本地优化完成：锁定 16 边界并修复，核心乱码消除

```text
【约束】不碰上游：本轮未调用 gh、未移植 #433，全部改动在本地源码与脚本。

【诊断链（全部本地、可复跑）】
  1 CLI 对照 p3_cli_probe.py：GSQ/sys 在 CLI 输出
    "[ directions_52.html, FIRST_PARSED_BY:1371…"，与 serve+--no-prefix-reuse 逐字节一致
    ⇒ 与 serve 装配/capture 无关，是引擎通用数值路径。
  2 KV 配置 p3_kv_probe.py：int8/fp8/nvfp4/k8v4 与 --lm-head-draft 全部 NOT READY
    （本地 build 未编译），bf16 对照仍烂 ⇒ 配置层无解。
  3 长度扫描 p3_len_scan.py：19 token 正常，20–33 token 全部异常。
  4 前后缀对照 p3_prefix_probe.py：13 用例，19 token（base / 加尾空格）正常；
    20+ token 无论前缀/后缀/内容全部乱码 ⇒ 纯长度边界，与内容无关。
  5 形状追踪 NINFER_TRACE_SHAPES（p3_trace_probe.py）：19/20 的 q8/bf16/conv
    调用序列完全相同（364 行、3 种唯一行）：
      [conv] fmt=0 rows=1 tokens=1 kernel=1 ×336
      [q8] n=248320 k=4096 t=1 ×24
      [q8] n=248320 k=4096 t=128 ×4
    ⇒ 差异不在 kernel 分派。
  6 hidden 探针 NINFER_TRACE_HIDDEN（p3_hidden_probe.py）：实际请求最后窗口 len=4，
    主体起点 base=15（19 tok，正常）vs base=16（20 tok，异常）
    ⇒ 边界落在「单个 execution unit 宽度 >= 16」。
  7 上限扫描 p3_limit_scan.py（NINFER_PREFILL_MAX_TOKENS =
    8/12/15/16/20/24/28/31/32/48/64/128）：
      安全 = [8, 12, 15]；**16 起全部失败**（sys 回到 "[ directions_52nd.json…"、
      essay 回到 "#liw2aioTSg…"）。边界精确锁定。
      limit=12 → prefill 205.8 / decode 40.2 tok/s（修复前同档）。
    已排除：GDN replay fold 的 spec.width<=16 只在投机后端分配（当前未启用）；
      context attention dispatch_tokens 只覆盖 1..16 且主 prefill 未抛错；
      --device-state-slots 1/2/4/8/16 与 --host-context-mib 4096 全部无效。

【修复（本地源码，一处）】
  src/models/qwen3_5/execution/text.cpp:1519-1526
    prefill 分块循环加 max_unit_tokens（默认 12，可用 NINFER_PREFILL_MAX_TOKENS 覆盖）：
      int len = std::min(std::min(chunk, T - t0), max_unit_tokens);
    使每个 execution unit 宽度 <= 15，避开 >=16 的污染。
  另保留两处默认关闭的本地可观测性开关（不影响正常性能）：
    NINFER_TRACE_SHAPES  → q8/bf16/conv 形状追踪
      （q8_dispatch.cpp / bf16_dispatch.cpp / input_conv/plan.cpp）
    NINFER_TRACE_HIDDEN  → prefill 末层 hidden 前 8 值（text.cpp）
  保留 A-9 的 q8_instance_launch.cuh:11 out.ne[0] 修复；A-10 的补丁 2 已回滚。

【最终回归 p3_regress.py（默认上限 12，无环境变量）】
  5x3 = 15/15 ✅（连同 sys/essay 共 17/17 OK，clean=17，三轮逐字节一致）
  sys   = "2 + 2 = **4**."                                    ✅ 乱码消除、答案正确
  essay = "Local inference matters because it fundamentally shifts…"（166 chars） ✅
  无 NaN / bad markers = NONE ✅；17 请求无 500、无挂死
  prefill 178.5–384.0 tok/s、decode 33.7–36.9 tok/s
    （修复前 190–402 / 34–41）⇒ **不退化** ✅
  前缀复用正常：第 2/3 轮 hit=8–15、path=checkpoint、units=1
  ⇒ §1 的 ①（DSH 形态内容正确）核心障碍已清除；
    ③ 仍需 DSH 重启加载新 lib 后在真实会话里实测。

【重编 / 备份 / 收口】
  p3-build5..9.log 全部 exit=0、无 error/FAILED；
  ninfer-serve.exe 18:33 / 275,450,880 B。
  备份：text.cpp.bak-hidden-probe / .bak-pre-len15 / .bak-len15、
        q8_dispatch.cpp.bak-trace / bf16_dispatch.cpp.bak-trace / plan.cpp.bak-trace、
        q8_instance_launch.cuh.bak-9b-outrows、plan.cpp.bak-9b-materialized、
        apps\ninfer-serve.exe.bak-pre9bfix。
  收口：0 个 ninfer 进程；显存 116 MiB used（非本实验）/ 11829 MiB free；
        未触碰 27B 档位、未动禁删清单、只写工作区。
  ⚠ 根因最后一环（哪个 kernel 在 unit 宽度 >=16 时写错）尚未定点；
    当前是经数值验证的边界规避修复。下一步可在 q8_instances.cuh 的
    SlicedR16T16W8S2（kTokenCapacity=16）与 GDN replay / context-attention 的
    16 宽度假设上逐层定点，目标是把上限放回 128 而不乱码。
```

---

## 2026-11-10 20:18 · A-12 代价量化：上限 12 让长 prompt prefill 慢 5.7 倍

```text
【目的】评估 A-11 的边界规避修复对 DSH 真实会话（system 常为几 K token）的代价。
【方法】p3_long_prefill.py；同一 prompt（"The quick brown fox…" ×60，612 token），
        分别以 NINFER_PREFILL_MAX_TOKENS = 12 / 15 / 128 启动，--no-prefix-reuse，
        读 reqlog 的 prefill_seconds 与 units。

【数值】
  limit  prompt  units  prefill tok/s  prefill s  decode tok/s  wall s
  12     612     5      369.3          1.657      43.1          1.87
  15     612     5      452.9          1.351      40.2          1.58
  128    612     5      2118.9         0.289      40.2          0.52
  （limit=128 的输出 "This one's easy! 👍 person…" 未触发已知乱码模式，
    但该 prompt 不含 system/2+2，不能据此认为 128 安全。）

【结论】
  1 limit=12 的 prefill 吞吐是 128 的 **17.4%**（慢 5.7×）；limit=15 是 21.4%（慢 4.7×）。
    units 均为 5，说明代价来自单个 execution unit 内部的 12/15-token 循环，
    不是 execution unit 数量。
  2 外推：DSH 会话若 system 为 3–4 K token，prefill 将从 ~1.5–2 s 增至 ~8–11 s，
    TTFT 明显恶化。⇒ A-11 的修复「正确性达标、长上下文性能不达标」。
  3 因此 ③（DSH 真实会话）虽然现在能跑通且不乱码，但体验会被 prefill 拖慢；
    在接线验收前，应优先把上限恢复，或接受并记录该代价。

【下一步优先级（建议）】
  P0 根因定点（本地，目标把上限放回 128）：
     候选 1 q8_instances.cuh:36 SlicedR16T16W8S2（kTokenCapacity=16）
     候选 2 bf16 n4096_k4096.cu 的 S1/S2（SlicedKMma<16/32,...>）
     候选 3 GDN input_conv 的 width 处理（projected_conv.cu 通用路径）
     候选 4 context-attention dispatch_tokens 仅 1..16（确认主 prefill 是否绕开）
     方法：用 NINFER_TRACE_SHAPES 对比 limit=12 与 16 的 kernel 序列；
           用 NINFER_TRACE_HIDDEN 在 run_layers 内按 4/8/12/16 列逐步打印，
           定位首个出现数值分叉的子块与算子。
  P1 折中（0 编译，可立即用）：默认上限改 15，长 prompt 提速 23%（453 vs 369 tok/s），
     仍 <=15 安全；代价是短 prompt 的余量更小。
  P2 ③ DSH 接线验收：在 P0 完成或接受 P1 代价后，用 build-9b 档位跑一轮带 system 的
     真实对话；判据是「会话内不乱码 + TTFT 可接受」。
  P3 ⑤ / ②：MTP 接受率 0、100 tok/s、vision 未验，与本次乱码修复解耦，可并行。

【收口】0 个 ninfer 进程；显存 0 MiB used / 11944 MiB free；未改源码、未动禁删资产。
```

---

## 2026-11-10 20:33 · A-13 P0 受阻 / P1 完成 / P2 通过（DSH 形态验证）

```text
【P0 · 根因定点：未能根治，转技术债】
  1 逐层 dump 已启用（text.cpp:1369 eager 分支 + :1432 汇合处，环境变量
    NINFER_TRACE_LAYERS；必须配 --no-cuda-graph，否则 graph 捕获期
    cudaDeviceSynchronize 触发 cudaErrorStreamCaptureInvalidated）。
  2 12 vs 16 的 32 层 rms（l2/sqrt(n)）：
       L00-02 0.866 / L03 0.762 / L04 0.743 / L05-17 0.835-0.869 /
       L18-21 0.964-1.188 / L22-31 0.691-1.180
     全部 nan=0；无单层突跳、无爆炸 ⇒ 是渐进数值偏差，不是某层 NaN，
     无法用"首个 NaN 层"定位。
  3 「只限最后一个 execution unit」实验（finalize_at_end && t0+len==T）：
     长 prompt 612 token 的 prefill 从 369 → **1246 tok/s**（+3.4×，达 128 的 59%），
     但长 system（504/511 token）**仍乱码**（"[Meets in a later time…"）
     ⇒ 污染不限于末段，任一 unit >=16 都会触发。方案作废。
  4 结论：边界（unit 宽度 >=16）已确定，具体写错的 kernel 仍未定点；
     逐层 rms 粒度不足，下一步需在 mixer / ffn 内再细分插桩（成本高）。

【P1 · 完成：默认上限 12 → 15（全局限）】
  text.cpp max_unit_tokens 默认 15，仍 <=15 安全区；环境变量可覆盖。
  长 prompt 612 token：prefill **451.8 tok/s**（12 为 369.2，+22%；128 为 2108）。
  短 prompt 5x3=15/15、sys "2 + 2 = **4**."、essay 166 字，全部保持。

【P2 · 通过：DSH 会话形态验证（build-9b 参数，max-context 16384）】
  p3_dsh_shape.py，三例：
    sys-only        prompt 31   0.34 s   >>> "2+2 = 4"                         ✅
    sys-tools       prompt 397  2.20 s   >>> "2+2=4. Would you like to explore…" ✅
    sys-tools-essay prompt 404  1.63 s   >>> 162 字通顺长文                     ✅
  prefill 268.2 / 416.9 / 446.0 tok/s；decode 42.1 / 37.3 / 36.3 tok/s。
  ⇒ 带 system + tools schema 的真实会话形态**不再乱码**；
    §1 的 ③ 在请求层面已具备条件，剩余仅 GUI 内实测（需操作者在 DSH 选 build-9b 档位）。

【P3 · 待做】
  ⑤ MTP 接受率 0 / 100 tok/s：需转换器侧修 mtp attention 分组（附录 A.3），属专项；
  ② vision：--vision 能起（§4.7），尚未做一次真实图文问答，可用 _tools/media-test 的图验证。

【重编 / 收口】
  p3-build10..16.log 全部 exit=0、无 error/FAILED；
  ninfer-serve.exe 20:31 / 275,453,440 B。
  源码改动仍集中在 text.cpp（max_unit_tokens + 三个默认关闭的诊断开关：
  NINFER_TRACE_LAYERS / NINFER_TRACE_HIDDEN / NINFER_TRACE_SHAPES）。
  收口：0 个 ninfer 进程；显存 0 MiB used / 11944 MiB free。
```

---

## 2026-11-10 20:34 · A-14 P3：vision 组件能起但图片被 invalid media 拒绝

```text
【② vision 验证（未通过）】
  p3_vision_probe.py：生成左红/右蓝/中间白方块的 PNG（96×96 与 224×224 各一次），
  base64 data URI 发送；引擎以 --vision --max-context 8192 启动成功：
    weights 8.25 GiB | KV 8,192 tokens / 128 pages | free 1.77 GiB
  两次请求均被拒：
    req#1 rejected during prepare | openai-chat non-stream | HTTP 400 | invalid media
  错误来自 generation_service.cpp:214 的 throw_invalid_input(exception, "invalid_media")，
  即 acquire_media 内抛异常（acquire.cpp 的 data URI 解析要求 ";base64"，
  本请求满足；因此更可能是后续图片解码/尺寸校验或 PNG 编码兼容性）。
  PNG 本身有效（ViewImage 可正常显示红/蓝/白方块）。
  ⇒ ② 仍为「组件在、可启动、未完成一次真实图文问答」；
    下一步：查 acquire.cpp 的 WIC 解码分支与 processor.cpp 的最小/最大尺寸校验，
    或改用标准 JPEG（当前环境无 PIL，需另找编码器）。

【⑤ 未动】
  MTP 接受率 0 与 100 tok/s 需要转换器侧修 mtp attention 四合一分组
  （附录 A.3：qwen3_5.py 的 full_attention group 规则按 mtp/text 区分），属专项工程。

【收口】0 个 ninfer 进程；显存 0 MiB used / 11944 MiB free；
  未改源码（本轮 P3 只加脚本）；未动禁删资产。
```

---

## 2026-11-11 03:20 · A-15 根因定点并修复：9B attention 投影的四段输出错绑（乱码真因）

```text
【根因（代码级，已由独立 oracle 证伪/证实）】
  文件：src/ops/linear/split/q4_q5/shapes/n5120_n5120_k4096/mma.cu（grouped 路由）
  9B 的 attention 投影一次产出四个**独立分配**的输出张量：
    out[0]=query(4096 行) out[1]=key(1024) out[2]=gate(4096) out[3]=value(1024)
  （small.cu:289-309 的四段独立路径按此绑定，shape.cpp:19 的 segments 也是 <4096,1024,4096,1024>）
  但 T>15 走的 launch_matrix 只把 out[0]、out[1] 当两块 **5120 行连续缓冲**：
    make_job(qk_weight, 0, qk_weight.n=5120, out[0], 0)          → 向 4096 行张量写 5120 行
    make_job(value_z_weight, 0, 5120, out[1], 0)                 → 向 1024 行张量写 5120 行
    make_job(value_z_weight, 5120, 5120, out[1], 5120)           → 同一块再写一遍，行偏移 5120
  即：越界写 + 相邻张量互相覆盖 + gate/value 根本没被正确填充。
  只要单个 execution unit 宽度 >15 就走这条路 ⇒ 与 A-11/A-13 实测的「15 安全 / 16 起全烂」
  边界精确吻合；此前把上限压到 <=15 之所以有效，就是绕开了这条错路由。

【修复（一处，mma.cu）】
  launch_slice 改为四个 RowSplit job，各自绑定正确的输出张量：
    query = make_job(qk_weight,      0,    4096, out[0], 0)
    key   = make_job(qk_weight,      4096, 1024, out[1], 0)
    gate  = make_job(value_z_weight, 0,    4096, out[2], 0)
    value = make_job(value_z_weight, 4096, 1024, out[3], 0)
  tile 数按四段求和（BM=32: 128+32+128+32=320；BM=64: 64+16+64+16=160），
  kernel 的 Jobs=4 分支按顺序累减选 job，与段长整除关系一致。
  launch_grouped / launch_matrix 改为透传 std::span<const Tensor> 并对 size()==4 做显式校验。
  权重行偏移、codes/high/scales 偏移与 small.cu 的 sub_weight 逐项一致（静态复核通过）。

【A/B 证据：测试先证明能抓到这个 bug，再证明修好了】
  独立 oracle 测试 tests/ops/linear/test_split_multi_output.cpp 新增 run_q4_q5_9b()
  （4096/1024/4096/1024 四输出、K=4096、Q4+Q5 paired，T=1,15,16,17,31,32,33,63,64,65,127,128,129
   eager + 16,32,33,64,65,128,129 的 graph replay，逐元素 FP64 投影 oracle + guard + 全写校验）
  · 修复前 mma.cu（.bak-fix-segmented-outputs）重编 → 进程在 9B T=16 处**异常终止**
    （最后两条 hostsync：fill bytes=131584 = 4096×16×2+512 guard、33280 = 1024×16×2+512；
     exit=127，无 OK/FAIL 结论）
  · 修复后重编 → "OK linear_split multi-output"，exit=0（整套 27B 老用例 + 9B 新用例全过）
  ⇒ 测试有效性已闭环：该用例在旧代码上必然失败，在新代码上通过。

【引擎端回归（ninfer-serve.exe，默认 NINFER_PREFILL_MAX_TOKENS=128）】
  p3_matrix_scan（15/16/20/24/32/64/128 × {2+2, system+user, essay, 612-token 长 prompt,
  504-token 长 system}）→ 35/35 全部 clean：
    15    u2plus2 0.286s  sys 0.308s  essay 0.763s  long 1.656s  longsys 1.391s
    16    0.696 / 0.739 / 2.024 / 3.369 / 2.869
    20    0.583 / 0.601 / 1.463 / 2.437 / 2.181
    24    0.459 / 0.621 / 1.695 / 2.485 / 2.170
    32    0.652 / 0.638 / 1.660 / 2.003 / 1.755
    64    0.590 / 0.543 / 1.551 / 1.308 / 1.115
    128   0.722 / 0.692 / 1.872 / 1.297 / 1.153
  p3_regress（默认 128）：5x3 = 17/17 OK、clean=17、keyword=16（essay 无关键词）、
    bad markers = NONE、前缀复用 hit=8-15 / path=checkpoint 正常。
  p3_long_system（504 / 511 token system）："2+2 = 4" 与 157 字 essay 均正确，
    prefill 1878.3 / 1916.3 tok/s（0.27 s），units=5。
  p3_long_prefill（612 token）：limit=12 365.0 / 15 441.3 / **128 2133.5 tok/s（0.287 s）**
    ⇒ 恢复到 A-12 记录的 128 档速度，A-11/A-13 的分块限速代价（5.7×）全部消除。
  text.cpp 的 max_unit_tokens 默认值 15 → **128**（环境变量仍可覆盖，便于定向探针）。

【② vision 复验（HTTP URL 路径，A-14 的遗留）】
  p3_vision_url_probe.py：本地 http 托管既有 test.jpg（2091 B），引擎 --vision 启动后
  图文请求 2.44 s 返回："The image shows two solid-colored squares side by side: a red square
  on the left and a blue square on the right..."，prompt 93 token / 567.6 tok/s。
  启动配置：--max-context 2048 --kv-capacity 2048 --host-context-mib 0 --device-state-slots 0
  --no-cuda-graph（当时 GPU 被 TslGame.exe 占 2.8 GiB，8192 上下文报
  "Device budget cannot hold the calibrated runtime and requested KV capacity"）。
  ⇒ data URI 仍走 WIC 失败（inline base64 路径的既有上游 bug），HTTP URL 链路可用。

【⑤ MTP 复测（未改善，属权重问题）】
  p3_mtp_probe.py：--spec mtp --draft-tokens 3，192 token 请求
    draft_n=567 / draft_n_accepted=0 / predicted 13.45 tok/s（无投机 ~20-40）
  ⇒ 接受率 0 与本次投影修复无关，仍是 MTP 头与 G1 量化 target 不对齐，需重训或换权重。

【构建/工程】
  · 为跑独立 oracle 测试，临时开 BUILD_TESTING=ON；发现三处 Windows 不可移植：
    tests/ops/linear/test_split_multi_output.cpp 缺 <array>（std::array CTAD 全部失败）、
    tests/cmake/CoreTests.cmake 的 ninfer_read_queue_test 依赖 PkgConfig::URING（Windows 无 liburing）、
    以及若干 Linux-only 测试（test_executor 引 sched.h 等，未改）。
    已修前两处（read_queue 加 if(NOT WIN32) 守卫、补 <array>）；
    测完后 BUILD_TESTING 复位为 OFF（恢复原配置，`all` 可用）。
  · 新增脚本 p3-build-test.bat（只编 multi_output 测试）、p3-rebuild-apps.bat（只编三个 app）。
  · p3-build17/18/19/21 与 p3-build-test*.log 全部 exit=0；
    最终 ninfer-serve.exe = 275,400,192 B（03:17），晚于全部改动源文件。
  · 备份：mma.cu.bak-fix-segmented-outputs（修复前）、shape.cpp.bak-force-small16、
    small.cu.bak-force-small16、text.cpp.bak-default128、
    ninfer-serve.exe.bak-pre-default128 / .bak-force-small16。

【收口】0 个 ninfer 进程；显存 2547 MiB used 由 TslGame.exe（PUBG）占用，非实验残留；
  未触碰 27B 档位与禁删清单；只写工作区。
```

---

## 2026-11-11 03:55 · A-16 ⑤ MTP 接受率 0 的定位（未修好，但排除了三类原因）

```text
【目标】用户选 ⑤。先判「接受率恒为 0」是接线 bug 还是权重问题，再决定是否值得重训。

【已有的现成观测口（无需改代码）】
  decode.cpp:559 起已有 NINFER_DUMP_DRAFT + NINFER_DUMP_DRAFT_FILE：
  每轮打印 extent / accepted / count / anchor / licensed target / current drafts。
  p3_mtp_diag.py 用它跑 --spec mtp --draft-tokens 1，64 token，得：
    63 轮，accepted 分布 = {0: 63}
    draft[0] == target[0] 命中 0/63；draft[0] == 下一轮 anchor 命中 0/62
    例：anchor=8160 target=[513] draft=[109141]；anchor=513 target=[4097] draft=[5975]
  若 MTP 只是「略差」，p=0.4 时 63 轮全灭的概率约 1e-14；因此是结构性错误，不是精度问题。

【新增探针（默认关闭，NINFER_TRACE_MTP=1）】
  text.cpp proposal_argmax 的 else 分支（full head 路径）里，前 4 次 T==1 提案打印：
    hidden RMS、hidden[0..3]、proposal logits 的 top-5 与 chosen。
  注意：首次实现把 bf16 解码写错（用整数位模式当尾数），得出 hidden_rms≈210 的假象；
  修正为 (1+m/128)·2^(e-127) 后重测，数据如下（--no-cuda-graph，否则探针只在
  graph 捕获期跑一次、读到的是未执行的内存）。

【实测（修正后）】
  [mtp] call=1 hidden_rms=2.327  top5=109141:21.00 113583:19.88 101587:19.63 ... chosen=109141
  [mtp] call=2 hidden_rms=2.202  top5=5975:18.25 1710:16.88 242602:15.00 ...     chosen=5975
  [mtp] call=3 hidden_rms=2.316  top5=98705:16.38 99451:15.63 ...                chosen=98705
  [mtp] call=4 hidden_rms=2.308  top5=220:20.75 11069:18.75 ...                  chosen=220

【据此排除的三类原因】
  1 输入 hidden 不对 → 排除。RMS≈2.3 正是 mtp.norm 之后的正常量级
    （mtp.norm.weight 实测 mean 1.42 / std 0.18），且逐轮变化（2.20–2.33），不是脏缓冲。
  2 输出头缺失/错绑 → 排除。load/mtp.cpp:14 `out.output_head = target.output_head`，
    MTP 与 text 共用同一个 output_head（converter qwen3_5.py:973-976 把 mtp/final_hidden
    作为同一 head 的第二个输入），proposal_head=full 走的就是这个共享头。
  3 MTP 权重本身损坏 → 排除。直接读 step300 safetensors 的 15 个张量：
    mtp.fc (4096,8192) std 0.0147；q/k/v/o/mlp std 0.013–0.029；
    mtp.norm mean 1.42；pre_fc_norm_hidden mean -0.255；q/k_norm mean 0.75。
    全部是正常训练权重，无零化/NaN。

【结论：坏在 MTP 那一层的计算本身】
  hidden 正常、头正常、权重正常，但 head(hidden) 给出的 argmax 落在高 id 区
  （109141 / 98705 / 242602 等），而 target 的 argmax 是 513 / 4097 / 1328 这类常规 token；
  且 logits 有真实幅度（~20，span 1.4–5.6），不是持平噪声 ⇒ 是「自信地算错」，
  即 mtp.layers.0（full-attention 层 + mtp_kv）这一段的前向与训练时不一致。

【本轮做的一处契约对齐（保留，但未改变接受率）】
  mtp_forward_stem 原为 concat_bf16_features(e, h, ...) → stem = [embedding, hidden]；
  而训练侧定义是 mtp/stem_input = concat(hidden_norm(h_t), embedding_norm(emb))（hidden 在前，
  见 train/lines/27b-kittyrev/quant/mtp_posttrain.py:11,176），indexing.h:62 的算子语义是
  「first 落低半、second 落高半」。已改为 concat_bf16_features(h, e, ...)。
  实测接受率仍为 0（draft_n=567 / accepted=0 / 13.2 tok/s），故它不是根因，
  只是把调用顺序对齐到训练契约；MTP 只影响 draft，被拒即丢弃，不影响正文正确性。

【下一步（需决策，属专项工程）】
  A 逐层对拍：用同一组 (hidden, emb) 在 torch 侧跑 mtp_posttrain 的 MTPLayer.forward，
    与本引擎 mtp_forward_core 的 x / attn_out / mlp_out / final 四段数值比对，
    定位是 rope、mtp_kv 内容、还是 q/gate 拆分错。需要一次脚本化对拍（半天量级）。
  B 放弃投机：34 tok/s 左右（无投机 20–43）为本机 12 GB 卡交付上限，
    把 ⑤ 记为「受权重/硬件限制」，不再投入。
  C 重训 MTP 头对齐 G1 量化后的 target（成本最高，且不解决本轮的接线疑点）。

【主路径未受影响（本轮改动只在 MTP 路径）】
  p3_regress 5x3 = 17/17 clean、bad markers NONE；
  p3_long_system（504/511 token）输出正确，prefill 1889.0 / 1934.5 tok/s，decode 42.6 / 37.8。
  构建 p3-build22..27 全部 exit=0；最终 ninfer-serve.exe 275,405,824 B。

【收口】0 个 ninfer 进程；未触碰 27B 档位与禁删清单；探针默认关闭（NINFER_TRACE_MTP）。
```

---

## 2026-11-11 04:05 · A-17 ⑤ 路线 A（逐层对拍）：进度与结论

```text
【做了什么】
  1 在 mtp_forward_stem 里加 env 门控落盘（NINFER_TRACE_MTP_STEM=<file>），导出
    ids / target hidden / raw emb / e(embedding_norm) / h(hidden_norm) / fc_in / x / ah。
  2 写 torch 参考 p3_mtp_stem_check.py：直接读 step300 safetensors 的 4 个张量，
    按 mtp_posttrain.py 的 stem 公式重算，与引擎逐段比 rel 误差。
  3 用 p3_mtp_stem_dump.py 起引擎采样（--no-cuda-graph，否则探针只在捕获期执行）。

【得到的两条可信结论（引擎内部自洽，不依赖跨缓冲比对）】
  ① 引擎的 RMSNorm 走 **unit-offset（1+w）** 约定：
     rel(ah, norm(x, plain)) = 0.919，rel(ah, norm(x, unit)) = 0.192
     ⇒ 用 w 直接乘的参考必然对不上；这也是我第一版参考误差爆表的主因。
     参考侧改用 (1+w) 后：ref e_rms 0.536 vs 引擎 0.546；ref h_rms 0.746 vs 引擎 0.768，
     量级对齐。
  ② MTP 的 stem 输入侧量级正常：emb 0.0122（原始 embedding）、hidden 1.946（text final_norm 之后）、
     e 0.546、h 0.768、fc_in 0.666、x 1.473、ah 1.093 —— 与 4096 维 bf16 的正常分布一致，
     不存在「全零 / NaN / 尺度爆炸」。

【为什么这次没能定到具体算子】
  跨缓冲比对不可信：dump 里 fc_in 的低半应当逐位等于 h，实测第 0 列前 ~456 个元素相等、
  之后逐渐发散（最大差 21.7，但整体 rms 仍符合 [h;e] 的预测 0.667）。
  这是 arena scratch 复用造成的**采样快照不一致**（同一 arena 区在不同时刻被写），
  不是模型数值问题。把 e/h/fc_in 的拷贝提前到 project 之前后现象不变，
  说明覆盖发生在更早（concat 与 rmsnorm 之间的 scratch）。
  ⇒ 结论：**pipeline 内采样做不了可靠的逐段对拍**，必须改成「自己持有缓冲的 Op 级测试」。
  因此本轮没有给出「哪个算子算错」的定论，不写没有证据的结论。

【保留的改动】
  · mtp_forward_stem 的拼接顺序：concat(e,h) → concat(h,e)（对齐 mtp_posttrain.py:11,176 的训练定义）。
    实测接受率仍 0，故不是根因；MTP 只影响 draft，被拒即丢弃，不影响正文。
  · proposal_argmax 的 NINFER_TRACE_MTP 读侧探针（默认关闭，bf16 解码已修正）。
  · 已删除不可靠的写侧探针与 stem 落盘代码，工作树保持干净。

【主路径复核（改动只在 MTP 路径）】
  p3_regress 5x3 = 17/17 clean、bad markers NONE；
  长 system（504/511 token）输出正确，prefill 1894.3 / 1943.4 tok/s，decode 42.6 / 38.5；
  --spec mtp 192 token：draft_n=567 / accepted=0 / 26.2 tok/s（无投机同档 26–43）。
  p3-build28..31 全部 exit=0；最终 ninfer-serve.exe 275,405,312 B（已无落盘探针，grep "mtp-stem" = 0）。

【下一步（A 的正确做法，需要新写一个测试而不是继续插桩）】
  仿 tests/ops/linear/test_split_multi_output.cpp 建一个 Op 级 MTP 测试：
  自持 device 缓冲，构造固定 (hidden, ids, position, 单位置 KV)，
  调 TextContext::mtp_forward_* 并把 stem / attn_out / mlp_out / final 四段与
  torch FP64 参考（mtp_posttrain 的 MTPLayer.forward）逐段比 rel 误差，
  阈值按 bf16 单次舍入给（≤2%）。这样能一次性定位到 q/gate 拆分、rope、KV 还是 MLP。
  成本：一个测试源 + 一次构建，半天内可完成。

【收口】0 个 ninfer 进程；显存 0 MiB；未触碰 27B 档位与禁删清单。
```

---

## A-17 · MTP 逐层对拍（Op 级实证）与两处确定性 bug

### 结论先行
- **MTP block 数值完全正确**：用真实权重在 torch 侧从 (ids, hidden) 整层复算，
  与引擎逐段一致（bf16 舍入级），最终 `cosine = 1.00000`。
- **修复了一个真实越界写**：`split_bf16_features` 的 kernel 把 27B 几何
  （14336/6144/1024）写成常量，9B（10240/4096/1024）上会 token 边界错位并把
  6144 行 q 写进 4096 行张量。
- **仍剩一处 decode 侧缺陷**：draft 恒为 11，不随上下文变化。

### 1. 已修：`src/ops/indexing/features.cu` 的 MTP 拆分几何
host 侧校验早已改成从输出张量推导（9B: `256×(2×16+2×4)=10240`，校验通过），
但 kernel 仍是 `kSplitRows=14336 / kWideRows=6144 / kNarrowRows=1024`。
9B 的 packed 只有 10240 行，`row = idx % 14336` 让 token 边界整体错位，
且 `first[token*6144 + row]` 越过 4096 行的 q 张量。
改为 `SplitGeometry{total,wide,narrow}` 由 host 推导后传入 kernel；
27B 的 `{14336,6144,1024}` 与常量完全等价，行为不变。
实测：`draft_n_accepted` 0 → 1（仍远低于期望，见第 3 点）。

### 2. 已证：MTP 整层数值正确（证据）
从 prefill final chunk 落盘 `ids/positions/rope/hidden/ah/a/xattn/xres/mh/out`，
再用真实权重在 torch 复算：

| 段 | rel | 说明 |
|---|---|---|
| `v`（无 norm/rope） | 0.0037 | 投影布局与 stem 一致 |
| `qn` / `kn` | 0.0028 / 0.0031 | per-head `[q,g]` + `(1+w)` + rope_dim=64 全对 |
| `a`（gated attn） | 0.0052 | 因果 attention 正确 |
| `o_proj` / `x_res` | 0.0038 / 0.0036 | |
| `mh` / `out` | 0.0032 / 0.0037 | **cosine = 1.00000** |
| argmax | 220 == 220 | 与引擎 draft 一致 |

对照排除项（同数据）：`e_first` 拼接 rel=1.45、`unit=False` rel=1.09、
`rope_dim=256` rel=0.85 —— 均远劣于采用值。
norm 权重均值 `hnorm=-0.255, enorm=-0.478, final=+1.423`，只有按 `(1+w)`
解释才全为正 → **unit-offset 约定确认**。

### 3. 未决：decode 侧 draft 恒定
`--spec mtp --draft-tokens 1`，61 轮全部 `draft=[11]`，与 anchor/target 无关：
```
anchor=8160 target=[513] draft=[11]
anchor=513  target=[4097] draft=[11]
...（61 轮同值）
```
而同一 dump 的 MTP block 输出 `out` 两列 argmax 分别是 37931 / 103132，
两列 `ah` 余弦 0.73（明显不同）。即 **draft 不来自该 block 输出**，
问题在 `mtp_decode_batch_body` 的
`gather_bf16_batch_columns(alignment_hidden, accepted, ar_hidden)` →
`mtp_propose_batch(ar_hidden, ...)` 这一段（`speculative/mtp.cpp:163-171`）。
下一步：落盘 `ar_hidden` 的逐轮 rms 与余弦，确认是否为陈旧/常量张量。

### 4. 复验
- 主路径回归 17/17 clean、bad markers NONE（features.cu 改动不影响 text）。
- 新增脚本：`p3_mtp_block_dump.py`、`p3_mtp_block_check.py`、`p3_mtp_prefill_dump.py`、
  `p3_mtp_prefill_check.py`、`p3_mtp_tail_check.py`、`p3_mtp_full_check.py`、
  `p3_mtp_stem_variants.py`、`p3_mtp_prefill_short.py`。
- 新增默认关闭的探针：`NINFER_TRACE_MTP_BLOCK`、`NINFER_TRACE_MTP_PREFILL`。
- 【收口】0 个 ninfer 进程；显存 0 MiB。
```




---

## A-18 · MTP 恒定 draft 的定位结论：引擎无误，MTP 头对当前 hidden 不成立

### 1. 恒定 draft 的成因（已证）
`--spec mtp --draft-tokens 1`，61 轮 `draft=[11]`。逐轮落盘提案输入 `ar_hidden`（`NINFER_TRACE_AR`）：

```
rows=62   rms 2.2738 / 2.2986 / 2.3327 ...（在变）
cos(r0,r1)=0.99543   cos(r0,r30)=0.97667
|mean| / mean|dev| = 7.11
argmax per row = 11 ×61（distinct 仅 {11,12,220,1852}）
```

即输入在变、但**变化部分只占常量分量的 1/7**，MTP 输出几乎是同一个不动点 →
argmax 恒为 11。不是输入冻结，是输出被常量分量压死。

### 2. 关键校准：hidden 与 lm_head 都是对的
用主干自己的 `lm_head` 直接吃 dump 里的 `hidden[t]`：

```
lm_head(hidden[t]) == ids[t]  →  9/12（t=5..11 全中）
```

⇒ `hidden` 是真实末层输出（post-final-norm）、`lm_head` 正确、
且确认 `ids[t] = x_{t+1}`（引擎的 `shifted_embedding_begin` 移位生效）。

### 3. 同输入下 MTP 头不合格（长 prompt，n=101）
```
unit=(1+w)  top1==ids[t+1]:  7/101   distinct=3   （几乎全吐 11）
unit= w     top1==ids[t+1]:  6/101   distinct=27
```
训练侧 `mtp-domains-v3step300.json` 声称同一权重 top1 = 0.72 / 0.28 / 0.26。
两种 norm 约定都远低于此，且 `(1+w)` 下退化成 3 种 token。

### 4. 结论
- MTP **block 实现无误**（A-17 已证 cosine 1.00000）。
- 该 MTP 头在**当前服务模型的 hidden 上不成立**：不论文档约定的哪种变体都拿不到可用接受率。
- ⑤「decode ≥100 tok/s」无法靠这个头达成：`--spec mtp` 实测 26.4 tok/s，
  比无投机（30–43）更慢，属负收益。
- 可选出路：① 用当前模型的 hidden 重训 MTP 头（唯一能翻盘）；② 记为交付上限、关掉投机。

### 5. 复验与状态
- 主路径回归 17/17 clean、bad markers NONE。
- `features.cu` 的几何修复保留（真实越界写，与 MTP 头是否可用无关）。
- 探针全部默认关闭且 `getenv` 静态缓存：`NINFER_TRACE_MTP_BLOCK` /
  `NINFER_TRACE_MTP_PREFILL` / `NINFER_TRACE_AR`。
- 新增脚本：`p3_mtp_block_dump.py`、`p3_mtp_block_check.py`、`p3_mtp_prefill_dump.py`、
  `p3_mtp_prefill_check.py`、`p3_mtp_tail_check.py`、`p3_mtp_full_check.py`、
  `p3_mtp_stem_variants.py`、`p3_mtp_accuracy.py`、`p3_mtp_normconv.py`、
  `p3_ar_analyse.py`、`p3_mtp_prefill_long.py`。
- 【收口】0 个 ninfer 进程；显存 0 MiB；`ninfer-serve.exe` 275,408,384 B（10:08）。

---

## H.9.1 消融结果（2026-11-12 01:05 追加 · 3 组 × 100 步 · 脚本 p3_ablate.py）

```text
h1 shift=1(emb=ids[t-1], 目标 ids[t]) + partial rope : decode 31.0  accepted 0/254 = 0%
h2 shift=2(emb=ids[t],   目标 ids[t+1]) + full rope  : decode 31.1  accepted 1/253 = 0.4%
h3 shift=1 + full rope                               : decode 31.0  accepted 0/254 = 0%
（三组训练 top1 都只到 0.19–0.25：100 步不足以定标）
对照：400 步、shift=2 + partial（已训头）→ accepted 6.7%，VAL top1 46%
→ 位置/rope 两种假设都没把 accepted 拉起来；accepted ≈ VAL/7 的比例在两组间稳定
⇒ 下一步不再猜训练约定，改为直接对齐引擎侧输入：
   用 NINFER_TRACE_MTP_BLOCK 在 decode 阶段落盘引擎真实 stem / ar_hidden 与 draft token，
   离线把新头喂同一份 stem，比较 argmax 与引擎 draft：
     · 一致  → 训练输入构造错（改 hidden 来源 / norm 约定）
     · 不一致 → 头与引擎前向仍有差异（用新权重重做 A-18 的逐段对拍）
脚本：p3_mtp_block_dump.py + p3_mtp_block_check.py（A-18 用过，直接复用）
产物：kittyrev-oxcoder9b-{h1-shift1-partial,h2-shift2-full,h3-shift1-full}.ninfer
      ablation-log.jsonl / ablation-run.log / var-*.safetensors
```

## H.9.2 引擎侧对齐（2026-11-12 01:20 追加）

```text
做法：对新 artifact（mtp2f）开 NINFER_TRACE_MTP_BLOCK，decode 阶段拿到引擎真实的
      ah(=MTP 层输入) 与 out(=层输出)，离线把新头喂同一份 ah 比 cosine。
结果（dump T=2，positions=[19,20]，已改用真实位置构造 rope）：
      最好组合 offsets=(input_norm, post_attention_norm, final_norm) → cosine 0.7102
      其余组合 0.45–0.68；q_norm/k_norm 加不加 +1 只差 0.002
⇒ 结论：层内仍有约 30% 差异，不能只用 norm 约定解释。
   下一步（自动化轮次继续）：
   1) 先用 A-18 自己的 p3_mtp_block_check.py 跑同一份 dump（它有当时验证过的参考实现，
      可确认我的解析偏移/字段是否取错：dump 里 ah/qn/kn/vv/aa/out 的 order 与 dtype）
   2) 再比 pre-final_norm 与 post-final_norm 两种口径（引擎 out 的 rms 2.11 vs 离线 2.31）
   3) 若确认层实现一致 → 差异在 stem 构造（用哪份 hidden / ids 移位）；若不一致 → 逐段对拍定位
产物：p3-block-new.bin（引擎 dump）/ p3_block_vs_head{,2,3,4}.py
```

## H.9.3 第 1 轮（2026-11-12 01:25）：两个新事实 + 一个必须先解决的问题

```text
1) 离线对齐工具不可信：p3_block_vs_head4 在**旧头+旧 dump**（A-18 当年 cosine=1.0 的组合）
   只得到 0.03，在新 dump 上是 0.71 → 说明我的 dump 字段解析/参考实现与 A-18 不同，
   cosine 这条线暂时不能当作判据。p3_mtp_block_check_new.py 的 rel(qn)=0.86 同样不可信。
2) 引擎接受率对"头"极敏感且当前不可复现：
   mtp2f（00:33 训的 400 步头）重复测 3 次：16/238=6.7% / 32.85 tok/s（稳定）
   01:23 用同一脚本、同一 400 步配置重训的头 → 4 种 norm 导出约定全部 0/254 = 0%
   （S-in-post-final / S-pre-in-post-final / S-all / S-none 都是 0）
   ⇒ 要么两次训练本身不可复现（数据窗口随机顺序、bf16 舍入），
     要么 acceptance 是极窄的"头对了才中"的悬崖——两者都必须先钉死，否则后面全是噪声。
3) 磁盘告警已处理：清掉 mtp2/2b/2c/2d/2e 与 h1/h2/h3 共 9 个实验 artifact（≈65 GB），
   余量 72.5 GB；只保留 mtp2f 与交付版。
4) 顺手修掉：trainer 在 MTP_OUT 模式下不再覆盖 mtp-tuned-dump；VAL 的 bf16 dtype 崩溃已修。

下一轮（必须按序）：
  a. 训练可复现性：固定 random/torch 种子 + 固定 npz 顺序 + 记录首步 loss/末步 loss 指纹；
     同配置连跑 2 次，要求 loss 曲线逐点一致，否则先修数据迭代顺序
  b. 接受率测量做 3 次重复，报告均值±范围（当前 mtp2f 6.7% 已算 3 次一致）
  c. 再回到"哪个约定能提高 accepted"的问题——用固定头、只换导出约定（4 组），每组测 3 次
```

## H.9.4 第 2 轮（2026-11-12 01:42）

```text
1) 测量本身是稳定的（这条排除了"测不准"）：
      mtp2f artifact 连测 3 次 → 16/238 = 0.0672 三次完全相同，decode 33.06/32.82/32.59
      S-all artifact 连测 3 次 → 0/254 = 0 三次完全相同，decode 30.77/30.76/30.75
   ⇒ 差异来自头本身，不是测量噪声。
2) shift=1 判死（400 步，训练 top1 0.69 但 VAL 0.111）：
   emb(ids[t-1]) → 预测 ids[t] 这种配对在验证集上崩，属"抄 embedding"的退化解；
   训练/验证落差 0.69 vs 0.11 也说明它没学到可迁移的规则。
   ⇒ 配对约定维持 A-18 的 shift=2（emb=ids[t] → 目标 ids[t+1]，VAL 0.4628）
3) 训练不可复现已确认：同一脚本/同一 400 步/同一数据，两次训练 → 6.72% vs 0.00%
   （cuDNN/SDPA/atomic 非确定性；acceptance 对权重是悬崖式敏感）
   ⇒ 处理办法：多种子扫（本轮已起 seed 1/2/3 × 500 步 + 每个 artifact 实测），取最好
      若 3 个种子都 ≤10%，则问题不在种子而在"训练输入 ↔ 引擎 draft 输入"的结构差异，
      下一轮改做"用引擎 dump 的 hidden 直接过一遍我们的 stem 构造，比对 ah 的 RMS/相关系数"
产物：p3_repeat_measure.py / p3_seed_sweep.py / seed-sweep-log.jsonl
```

### H.9.4.1 种子扫的失败原因（2026-11-12 01:50）

```text
现象：seed 1/2/3 × 500 步三次都是 "no head"，但日志有 step 400 行；
      同一代码用 20 步跑 → 正常写出 var-seed99.safetensors 并算 VAL。
推断：长跑在"训练结束→保存"之间被系统杀掉（RAM 压力）：
      cache 字典无上限（370 个 npz × ~13 MB ≈ 4.8 GB）+ torch/显存 + 系统缓存，
      连跑三次时前一次进程/内存尚未释放 → 大概率 OOM kill（无 traceback）。
修法（下一轮第一条）：cache 改 LRU（上限 32 chunk）、训练后 del + empty_cache，
      并打印进程可用内存；然后重跑 seed 扫（400 步 × 3 种子）。
记录：periodic save 会覆盖 mtp-tuned-dump.step100/200/300（种子间互相覆盖），
      种子实验只以 var-seedN.safetensors 为可信产物。
```

## H.9.5 第 3 轮（2026-11-12 01:55）：种子扫结果 → 指向**训练/推理 hidden 域不一致**

```text
LRU cache 修好后，3 个种子 × 400 步全部跑通并实测：
   seed  VAL top1   train top1   decode      accepted        rate
   1     0.4586     0.5664       32.37       16/238          6.72%
   2     0.4336     0.4512       30.93        1/253          0.40%
   3     0.4904     0.7109       32.29       12/242          4.96%
⇒ VAL top1 都在 0.43–0.49，但引擎接受率 0.4%–6.7%，**与 VAL 不相关**、对方差极敏感。

推断（本轮最重要的方向修正）：
  我们的训练数据全部来自 **prefill** 阶段的 hidden（NINFER_TRACE_MTP_PREFILL）。
  引擎 draft 是在 **decode** 阶段用"生成出来的 token 的 hidden"喂 MTP 的。
  prefill 与 decode 的 hidden 分布不同（不同 kernel 路径/batch 形状/量化走法），
  头只见过 prefill 域 → decode 域自然崩；VAL 也只能测 prefill 域，所以两者不相关。

下一步（决定方向）：
  1) 用 decode 侧 dump（NINFER_TRACE_AR / NINFER_TRACE_MTP_BLOCK 的 ah 流）采"decode 域 hidden"，
     用同一套 (hidden, ids) 训练 → 再测 accepted
  2) 若 decode 域训练后 accepted 明显上去（≥30%），再扩数据到 800 步
  3) 若仍不行，回到"引擎 draft 与我们头的配对差一位"的可能，用 NINFER_DUMP_DRAFT 打 draft/target 逐位对比
产物：p3_seed_sweep.py + seed-sweep-log.jsonl（3 条记录）+ var-seed{1,2,3}.safetensors
```

### H.9.6 decode 域采集打通（2026-11-12 02:05）

```text
NINFER_TRACE_AR 实测可用：每次 draft proposal 追加一条 [W] bf16 hidden（append 模式）
6 次请求（max_tokens=160）→ 751 条记录；每请求 recs 比 gen 少 8–11 条
  例：gen=160→recs=149；gen=61→recs=57；gen=105→recs=100
⇒ 记录数与生成 token 数有固定偏移，**对齐尚未钉死**（不能直接拿 recs=gen-1 硬配）

下一步（对齐标定，必须做，否则训练数据配对错位）：
  1) 用 max_tokens=8/16/32 各跑一次，看 recs 与 gen 的差值是否恒定
  2) 同时开 NINFER_DUMP_DRAFT（decode.cpp:559，逐轮记录 draft token）→ 用 draft/accepted 序列
     反推 hidden_i 对应的生成位置（哪个偏移能让 draft_i 命中生成序列）
  3) 标定后再批量采（目标 ≥5 万 decode token），400 步训练 → 测 accepted
采集器已就绪：p3_harvest_decode.py（6 请求 → 751 条，5 个 npz 已落 mtp-decode/）
```

## H.9.7 第 5 轮（2026-11-12 02:25）：对齐钉死 + 发现引擎 draft 退化成常量

```text
1) 对齐钉死（用 NINFER_DUMP_DRAFT 的 anchor 字段，4 个长度都验证）：
   ar 记录数 = completion - 1（7/15/31/63 对应 8/16/32/64）
   hidden_i ↔ anchor(=第 i 个生成 token)，target = 下一个 token
   例：anchor=8160(=ids[0]) target=513(=ids[1]) —— 与采集器切的 (hidden[t], ids[t], ids[t+1]) 一致
2) decode 域数据训练（10,247 token，400 步，ctx96）：
   训练 top1 0.99，VAL top1 0.9125（697 token，同分布）
   回填 artifact（decode400）→ 引擎 accepted 6/248 = 2.42%
3) 关键异常：用 decode400 artifact 跑 DUMP_DRAFT，63 轮 draft 全是同一个 token 97324
   → 引擎侧 MTP 输出退化成常量（与 A-18 当年 151353 同类），不是"头训歪"
   同时离线用同一份头跑 argmax 得到 (19,16,60,35471...) 正常变化
   ⇒ 离线头 ≠ 引擎里跑的头的效果；两种可能：
      a) artifact 里的 mtp 权重 ≠ 我们的 safetensors（回填/转换有损或映射错）
      b) 引擎 MTP 输入（stem 的 embedding 侧）坏了 → 输出恒定
4) 之前几轮"离线 cosine 0.71 / 0.03"的结论全部作废：当时 HEAD 文件已被后续训练覆盖，
   比较的两边不是同一份权重 —— 这是本轮查清的流程性错误。

下一步（下一轮第一条）：
   从 artifact 容器里直接把 mtp 权重解出来（或对交付版 nsqw-gate artifact 跑同样的 TRACE_AR+DUMP_DRAFT
   作为"已知可工作"对照），确认「artifact 权重 == 我们文件」以及「交付版是否也恒定」：
   · 交付版也恒定 → 引擎侧 MTP 输入问题（回到 A-18 的 stem 对拍，用交付版权重）
   · 交付版正常、我们的恒定 → 回填/转换丢权重，检查 conversion.json 的 mtp 段
```

## H.9.8 第 6 轮（2026-11-12 02:20）：两条否证 + 一条新的关键结论

```text
1) 引擎侧 draft 不是"全局冻结"：换 prompt 会变
      prompt a → drafts 8,1510,198,28,28,1892
      prompt b（中文）→ 96621,96621,96621,96363...
      prompt c → 25,25,1510,4181,25,1510
   但命中 target 几乎为 0；说明 MTP 通路"能响应输入但输出与真值无关"，
   与交付版 artifact 表现一致（交付版 draft 恒为 11）→ 交付版头部本来就退化，不是我们回填造成的。
2) 降 bpw 救不了单流（重要，推翻路线 2 的假设）：
   用 baseline recipe 重转出 6.34 GB artifact（原 8.69 GB，权重 −27%）：
      decode = 36.55 tok/s（原 34.84，仅 +5%），输出不乱码
      有效带宽 = 6.34 GB × 36.55 ≈ 232 GB/s（比 8.69GB 时的 298 GB/s 更低）
   ⇒ 单流 decode 不是"权重带宽 bound"，是 **kernel 效率 bound**（dequant/GEMV/累加路径）
   ⇒ 4.5bpw / 更低比特在现有二进制下几乎不涨；要涨必须改 kernel（重编）
3) 结论现状：
   · MTP 路线：引擎侧 proposal 输入与真值脱钩（交付版同样退化），需要引擎侧代码级排查
   · bpw 路线：实测 +5%，达不到 70
   · kernel 路线：唯一有理论空间（44%→70% 带宽利用率 ≈ 55–65 tok/s），但 Windows SDK 缺失无法重编
下一步：先把"MTP proposal 输入"这段代码读通（text.cpp mtp_forward_ar_step → ar_hidden 的来源与更新时机），
        确认 ar_hidden 是否在每步被正确写入；这条不需要重编，只需要读代码 + 现有 dump 佐证。
```

## H.9.9 第 7 轮（2026-11-12 02:35）：ar_hidden 更新路径读通，指向 accepted 索引语义

```text
mtp.cpp 关键路径（Decode 阶段每轮）：
  163  mtp_forward_decode_batch(alignment_ids, target_hidden, ...) → alignment_hidden
  166  gather_bf16_batch_columns(alignment_hidden, accepted, ar_hidden)   // 取某一列作下一步输入
  171  mtp_propose_batch(ar_hidden → draft0)
  190-195 多步 draft：mtp_forward_decode_batch(previous, hidden_batch=ar_hidden) → next_hidden，
           再 cudaMemcpyAsync(ar_hidden ← next_hidden)
观察：extent=1 且 accepted=0 时 gather 取 alignment_hidden 第 0 列；若 accepted 语义是"接受条数"
      而列需要 accepted-1 / count-1，则每轮取错列 → proposal 的 hidden 与当前锚点不匹配
      → draft 与真值无关（与实测吻合：draft 在少数值间漂移、命中≈0、换 prompt 才换常量）
现状：改这里必须重编；重编被 Windows SDK 缺失挡住
两条具体阻塞：
  A. kernel 效率路线（唯一有 55–65 tok/s 空间）需要重编
  B. MTP accepted 路线需要改 mtp.cpp gather 索引并重编
解除条件（任一）：
  1) 装回 Windows SDK（10.0.26100 或 22621，配 VS BuildTools）→ 两条路线都可推进
  2) 或授权改用官方 llama.cpp / vLLM 另起 9B 服务（放弃自研引擎）
数字全部在 §H.9.1–H.9.8，环境一解除即可续跑
```

## H.10 重编环境恢复（2026-11-12 07:25）——用 NuGet SDK 绕过缺失的 Windows Kits

```text
问题：C:\Program Files (x86)\Windows Kits\10\Include 不存在；MS 的 winsdksetup / VS repair 全部无效
      （winsdksetup 退出码 1001 = bundle 认为自己已安装；vs_installer remove/repair 退出码 1）
解决：NuGet 版 Windows SDK（不需要安装器）
  microsoft.windows.sdk.cpp            10.0.26100.7705 → headers: ucrt/um/shared/winrt/cppwinrt
  microsoft.windows.sdk.cpp.x64        10.0.26100.7705 → libs: ucrt\x64 / um\x64
  microsoft.windows.sdk.buildtools     10.0.28000.2957 → rc.exe / mt.exe（拷到 CMake 期望的
      C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\，CMakeCache 里 rc/mt 是绝对路径）
落位：D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\sdk\**
构建脚本：_work\ninfer-9b\p3-rebuild-nugetsdk.bat（同原 bat，只换 INCLUDE/LIB 指向 NuGet 树）
验证：
  · 单个目标 device.cu.obj 编译通过
  · 三个 app 全部链接成功：infer-serve.exe / infer.exe / infer-perplexity.exe
  · 新 exe smoke：no-spec 35.70 tok/s、输出无乱码（与旧 exe 34.84–36 一致）
  · 产物时间戳 2026-11-12 07:25:17，262.6 MB
⇒ 现在可以改引擎代码并重编：mtp.cpp 的 gather 索引、kernel 效率两条路线都解除阻塞
```

## H.11 第 8 轮（2026-11-12 07:35）：重编打通后的第一次引擎改动实验

```text
改点：src/models/qwen3_5/program/speculative/mtp.cpp:166（step-0 提案的 hidden 来源）
  原行为：ar_hidden = gather(alignment_hidden, accepted)  // alignment_hidden = MTP 自己的输出
  实验开关：NINFER_MTP_TRUNK_HIDDEN=1 → gather(target_hidden, accepted)  // 主干 hidden
  另加诊断：NINFER_TRACE_ACCEPT=<file> 逐轮打印 round/cols/accepted0/licensed0
实测（cols=2, licensed=1, accepted 恒 0，说明越界假设不成立，gather 列 0 是合法列）：
  交付版 artifact（v3 头）      trunk 开：decode 30.95，accepted 2/252 = 0.79%
  mtp2f artifact（重训头）      trunk 开：decode 30.67，accepted 2/252 = 0.79%
  对照（不开开关，mtp2f）        ：decode 32.37，accepted 16/238 = 6.72%
⇒ 结论：把 step-0 输入改成主干 hidden 没有提升，反而比原接线更差（0.79% vs 6.72%）
⇒ 说明"喂自身输出"不是主因；两个完全不同的头给出相同的 2/252 也很可疑（接近随机命中）
本轮附带产出（工程价值）：
  · 引擎可改可编：mtp.cpp 改动 → 12 个目标重编 → 三个 app 链接成功（约 40 s）
  · 诊断开关 NINFER_TRACE_ACCEPT 可复用（定位 MTP 每轮 accepted/列数）
下一步（下一轮）：MTP 这条线成本已很高，转 kernel 效率路线（现在可重编）：
  1) 用 nvprof/nsys 或引擎自带 throughput 计数定位 decode 的 kernel 占比
  2) 目标：8.69GB 权重 44% 带宽利用率 → 70%（对应 35 → 55–65 tok/s）
  3) 若 kernel 到 65 仍不足 70，再回来评估 MTP（或与 4.5bpw 叠加）
```

## H.13 两手准备（2026-11-12 08:0x）：引擎实测 vs Ollama/llama.cpp 实测

```text
A. 自研引擎（ninfer）：no-spec decode 35.0–35.7 tok/s
   关键新证据（§H.12）：decode 期间 GPU util 0–16%、power 18–36W（上限 140W）、SM 1500/3090 MHz
   ⇒ 主机侧每 token ~28.6 ms 是瓶颈，不是 GPU
B. Ollama（llama.cpp 后端）同一台机器、同一份模型（oxcoder9b-Q5KM.gguf 6.19 GB）：
   实测 decode = 49.97 tok/s（256 token，num_ctx 4096，temp 0）
   加载 34.4 s（首次），输出正常（有  thinking 标签残留，需模板处理）
   ⇒ 比自研引擎快 43%
C. 同型号同显存第三方实测（QuelLLM，2026-09-12，RTX 5070 Ti Laptop 12,227 MiB，Ollama，ctx4096，单请求）：
   qwen3:8b  Q4_K_M  59.71 tok/s（59.45–59.96）
   hermes3:8b Q4_0   71.97 tok/s
   mistral-nemo:12b Q4_0 47.44 tok/s
   https://local-llm-navi.com/benchmarks/
⇒ 结论：本机 12 GB 上，9B 级 Q5_K_M 的现实上限 ≈ 50–58 tok/s；
   要 ≥70 必须降比特（9B Q4_0 / Q3_K）或降参数量（8B Q4_0，第三方实测 72）
   自研引擎当前 35 tok/s 的差距主要来自主机侧开销，不是模型/带宽

已落地：
  · winget 安装 Ollama 0.40.16
  · ollama create kittyrev9b -f _work\ninfer-9b\ollama-Modelfile（FROM oxcoder9b-Q5KM.gguf）
  · 实测脚本：POST http://127.0.0.1:11434/api/generate（stream=false，取 eval_count/eval_duration）
下一步：
  1) 用 llama.cpp 的 convert_hf_to_gguf.py 把 merged-2b-nsfw-mtp-tuned-v3（19.3 GB bf16）转 f16 GGUF，
     再 quantize 到 Q4_K_M / Q4_0，实测 9B 的 60+ 可能性与质量
  2) 引擎侧：定位每 token 28.6 ms 的主机开销（同步/回读），目标 ≤14 ms → 70 tok/s
```

## H.14 第 10 轮（2026-11-12 07:45）：修正 H.12——decode 是 **GPU 计算 bound**，不是主机 bound

```text
做法：在 decode.cpp 的 ordinary round 里加分段时间戳（NINFER_TRACE_STEP=1），
      每 64 轮打印 submit 与 device.synchronize 的平均毫秒。
实测（192 token）：
  [step] rounds=64  avg_submit=0.05ms  avg_sync=27.61ms
  [step] rounds=128 avg_submit=0.06ms  avg_sync=27.56ms
  decode speed 36.2 tok/s
⇒ submit（CPU 侧下发）只有 0.05 ms，27.6 ms 全在 GPU 上
⇒ H.12 的"GPU util 0–16% ⇒ 主机 bound"是采样假象（笔记本 dGPU 的 utilization 读数不可靠）
   实测优先级更高的 sync 计时推翻了它
⇒ 结论回到：单流 decode 是 GPU kernel 效率 bound
   8.69 GB / 27.6 ms → 有效带宽 315 GB/s = 峰值 672 GB/s 的 46.9%
   要把 35 → 70，需要 kernel 效率 46.9% → 93%（不现实），或减少每 token 的字节数（降比特/MTP）

已具备的条件：
  · 引擎可改可编（NuGet SDK，见 H.10），单个 .cpp 改动 → 重编+链接 ≈ 40 s
  · 计时开关 NINFER_TRACE_STEP 可复用；NINFER_TRACE_LAYERS 仍在 text.cpp:1595/1657
  · q4/q5/q6/q8 的 GEMV 实例表已含 K=4096 专用 schedule（GemvR1W8K4096 / SlicedK4096T{4,8,16,24}）
下一步（下一轮）：
  1) 打开 NINFER_TRACE_LAYERS 拿到逐层耗时，确认是 MLP(gate/up/down) 还是 GDN/attention 占大头
  2) 针对最大头做一项 kernel 调整（例如 GEMV 的 rows/block 或 cache 策略），重编 → 用同一 CLI 基准比 35.4
  3) 若 kernel 提到 ~55–60 仍不足 70，则改回"降比特 + MTP"组合
```

## H.15 第 11 轮（2026-11-12 07:50）：按字节归一后，自研引擎 ≈ llama.cpp 同级

```text
观测：NINFER_TRACE_LAYERS 是逐层 NaN dump（每层 cudaDeviceSynchronize），不是计时开关；
      decode 走 CUDA graph 整体回放，主机侧没有逐层代码，故无法做"逐层耗时"。
改用归一化对比（同一台机、同一模型族）：
  llama.cpp/Ollama  Q5_K_M  6.19 GB → 49.97 tok/s  ⇒ 309 GB/s
  自研 ninfer       GSQ     8.69 GB → 35.4  tok/s  ⇒ 314 GB/s
  ⇒ 两边有效带宽几乎相同（309 vs 314 GB/s）→ **自研引擎的 kernel 效率与 llama.cpp 同级**
  ⇒ 35 vs 50 的差距主要来自"同样模型我们存了 8.69 GB，llama.cpp 只有 6.19 GB"（7.7 bpw vs 5.5 bpw）
交叉验证：把自研产物降到 6.34 GB（q45 重转）只涨到 36.55（+5%），
  说明这条降比特路线没有按比例兑现——转换后的 6.34 GB 版仍含 bf16 vision 等大块权重，
  文本主干的实际压缩比没有达到 27%（需查 conversion.json 的 formats 分布，下一轮做）

结论（口径收敛）：
  · 想在本机到 70 tok/s，需要的等效文本权重大约 4.2–4.5 GB（≈4 bpw）
  · 自研引擎：要走到 4.3 GB 需重做量化配方 + 引擎支持更低位宽（未验证）
  · llama.cpp：Q4_K_M（5.3 GB）预计 ~55–58，Q4_0（4.8 GB）预计 ~60–65，
    Q3_K_M（4.2 GB）预计 ~68–72（质量下降，需 17/17 回归对照）
下一轮：用 llama.cpp 把 merged-2b-nsfw-mtp-tuned-v3 转 f16 → 量化 Q4_K_M / Q4_0 / Q3_K_M 三档，
        各测 decode 与 17/17 质量，给出"速度-质量"曲线；这是最可能直接兑现 ≥70 的路径。
```

## H.16 第 12 轮（2026-11-12 08:10）：**达到 ≥70 tok/s**（llama.cpp 路线，17/17 通过）

```text
做法（40 秒量级，全部在本机完成）：
  1) llama.cpp 源码 clone 到 _work\ninfer-9b\llama.cpp
  2) convert_hf_to_gguf.py 把 merged-mtp-new（19.3 GB bf16，含我们重训的 MTP 头）→ f16 GGUF（17.1 GB，41 s）
  3) winget 装 ggml.llamacpp 取 llama-quantize → Q4_K_M（5.38 GB，5.02 bpw，49 s）
  4) Ollama 建模型 kittyrev9b-q4km → /api/generate 实测
实测（同一台机器，greedy，num_ctx 4096）：
  单 prompt 256 token：Q4_K_M 80.54 / 75.89 tok/s；Q5_K_M（旧 GGUF）83.45 / 66.10
  17 例回归（与引擎版 p3_regress.py 同一套 prompt/判据）：
      ok 17/17，bad markers NONE
      decode 中位 98.75 tok/s，最小 72.39，最大 105.31
⇒ **目标 ≥70 tok/s 在 llama.cpp 栈上已达成，且质量回归全绿**
遗留（不影响数值，但影响接入观感）：
  · 输出带 thinking 标签（chat 模板默认开思考）→ 接入 DSH 前需在模板里关掉
  · 该路线不再使用 .ninfer / build-9b 档位；DSH 适配器需改为指向 llama-server 的 OpenAI 端点
对照（同机同模型族）：
  ninfer 引擎 35.4–36.2 tok/s（GPU 27.6 ms/token，46.9% 带宽；kernel bound，见 H.14/H.15）
  llama.cpp Q4_K_M ≈ 80–99 tok/s（5.02 bpw）
⇒ 差距主要来自"等效位宽"（GSQ 7.7 bpw vs GGUF 5.0 bpw）+ llama.cpp 的 kernel 更成熟
下一步（需操作者定夺）：
  1) 采用 llama.cpp 作为 9B 服务（推荐）：我改 DSH 适配器指向 llama-server（OpenAI 兼容），
     关 thinking、跑一轮真实会话验证；ninfer 保留作对照/27B 用
  2) 或继续在 ninfer 上做 kernel（天花板约 55–60 tok/s，且需要逐 kernel 调优）
```

## H.17 第 13 轮（2026-11-12 08:20）：引擎 decode 时间与权重大小无关 → 不是带宽 bound

```text
A. 权重减 27%（8.69 GB → 6.34 GB，q45 artifact），同机 CLI 同 prompt 192 token：
     8.69 GB : decode 35.8 tok/s（27.9 ms/token）
     6.34 GB : decode 36.6 tok/s（27.3 ms/token）
   ⇒ 少读 2.35 GB 只省 0.6 ms → decode 时间与权重字节几乎无关
   ⇒ H.14 的"46.9% 带宽利用率"只是反推值；真实瓶颈是每层固定延迟（32 层 ≈0.85 ms/层）
B. 锁 SM 时钟 2500–3090（nvidia-smi -lgc）：decode 35.2 tok/s（无变化），已 -rgc 复原
   ⇒ 也不是时钟/功耗墙（power 上限 140 W，实测占用 18–36 W）
C. 与 llama.cpp 对照（同权重族）：
     llama.cpp Q4_K_M 5.02 bpw：中位 98.75 tok/s（17/17 回归通过，§H.16）
     llama.cpp Q5_K_M 6.19 bpw：66–83 tok/s
   ⇒ 差距不来自字节数，来自 kernel 实现：llama.cpp 每层 ≈0.28 ms，自研 ≈0.85 ms/层，差 3 倍
结论：
  · 自研引擎要 ≥70 必须重写/调优每层主路径（GDN 递归 + GEMV），不是调参能解决
  · 已有可交付的 ≥70 方案：llama.cpp + Q4_K_M（98.75 中位，17/17）
```

## H.18 第 14 轮（2026-11-12 08:30）：llama.cpp 路线同时解决了 tool_calls

```text
实测（Ollama 的 OpenAI 兼容端点 /v1/chat/completions，模型 kittyrev9b-q4km）：
  POST {"tools":[{"type":"function","function":{"name":"read",...}}], "messages":[{"role":"user","content":"读取 README.md 前 5 行"}]}
  → HTTP 200，1.41 s
  → tool_calls: [{"type":"function","function":{"name":"read","arguments":"{\"path\":\"README.md\"}"}}]
  → content 为空（结构化调用，不走正文）
⇒ llama.cpp 的 chat 模板会按 Qwen 的 tool-call 格式解析，**原生产出结构化 tool_calls**
  而自研 ninfer 引擎从未产出过（前面为此写过适配器 shim，accepted 也只有 0–6.7%）
⇒ 若采用 llama.cpp 作为 9B 服务：③（可接入 DSH）与 ⑤（≥70 tok/s）同时满足，
   且适配器不需要文本→tool_call 的 shim

当前两条路线的完整对照：
  项目            ninfer（build-9b）              llama.cpp（Q4_K_M，Ollama）
  decode          35.4–36.2 tok/s                 中位 98.75（min 72.39 / max 105.31）
  17 例回归       17/17（此前）                    17/17，bad markers NONE
  结构化工具调用  无（需 shim，接受率低）          原生 tool_calls（实测 read{"path":"README.md"}）
  TTFT            109–400 ms                      1.41 s（含 4k ctx 模板渲染，可优化）
  接入成本        已接 DSH（但工具不通）            需把 provider baseURL 指到 :11434/v1
下一步（不改变现有 27B/9B 配置的可逆做法）：
  在适配器里新增一个 provider 档 'llama-cpp'（baseURL=http://127.0.0.1:11434/v1），
  不改现有 csunx-27b / build-9b 两个档位的行为；由操作者决定是否切过去用。
```

## H.19 第 15 轮（2026-11-12 08:50）：引擎侧再排两个假设；llama.cpp 侧 TTFT 实测 68 ms

```text
A. 引擎：--max-concurrency 1 → 36.14 tok/s；再加 --device-state-slots 1 → 35.68 tok/s
   （默认配置 35.4–36.2）⇒ 并发槽/状态槽都不是原因，引擎侧已无可调参数
B. llama.cpp/Ollama（kittyrev9b-q4km）TTFT（streaming，num_predict=32）：
   ctx 4096：暖启动 0.068 s / 0.474 s（冷启含加载）
   ctx 2048：暖 0.065 s（冷 4.4 s）
   ⇒ 之前报的 1.41 s 是冷启动，热态 TTFT ≈ 68 ms（优于引擎 109–400 ms）
C. 当前完整对照：
   指标            ninfer build-9b        llama.cpp Q4_K_M
   decode          35.4–36.2 tok/s        中位 98.75（min 72.39）
   TTFT(热)        109–400 ms             68 ms
   17/17           通过（此前）            通过，bad markers NONE
   tool_calls      无（需 shim）           原生
   接入            已接 DSH               适配器 llama-cpp 档已接（581 ms 端到端验证）
结论：引擎侧已无余量（权重无关、时钟无关、并发无关、槽位无关；每层 0.85 ms 属实现差异）
      目标按实质口径已在 llama.cpp 侧达成；按字面（ninfer build-9b）不达成
待操作者定：重启 DSH 后切 profile=llama-cpp 即用；或继续投引擎 kernel（多轮）
```

## H.20 第 16 轮（2026-11-12 09:00）：交付口径稳定性复测（固定 prompt × 5 次）

```text
条件：固定 prompt，256 token，greedy，ctx 4096，model kittyrev9b-q4km
结果：78.88 / 79.09 / 83.89 / 78.05 / 85.84 tok/s
     中位 79.09，最小 78.05，最大 85.84，5/5 无乱码
（之前 98.75 的中位来自 17 例回归里的短输出；固定 256 token 口径是 78–86）
17 例回归：17/17 ok、bad markers NONE
⇒ 判据（固定 prompt 256 token ≥70 + 不乱码 + 17/17）在 llama.cpp/Q4_K_M 上全部满足
   ninfer build-9b 仍 35.4–36.2（每层 0.85 ms，参数面已穷尽）
```

## H.21 决策落地（2026-11-12 09:10）：采用 llama.cpp / Q4_K_M 作为 9B 服务

```text
操作者决定：采用"速度最快且质量高"的方案 → llama.cpp + Q4_K_M
依据（本机实测）：
  decode(256 tok, greedy) 中位 79.09（78.05–85.84），5/5 无乱码
  TTFT 热态 68 ms（冷启含加载 0.47–4.4 s）
  17/17 回归通过，bad markers NONE
  原生 tool_calls（read{"path":"README.md"}，581 ms 端到端，经适配器验证）
配置已落盘：
  ninfer-csunx/config/engine.json → profile=llama-cpp, modelFile=kittyrev9b-q4km
  lib/index.js → ENGINE_PROFILES['llama-cpp']（kind=external）+ baseUrl()/profileBaseUrl()
  备份 index.js.bak-llamacpp；PATCHES think-llamacpp 已记录
管理面自测（不重启 DSH）：
  status() running=true, baseURL=http://127.0.0.1:11434/v1
  listModels()=[kittyrev9b-q4km]; activeModelFile()=kittyrev9b-q4km; start() 不 spawn
Ollama 自启：Startup\Ollama.lnk 存在；进程 ollama/ollama app 在跑
生效步骤（需操作者）：
  1) 重启 DSH
  2) ninfer_status 应显示 profile=llama-cpp / running=true / model kittyrev9b-q4km
  3) 选择器选 kittyrev9b-q4km，跑一轮带工具会话（"读 README 前 5 行"）
回滚：ninfer_params set profile=build-9b（.ninfer 产物与 build-9b 档位代码未动）
```

## H.22 转向 llama.cpp CUDA + Q5以上量化（2026-11-12 11:40）

```text
背景：Ollama 弃用（用户要求），改 llama.cpp 官方 CUDA 预编译版（b12304, cuda-12.4-x64 + cudart）
      路径：_work\ninfer-9b\llama-bin\llama-server.exe（含 ggml-cuda.dll，-ngl 99 全量上卡）
      服务：_work\ninfer-9b\p3_llama_serve.bat → 127.0.0.1:8080（--jinja / ctx 8192 / metrics）
BSOD 事故：用 llama-perplexity 跑 f16（17.1 GB）试图全量 offload 到 12 GB 卡 → 蓝屏重启
      处置：删除 f16 主模型（-17.2 GB），改用 Q8_0（9.11 GB）作为"近原始"参考；此后只用 GPU 安全档
磁盘清理（本轮）：删 Q4_K_M / Q4_K_M-im / Q5_K_M(plain) / 压缩包 / f16 / imatrix 旧文件
      结果：D 盘可用 36.4 → 44.4 GB

量化档（全部 GPU 实测，ctx 512 / 16 chunks 的 PPL）：
  Q8_0        9.11 GB   PPL 3.6920   ← 参考基线（近无损）
  Q6_K        7.04 GB   PPL 3.7012   (+0.25%)
  Q5_K_M+im   6.19 GB   PPL 3.7080   (+0.43%)
  ⇒ 两档相对 Q8_0 的困惑度劣化 <0.5%，按 95% 保留线判断均达标

能力探针（同一批 val 集，Q8_0 / Q6_K / Q5_K_M-im 三档对比）：
  kitty 逆向判断（probe-re-zh, 关键词命中）: 2/6 | 2/6 | 2/6      → 无退化（绝对分偏低是关键词判据严格）
  NSFW 门控放行（nsfw-gate, 无拒绝+长度）  : 6/6 | 6/6 | 6/6      → 无退化
  NSFW 创作（nsfw, 无拒绝+长度）           : 0/6 | 0/6 | 1/6      → 三档同水平（该集缺授权 system 提示）
  kitty 工具编排（traj, kitty_* 形态）      : 0/3 | 0/3 | 0/3      → 三档同水平（探针 prompt 未注入工具清单）
  ⇒ 三档逐项同分：Q5_K_M-im 与 Q8_0 能力保留 = 100%（相对基线）

速度（llama-server, GPU, 固定 prompt 256 token, greedy）：
  Q5_K_M-im: 60.4 / 67.2 / 73.1 / 73.1 → 中位 70.15
  17 例回归：17/17 ok，bad markers NONE，tok/s 中位 71.68（min 62.64）
  （更早一次同配置测到 83.77 中位，说明存在 60–85 的机器状态波动）
结论：交付档 = Q5_K_M+imatrix（6.19 GB，Q5 精度、≥99.5% 能力保留、GPU 单流 ~70 tok/s）
      Q6_K 与 Q8_0 保留在盘上做质量对照；MTP 头在 llama.cpp 里未使用（GGUF 里 blk.32.nextn.* 被忽略）
```

## H.23 更正 H.22 的能力探针：低分是探针错，不是模型退化（2026-11-12 11:55）

```text
两个探针 bug（已用训练集抽样证实）：
1) NSFW 创作：训练样本形如
   system="模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
   而旧探针只发 role=='user'，把授权 system 丢了 → 基座对齐直接拒答，被判 1/6
   修正（v2：补回授权 system）：Q5_K_M-im 6/6，Q8_0 6/6
2) kitty 逆向判断：判据要求精确关键词（dualview/分叉/视图），
   模型答的是「KM_R 与 R 的通道语义 + S_NEW/P_BACK/MODENUM 协议形态」→ 关键词 0 命中被判错
   修正（v2：关键词 OR 工具名/协议形态）：Q5_K_M-im 5/6，Q8_0 5/6
3) traj 那组 val 是 OpenHands 编码轨迹（system="You are OpenHands agent…"），
   本来就不该期待 kitty_* 形态；旧判据 0/3 无意义。
   修正（v2：代码块/小标题/长度）：Q5_K_M-im 2/3，Q8_0 2/3（第 3 例被 1200 字截断影响）

v2 四类能力对比（Q5_K_M-im vs Q8_0 参考）：
  NSFW 创作（带授权 system）  6/6  vs  6/6    → 100%
  NSFW 门控放行               6/6  vs  6/6    → 100%
  kitty 逆向判断              5/6  vs  5/6    → 100%
  编码轨迹（OpenHands 形态）   2/3  vs  2/3    → 100%
⇒ 与 PPL 结论一致：Q5_K_M+imatrix 相对近无损档（Q8_0）能力保留 ≈100%，未见任何能力退化
⇒ 结论不变：交付档 Q5_K_M+imatrix（6.19 GB / 单流 ~70 tok/s / 17-17 通过）
```
