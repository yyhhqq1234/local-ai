# TASKPOINT — 项目级任务断点

> 保存时间：**2026-11-08 22:00（UTC+8）**
> 项目根目录：D:\BaiduNetdiskDownload\Local-AI
> 分支/版本：main @ af914b6（工作区另有大量未提交改动；训练产物与引擎运行时均在 .gitignore 内）
> 本次性质：**①③④② 完成并可用；⑤ 投机链路已打通（13 层修复）但 MTP 接受率≈0，34.4 tok/s 为当前权重天花板**
> 历史归档：旧版 2622 行（A1–A27 + §1–§26）压缩至 §13；原文见 `git log -- TASKPOINT.md`。

---

## ▶ 接手先读这一段

```text
目标：让 ninfer-serve.exe（Windows 原生）把后训练 Oxcoder9B 跑成可交付推理服务（五项验收）。

已完成（全部实测）
  ① 5 prompt × 3 轮 = 15/15（内容非空）· 长 prompt 312 token 3/3 · 失败只死单请求
  ② --vision 启动 7.1 s；HTTP URL 图片 → decode→image token→vision tower→文本，可复现
  ③ 普通对话（含长 prompt）正常；带 tools 内容退化属"可后续"
  ④ 冷启 7.1 s、长 prompt TTFT 225 ms、前缀复用命中更快
未完成
  ⑤ 34.4 tok/s（无投机）。投机链路已打通（--spec mtp --draft-tokens 1 → 31.4 tok/s），
    但 --request-log-jsonl 实测 decode.rounds=191 生成 192 token
    ⇒ MTP 的 draft 接受率 ≈ 0，投机无收益。需用 G1 量化后的 text 权重重训 MTP 头才有望突破。

交付物
  out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer（7.93 GB / 738 objects / text+vision+mtp / G1=q8 gate·up）
  启动：& _tools\run-serve.ps1            → ①③④
        追加 --vision                      → ②
        --spec mtp 可用但不建议（31.4 tok/s，负收益）

下一动作：⑤ 若要继续 —— 用 G1 量化后的 text 权重重新训练 MTP 头（对齐量化后 hidden 分布），
          或换 dflash/dflash2 投产权重（本地无）；否则 34.4 tok/s 是本机 12 GB 卡的交付上限。
```

---
## 1. 任务目标

- **一句话目标**：为 Qwen3.5-9B（OxCoder-9B，H=4096）补齐 NInfer 缺的 K4096 成套 kernel 特化，使本地 `ninfer-serve.exe`（Windows 原生，非 WSL）能加载并稳定推理，支持多模态。
- **验收标准**：
  - [x] 引擎能加载 `.ninfer`（5.81 GiB 权重，391 objects）
  - [x] prefill 全 32 层数值正确（l2 从 759 平滑递增到 25825，nan=0）
  - [x] 能输出正确内容（`"2 + 2 = 4. This is a fundamental arithmetic fact..."` / `"你好！很高兴为你提供帮助。"`）
  - [ ] **连续生成 ≥32 token 且 100% 成功**（当前 40%，100% 可复现）
  - [ ] 5 个不同 prompt × 3 轮全通过（当前 6/15）
  - [ ] decode ≥40 tok/s（当前 15.2 tok/s，因 CUDA graph 不可用）
  - [x] 内存 ≤6 GiB（当前 4.0 GiB）
  - [ ] 多模态（视觉）通路可用（未开始）

---

## 2. 背景与现状

### 2.1 为什么做

- 后训练已完成（方案 Z：双 adapter 分离，kitty 逆向工具路由 + NSFW 门控）。量化验收基线：
  - **G1 混合（mlp.gate/up 升 Q6，其余 Q5）：recall 0.6333 / leak 0.0333 / fpr 0 / trap 0.1111**（唯一达标量化版，约 7.4 GB）
  - 门控判据：GateRecall ≥0.90 · GateLeak ≤0.05 · GateFPR ≤0.05 · TrapRefusal ≤0.10
- NInfer 引擎**原本不支持 Qwen3.5-9B**（只支持 27B H=5120 / 35B-A3B H=2048），需补 K4096 特化。
- 操作者硬约束：**「我要的是本地 ninfer 可以推理的」「不要额外给我造推理引擎」「不接受 WSL2，必须 Windows 原生 .exe」「要支持多模态」**。

### 2.2 现状（全部实测）

```text
weights ready        | 5.81 GiB | 1.3s | 4.57 GiB/s
host context pinned  | 2.00 GiB | 227 ms   （--host-context-mib 2048；默认 8192 = 8.38 GiB）
engine ready         | total 2.4s
capacity             | KV 4,096 tokens, bf16 | pages 64/64 | runtime 318.7 MiB | free 4.66 GiB
进程内存             | WorkingSet 4.00 GiB / PrivateMemory 4.00 GiB
prefill              | 23–41 tok/s ✅
decode               | 15.2 tok/s（无 CUDA graph；开 graph 直接 FAIL）
成功率               | 6/15（A/B 两组各 3 轮 × 5 请求，100% 可复现）
```

### 2.3 关键配置（Qwen3.5-9B text_config 实测）

```text
num_hidden_layers=32        layer_types=[linear×3, full, …]（3:1，full_attention_interval=4）
num_attention_heads=16      num_key_value_heads=4        head_dim=256
hidden_size=4096            attn_output_gate=True        dtype=bfloat16
linear_conv_kernel_dim=4    linear_key_head_dim=128      linear_value_head_dim=128
linear_num_key_heads=16     linear_num_value_heads=32    mamba_ssm_dtype="float32"
⇒ GDN key_dim = 128×16 = 2048   value_dim = 128×32 = 4096   conv_dim = 2048×2 + 4096 = 8192
⇒ 对照 27B：H=5120, Q=24, KV=4, value=6144, conv channels=10240
```

### 2.4 变更记录

- 2026-11-07：原路线「P5 量化 → 质量验收 → NInfer 加载」被「NInfer 不支持 9B」阻断 → 改为「Windows 原生 .exe 移植（B 路线）」。

---

## 3. 总体计划

1. ✅ Windows 平台移植（6 文件：文件 IO / 读队列 / 系统信息 / WinHTTP 采集 / WIC 解码 / int128 兼容）
2. ✅ K4096 kernel 特化（29 处：GEMV / MMA / sliced-K / add / split / projection / norm）
3. ✅ 新形状目录（split n4096_n8192_k4096、split n5120_n5120_k4096、projection n248320_k4096 等）
4. ✅ 引擎能加载并 prefill 正确
5. ⏳ **修 verify 路径 100% NaN**（当前卡点）
6. ⏳ 开 CUDA graph 提速度（graph 路径有 NaN，与第 5 条同源）
7. ⏳ 多模态（视觉）通路
8. ⏳ 最终交付：单 exe + 模型 + 启动脚本，验收集全绿

---

## 4. 团队模式

- **否，单 Agent 执行**（本任务全程由主 agent 直接操作）。
- 历史（已归档，不活跃）：9B/27B 后训练阶段用过 AgentTeams，团队名与 task_id 见 §13。

---

## 5. 步骤规划

| # | 步骤 | 负责人 | 状态 | 备注 |
|---|------|--------|------|------|
| 1 | Windows 平台移植（6 文件） | 主 agent | 已完成 | EXIT=0 |
| 2 | K4096 kernel 特化（29 处） | 主 agent | 已完成 | 编译通过，加载成功 |
| 3 | 新形状目录注册 | 主 agent | 已完成 | split/projection/add 各若干 |
| 4 | 引擎加载 + prefill 正确 | 主 agent | 已完成 | 32 层 l2 平滑，nan=0 |
| 5 | **修 verify 100% NaN** | 主 agent | **进行中** | 已排除 6 个假设 |
| 6 | 开 CUDA graph 提速度 | 主 agent | 待办 | 依赖 5（同源） |
| 7 | 多模态（视觉）通路 | 主 agent | 待办 | 未开始 |
| 8 | 交付打包 + 验收集 | 主 agent | 待办 | — |

---

## 6. 已完成步骤（已验证事实）

- [x] **Windows 平台移植 6 文件**（改动：§10.1；验证：`cmake --build ... --target ninfer-serve` EXIT=0，260 MB exe 可运行）
- [x] **K4096 kernel 特化 29 处**（改动：§10.2；验证：引擎加载 391 objects 无报错，prefill 通过）
- [x] **prefill 数值正确**（验证：逐层 dump `_tools/layer-norm.txt`，L00 l2=759.8896 → L31 l2=25825.44，全 32 层 nan=0）
- [x] **能输出正确内容**（验证：`"2 + 2 = 4. This is a fundamental arithmetic fact: adding two units to two more units gives four units total."`、`"你好！很高兴为你提供帮助。"`）
- [x] **内存从 8.38 GiB 降到 2.00 GiB**（验证：`--host-context-mib 2048` → `host context pinned | 2.00 GiB | 227 ms`，进程 WorkingSet 4.00 GiB）
- [x] **A/B 对照排除 kValueRows=6144**（验证：A 组[未改动+预算增大] 6/15 = B 组[运行时化+预算原值] 6/15，完全相同）
- [x] **排除 6 个假设**（§7.2，每个都有实测数据）
- [x] **联网定位到三条完全对口的已知上游 bug**（§9.3）
- [x] **备份可用版本**（`_tools/dist/oxcoder9b-win-20261107-2134/`：exe 260MB + gdn.cpp + convolution.cu + plan.cpp）

---

### 6.9 本轮（2026-11-08 12:00–20:30）新增完成项

- [x] **长 prompt NaN（≥263 token）定位并绕过**：病灶 = L03 首个 full-attention 层的 proj_k/proj_v（1024 行段），
      触发宽度在 (260,272]；修法 = 启动加 `--prefill-chunk 128`（块宽 >128 必 NaN）。
      验证：312 token prompt 3/3 通过（此前必 500→503）。
- [x] **CUDA graph 已打通**：根因是 9B MLP swiglu dispatch 里未关闭的 `cudaDeviceSynchronize`（捕获期 error 900→901）。
      验证：decode 15.3 → 36.2 tok/s（2.3×）。commit 8973a04。
- [x] **采样空候选不再打死进程**：`ops/sampling/sample/kernel.cuh:56,206` 的 `asm volatile("trap;")` 改为不发散值。
      验证：带 tools 请求从「进程 0xC0000409」→「单请求 HTTP 500，引擎存活」。commit c6faf4b。
- [x] **grammar 约束失败降级**：`text/grammar.cpp:368` 的 accept 失败不再 throw。commit 9aa848f。
- [x] **G1 量化落地**：mlp.gate/up 升 **q8**（64 张量；原定 q6，因引擎无 q6 swiglu 改用 q8，精度更高）。
      产物 formats 含 q8×34，5×3=15/15 不退化，192 token 34.4 tok/s。
- [x] **三组件产物（text+vision+mtp）生成**：`kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer`（7.93 GB，738 objects）。
      转换链：影子 HF 目录（权重硬链接）+ recipe_g1_full_gsq.py + `--components text,vision,mtp`。
- [x] **② 视觉链路打通**：`--vision` ready=True 7 s；HTTP URL 图片 → decode→image token→vision tower→文本可复现。
      data URI 的 base64 路径有引擎上游 bug（WIC: unrecognized image format），用 HTTP URL 绕过。
- [x] **⑤ 投机链路连破 7 层**（每层打印定位后修）：
      pair k=4096 / mtp attention 四合一 group（含 gate，10240 行）/ q8(10240,4096) / q8(4096,4096) /
      bf16(24576,4096) / gdn_replay_fold 放宽到 32 层 / slice 越界定位于 GDN conv 常量。

### 6.10 ⑤ 投机链路专项（2026-11-08 21:00–22:00）—— 连破 13 层并首次跑通

- [x] **pair 的 k=4096**：`pair/q8/shapes/n1024_k5120.cu` 加 `select_q8_pair_n1024_k4096`（实现本就参数化，转发即可）。
- [x] **mtp attention 的 contiguous parent**：转换器 group 必须把 `query+gate+key+value` **四合一**（10240 行）
      成同一 parent，且四者 format/layout/method 全同（`qwen3_5.py` 的 mtp block）。
      验证：`[wv-parts]` 打印从「4 个不同 parent」变为「同 parent 且行区间连续」。
- [x] **q8 两个形状**：`projection/q8` 加 `(10240,4096)`、`(4096,4096)`（K 相同转发）。
- [x] **bf16 一个形状**：`projection/bf16` 加 `(24576,4096)`（转发 n12288_k4096）。
- [x] **fold 的 GDN 层数**：`fold_io.cuh` 加 `FoldGeometry24x32 = FoldGeometry<24,16,32,8192>`，
      `launch.h` 判定 `spec.layers == 24`，`fold.cu` 加对应 case。
      **关键认知：fold spec 的 layers 是 GDN 层数（32 层里每 4 层 1 个 full-attn → 24），不是总层数。**
- [x] **slice 三处运行期化**：`split/.../n4096_n12288_k5120/small.cu:232`、`input_conv/q4_q5/projection.cpp:18`、
      `input_conv/q4_q5/projection_mma.cu:39` 的 `6144` 全部改为按张量实际行数/权重推导。
- [x] **Q5 direct SIMT static K**：`convolution.cu:173`、`projection_independent.cu:117 / 170`（T=4 verify 路径）
      按 `x.ne[0]` 分派 4096/5120 两套 schedule 实例。
- [x] **split_bf16_features 几何**：`indexing/features.cu` 的 14336 / 256×24 / 256×4 硬编码改为
      从输出张量推导（`hd*(2q+2k)`），27B 与 9B 通用。
- [x] **投机首次跑通**：`--spec mtp --draft-tokens 1/3` 均可完整生成 192 token，无崩溃、无 500。
      实测：draft=1 → 31.4 tok/s；draft=2 → 13.4；draft=3 → 10.4–16.4（均低于无投机 34.4）。
- [x] **接受率取证**：`--request-log-jsonl` 显示 `decode.rounds = 191`、产出 192 token
      ⇒ 每轮仅 1.0 token ⇒ **MTP draft 接受率 ≈ 0**（draft=1 时若接受应约 96 轮）。

## 7. 进行中 / 下一步（新对话先干这个）

### 7.1 ⑤ 的定论（已取证，不是调度问题）

```text
实测：--spec mtp --draft-tokens 1，192 token 请求
  tps = 31.4
  decode.rounds = 191        ← 191 轮只产出 192 token
  decode.device_wait_exposed_seconds = 6.05
判读：draft=1 每轮 verify 2 列（target 1 + draft 1）
      若 draft 被接受则该轮出 2 token → 192 token 只需约 96 轮
      实际 191 轮 ⇒ **每个 draft 都被拒，接受率 ≈ 0**
⇒ 每轮白付一次 MTP forward + fold + 2 列 verify，故比无投机更慢。
```

**成因（按概率）**：MTP 头与 G1 量化后的 target 分布不对齐 —— 具体可能是
① MTP 训练时的 target 未做 G1（gate/up 升 q8），分布偏移；
② MTP 的 hidden 输入绑定到错误的层/位置（`mtp/pre_fc_norm_hidden`）；
③ MTP 与 text 权重不是同一来源世代。

### 7.2 下一步动作（三选一，按成本）

```text
A（最彻底）用 G1 量化后的 text 权重重训 MTP 头 → 对齐后接受率才有意义
B（验证成因）对比 MTP 的 hidden 输入：dump `mtp/pre_fc_norm_hidden` 的 l2，
   与 text 最后一层 final hidden 对比，看是否取错层/错位置
C（放弃投机）确认 34.4 tok/s 为交付上限，把 ⑤ 记为"受权重与硬件限制"
```

### 7.3 待验证假设

- 假设 1：若能拿到 dflash/dflash2 投产权重（本地无），可绕过 MTP 对齐问题。
- 假设 2：34.4 tok/s 已接近 12 GB 卡的带宽上限（5.81 GiB/token × 34.4 ≈ 200 GB/s，峰值 23-26%），
  非投机路径的优化空间有限（⑤-A 的 GEMV kernel 已实测无效）。
## 8. 待办步骤

- [ ] dump verify 中间张量（§7.3 动作 1）
- [ ] 定位并修 verify NaN
- [ ] 5 请求 × 3 轮全绿（目标 15/15）
- [ ] 开 CUDA graph，目标 decode ≥40 tok/s
- [ ] 多模态（视觉）：`src/media/decode/decode_win.cpp`（WIC）已移植，需接 `text.cpp` 的 image token 路径
- [ ] 清理 `text.cpp` 的 layer-norm / gdn-verify dump 诊断代码
- [ ] 最终交付：exe + 模型 + 启动脚本 + 验收报告

---

## 9. 雷区（进行时必须避开）

### 9.1 构建与环境

1. **坑：改 `.cuh` 不触发重编**；原因：Ninja 依赖追踪不含被 include 的头；正确做法：手动删对应 `.obj`。
2. **坑：`No CUDA toolset found`**；原因：vcvars64 未注入；正确做法：先执行 §11.1 的 98 个环境变量注入，用 Ninja 生成器。
3. **坑：`crt/host_config.h` 缺失**；原因：CUDA 安装不完整；正确做法：`-s` 全量重装 CUDA 13.0。
4. **坑：`error C2719`（`__grid_constant__` + `alignas(128)`）**；正确做法：去掉 `alignas(128)`。
5. **坑：`__int128` 不支持 / `shared_ptr::unique()` 缺失**；正确做法：`int128_compat.h`、改用 `use_count()!=1`。
6. **坑：`utf8proc` dllimport 冲突**；正确做法：全局 `-DUTF8PROC_STATIC`。
7. **坑：`localtime_r`/`gmtime_r` 不存在**；正确做法：`localtime_s`/`gmtime_s`（**参数顺序相反**）。
8. **坑：`LNK1104: 无法打开 exe`**；原因：上次引擎进程未退；正确做法：编译前 `Stop-Process -Name ninfer-serve`。
9. **坑：PowerShell here-string 里的 `` `r`n `` 变成字面反引号**（`error C2018: 未知字符 0x60`）；正确做法：**用 `edit`/`write` 工具或按行号插入，不要用 here-string 拼 C++ 代码**。

### 9.2 诊断方法（三次踩同一个坑，最重要）

10. **坑：dump 出来的数值全是假象**；原因：**`cudaStreamSynchronize(nullptr)` 只同步默认流，引擎 kernel 在自有 stream 上**；正确做法：**dump 前一律 `cudaDeviceSynchronize()`**。此错误造成第 8–16 轮全部误判，第 28 轮又踩一次（征兆：同一指针两次相邻 memcpy 读到相反结果）。
11. **坑：以为 FP32 张量爆炸到 1e34**；原因：把 FP32 当 bf16 解码；正确做法：**dump 前先查 `t.dtype`**（`g`/`beta` 是 FP32；`DType::FP32`，不是 `DType::F32`）。

### 9.3 上游同类 bug（已找到）

12. 三条完全对口的已知 bug（本地对应点都已确认正确处理，但思路可复用于别处）：
    - vLLM #55766：Qwen3.5 hybrid GDN —— **prefill 结束位置距 block 边界 4-10 token → NaN logits**（我们的 req#3 是 20 tok，20 mod 16 = 4，正好命中）
    - HyperQwen `mamba-chunked-prefill-align.patch`：`chunk_o.py` 的 `b_g` 在 `exp()` 前未 mask + mamba state 的 `src_col` 在 block 边界算错
    - vLLM #59404：边界 chunk 的 mask 在 `exp()` 前被丢弃
    - 补丁已下载：`_work/ref/hyperqwen-mamba-align.patch`、`_work/ref/megatron-2897.patch`

### 9.4 形状与预算（改一处崩全局）

13. **坑：改 `MmaGeometry` 的 Hidden 参数让 prefill 全崩**；原因：Hidden 参与 kernel 内部 tile 循环与寄存器分配，且 `plan.split_k` 按 K=2048 规则算出，与 4096 不匹配；正确做法：**不要换模板参数，走运行时参数**。
14. **坑：禁用 `Q4Q5Fused` 或改走 `Materialized` 让 prefill 全崩**（`L00~L31 nan=8192`）；原因：`convolution_capacity` 用 `select_conv_plan` 算预算，kernel 与预算必须同步改。
15. **坑：改 `gdn_snapshot_workspace_bytes`（增大预算）让 prefill 全崩**；原因：该返回值参与启动时 arena 全局布局；正确做法：**已恢复为原始一行调用**。
16. **坑：`gdn_projection_snapshot` 写成两段（linear_split + causal_conv1d_silu_snapshot）编译过但 prefill 崩**；正确做法：已回滚为 `ops::gdn_input_proj_conv_snapshot`。
17. **坑：`Q5 exact direct SIMT token count differs from schedule`**；原因：`DirectSimtSchedule` 的 BlockTokens 必须 == T 且 ≤8；正确做法：`Q5A16SimtSchedule<1,4,4,16,2,Cache::ca,1>`。
18. **坑：`BF16 KV template operands do not match`**；原因：第 3 轮 regex 把 `throw` 留在 `if` 块外；正确做法：修回块内。
19. **坑：`projection/q5` 缺 (4096,12288)**；正确做法：新建 `n4096_k12288.cu` 并在 `q5_shapes.h` 声明 + `q5_dispatch.cpp` 的 ShapeEntry + `sources.cmake` 三处注册。

### 9.5 引擎参数

20. **坑：`--host-context-mib` 默认 8192 → 8.38 GiB host pinned**；正确做法：9B 用 `--host-context-mib 2048`（实测 2.00 GiB，够用）。
21. **坑：去掉 `--no-cuda-graph` 请求直接 FAIL**；原因：CUDA graph 路径本身有 NaN（与 verify NaN 同源）；正确做法：功能修好前必须带 `--no-cuda-graph`。
22. **坑：warmup 触发 verify 会把 state 弄坏**；正确做法：`generation_service.cpp:566` 已设 `request.max_tokens = 1;`（warmup 只 prefill）。

### 9.6 文件边界（最高优先级）

23. **只能写 `D:\BaiduNetdiskDownload\Local-AI\` 之内**；`D:\DrCE(26.2.16)\` 只读（可复制出来，禁止在里面写/改/删/跑脚本）。
24. **禁删清单**（删除会导致环境不可恢复）：`ninfer-27b-kv-stream-3arch-20261019/`(23GB) · `ninfer-csunx/`(1.9GB) · `.ninfer` · `train/.venv/` · `train/lines/9b-oxcoder/models/` · `train/lines/27b-kittyrev/base/`(52GB) · `train/lines/27b-kittyrev/local-pack/`(121GB) · `plugins/` · `_work/session-audit/`。**删大文件前必须问操作者。**

### 9.7 崩坏即回滚的纪律

25. **基线**：`prefill L00 l2=759.8896` / `verify L29 l2=15116.80 · L30 l2=16646.69 · L31 l2=25971.44`（全 nan=0）。出现 `nan=8192` 立即回滚。

---

### 9.8 本轮新增雷区（2026-11-08 12:00–20:30，只增不减）

- 现象/坑：改了 `.h` / `.cuh` 后重编，报错不消失、行为不变；原因：Ninja 不跟踪头文件依赖；
  正确做法：改头文件后必须手删对应 `.obj`（本轮 `gdn/replay/launch.h` 就踩过，删 gdn/replay 相关 40+ obj 才生效）。
- 现象/坑：converter 的 `--recipe` 传绝对路径报 `cannot load recipe file ...\D`；
  原因：`--recipe` 支持 `file:function` 语法，按 `:` 切分，Windows 盘符被切掉；
  正确做法：把 recipe 复制到 `ninfer-master\.agent-tmp\` 并用**相对路径**传。
- 现象/坑：`--resource tokenizer_config.json=<path>` 不生效、产物内仍是 1100 B 精简版；
  原因：该 resource 的取值链路有内部优先级，外部参数被覆盖；
  正确做法：用影子 HF 目录（`model.safetensors` 建硬链接，只替换 json），且 tokenizer_config 必须用
  **旧产物里那份 5518 B 的完整版**（含 added_tokens_decoder + add_prefix_space），
  导出方式：`tools.artifact.reader.Artifact(...).read_object('resource/text/tokenizer_config.json')`
  （`read_range` 拿到的是封装编码、`to_json()` 只返回元数据，都不对）。
- 现象/坑：转换报 `FileExistsError: conversion output already exists`；
  原因：`.conversion.json` 残留也算已存在；正确做法：删 `<x>.ninfer` 和 `<x>.ninfer.conversion.json` 两个。
- 现象/坑：`--prefill-chunk 40` 等小值会让引擎直接打印 usage 退出；正确做法：用 128（实测可用）；
  块宽 >128 时 L03 的 proj_k/proj_v 会 NaN（长 prompt 必 500→503）。
- 现象/坑：长 prompt 输出全落 `reasoning_content`、`content` 为空；正确做法：启动加 `--no-thinking`。
- 现象/坑：带 tools 的请求内容退化为重复 token（44/94 之类恒定 id）；
  原因：prompt 长度（358 token）落在长 prompt NaN 区间，不是 tools 逻辑问题；
  正确做法：先解决长 prompt（chunk 128），再谈工具调用。
- 现象/坑：`S_NEW` 之外，`--spec mtp` 报 `missing component mtp` / `--vision` 报 `missing component vision`；
  原因：.ninfer 的组件由转换时 `--components` 决定，缺组件无法靠启动参数补；
  正确做法：重转并显式列 `--components text,vision,mtp`。
- 现象/坑：mtp 的 attention 张量被拆成多个 object 时，加载报
  `native input requires one contiguous parent region`；
  原因：引擎要求同一 WeightView 的 parts 属于**同一 parent 且行区间相邻**；
  正确做法：转换器的 group 必须把 `query+gate+key+value` **四合一**（10240 行）成同一 parent，
  且四者 format/layout/method 完全一致（否则 compatible() 不合并 → 各成独立 parent）。
- 现象/坑：`q8 linear: unsupported shape` / `bf16 linear: unsupported shape` 只说"不支持"，不说是哪个形状；
  正确做法：在 `projection/q8/q8_dispatch.cpp` 与 `projection/bf16/bf16_dispatch.cpp` 抛错前
  加 `fprintf(stderr, "[q8-miss] n=%d k=%d t=%d\n", ...)`，一次就能拿到缺失形状。
  （这些诊断打印定位完必须删掉，别留在热路径/启动路径。）
- 现象/坑：`gdn_replay_fold: unsupported record geometry`；
  原因：`select_fold_geometry` 只认 48/36/30 层三种几何；
  正确做法：9B 是 32 层，但 head 几何（qk16/value32/conv8192）与 Layers30Heads32 相同，
  放宽 layers 判定复用即可（fold 是逐层的）。
- 现象/坑：PowerShell 里 `"run$n:"` 报「变量引用无效」；正确做法：写成 `"run${n}:"` 或字符串拼接。
- 现象/坑：`Stop-Process` 偶发「找不到进程标识符」；原因：引擎已退出；
  正确做法：`-ErrorAction SilentlyContinue`，不要当失败。

### 9.9 ⑤ 专项新增雷区（2026-11-08 21:00–22:00，只增不减）

- 现象/坑：改 `.h` / `.cuh` 后行为不变、报错照旧；原因：Ninja 不跟踪头文件；
  正确做法：改头文件后手删依赖 `.obj`（本轮 `gdn/replay/launch.h` 需删 gdn/replay 全部 obj）。
- 现象/坑：`cudaErrorIllegalAddress` 只告诉你"越界"，不给 kernel 名；
  正确做法：`compute-sanitizer --tool memcheck --launch-timeout 300 --target-processes all <exe> <args>`，
  它会打印 `Device Frame: <kernel<模板参数>>(…) +0x… in <文件>:<行>` —— 本轮据此定位到
  `recurrent_fold_kernel<FoldGeometry<30,16,32,8192>> at fold_io.cuh:179`。
- 现象/坑：fold 的 `spec.layers` 是 **GDN 层数**（32 层里 24 个 linear-attention 层），不是总层数；
  误用 30/32 层实例会在 `recurrent_fold_kernel` 里越界读写 state slot。
- 现象/坑：引擎报 `q8 linear: unsupported shape` / `bf16 linear: unsupported shape` 不说是哪个形状；
  正确做法：在 `projection/q8/q8_dispatch.cpp`、`projection/bf16/bf16_dispatch.cpp`、
  `core/tensor.cpp`（slice）、`gdn/replay/launch.h`（fold）的抛错前加 `fprintf`，一层一层剥。
  **定位完必须删掉这些打印。**
- 现象/坑：PowerShell 单引号字符串里的 `` `r`n `` 不展开，写进源码会变成字面反引号字符导致编译失败；
  正确做法：用双引号字符串或 `[Environment]::NewLine`。
- 现象/坑：`"run$n:"` 报「变量引用无效」；正确做法：`"run${n}:"`。
- 现象/坑：`--prefill-chunk 40` 之类小值会让引擎打印 usage 直接退出；可用值是 128（实测）。
- 现象/坑：`--request-log-jsonl` 的 `argv` 行会很长，`Select-String` 过滤时注意截断。

## 10. 关键文件与修改

### 10.1 平台移植（新增，含中文注释 + `.bak-winport` 备份）

```text
train/lines/_shared/tools/ninfer-master/
├─ cmake/Dependencies.cmake                     Windows 分支（CUDA/依赖探测）
├─ src/core/CMakeLists.txt                      平台源文件选择
├─ src/product/CMakeLists.txt                   同上
├─ src/media/CMakeLists.txt                     同上
├─ src/core/io/file_win.cpp                     CreateFileW + GetOverlappedResult
├─ src/core/io/read_queue_win.cpp               异步读队列
├─ src/core/cpu/system_win.cpp                  系统信息
├─ src/product/media_acquire/acquire_win.cpp    WinHTTP
├─ src/media/decode/decode_win.cpp              WIC
└─ include/ninfer/detail/int128_compat.h        __int128 → 结构体
```

### 10.2 K4096 特化（29 处）

```text
kernels/q8/q8_instances.cuh            GemvR4W1K4096 = Q8A16GemvSchedule<4,1,2,4096>
kernels/q5/q5_instances.cuh:14-15      GemvR16W1G16S2XK4096 = Q5A16GemvSchedule<16,1,16,2,Ca,1,true,4096>
                                       DirectR1T{1,2,3}W4K4096
kernels/q4/q4_instances.cuh:11,16      GemvR1W8K4096 · SlicedK4096T{4,16,24}
split/q4_q5/shapes/n4096_n8192_k4096/  GDN qk/vz，kSplitRows<8192,4096>
split/q4_q5/shapes/n5120_n5120_k4096/  attention 4 段，kSplitRows<4096,1024,4096,1024>，sub_weight() 行偏移 + 4 次 launch
projection/q8/shapes/n248320_k4096.cu  lm_head
projection/q5/shapes/n4096_k12288.cu   新建（mma<MmaR32T128>，避开 sliced 多批）
add/q5/shapes/n4096_k12288.cu · n4096_k4096.cu
control/bf16/n64_k4096.cu              新建未启用（MmaGeometry<32,4096,64>）
```

### 10.3 关键源码（当前状态）

```text
src/ops/linear_attention/gated_delta_net/input_conv/q4_q5/convolution.cu
  → 当前是【原始版】（kValueRows=6144 constexpr 全在）。
     第 27/29 轮的「5 处运行时化」已回滚（A/B 证明无效）。
     备份：convolution.cu.bak-kv4096（原始）
  → 如需重做：make_epilogue 内部从 Tensor 取 q_rows/k_rows/v_rows/channels；
     Q5GdnZOutput 加 int stride 成员；Q5GdnProjectionEpilogue 用 conv.value_rows

src/models/qwen3_5/execution/gdn.cpp
  → gdn_snapshot_workspace_bytes 已【恢复为原始一行调用】（第 25 轮增大版已撤销）
  → gdn_projection_snapshot 调用 ops::gdn_input_proj_conv_snapshot（融合路径）

src/models/qwen3_5/execution/text.cpp
  → 1137 起：逐层 hidden dump（_tools/layer-norm.txt，cudaDeviceSynchronize 后 cudaMemcpy）
  → 990 起：gdn-verify.txt dump（已按 DType::FP32 / bf16 分支）
  → ★ 诊断代码，功能修好后需清理

src/ops/sampling/sample/entry.cpp
  → 已清理全部诊断（156 行 → 80 行），无 cudaDeviceSynchronize / 全 vocab 扫描
  → plan.h 强制单 CTA

src/serve/generation_service.cpp
  → 442/476 两处 catch 链，505 挂 catch-all（打印真实异常到 _tools/verify-error.txt）
  → 566: request.max_tokens = 1;（warmup 只 prefill）
```

### 10.4 产物与备份

```text
_tools/ninfer-build/apps/ninfer-serve.exe                260 MB（当前构建）
_tools/dist/oxcoder9b-win-20261107-2134/                 ✅ 可用版备份（exe + gdn.cpp + convolution.cu + plan.cpp）
train/lines/9b-oxcoder/out/oxcoder9b-merged.ninfer        6.1 GiB
train/lines/9b-oxcoder/DEPLOY-GATE-MANIFEST.md            §22.1–§22.36 全部关卡记录
_work/ref/vllm_qwen_gdn.py · ollama_qwen35_9b.json        上游参考
_work/ref/hyperqwen-mamba-align.patch · megatron-2897.patch  上游修复补丁
_tools/ 诊断产物：layer-norm.txt · gdn-verify.txt · logits-diag.txt · verify-error.txt · mlp-diag.txt · delta-diag.txt
```

---

## 11. 验证方式

### 11.1 构建（必须注入 vcvars64 的 98 个环境变量）

```powershell
$BASE='D:\BaiduNetdiskDownload\Local-AI'
$VS='C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
$CUDA='C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0'
$CMake="$BASE\_tools\cmake-4.1.2-windows-x86_64\bin\cmake.exe"
Get-Process -Name "ninfer-serve" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
$dump = & cmd.exe /c "`"$VS\VC\Auxiliary\Build\vcvars64.bat`" >nul 2>&1 && set" 2>&1
foreach ($line in $dump) { if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') } }
$env:PATH = "$BASE\train\.venv\Scripts;$CUDA\bin;$env:PATH"
& $CMake --build "$BASE\_tools\ninfer-build" --target ninfer-serve --parallel 6
# 判据：EXIT=0
```

### 11.2 启动引擎（省 6.4 GiB 内存）

```powershell
$E="$BASE\_tools\ninfer-build\apps\ninfer-serve.exe"
$M="$BASE\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer"
& $E $M --max-context 4096 --greedy --no-cuda-graph --host-context-mib 2048 --port 1610
# 判据：host context pinned | 2.00 GiB | ~227 ms；engine ready | total ~2.4s
```

### 11.3 5 请求验收（基线 2/5，目标 5/5）

```powershell
$bodies = @(
  '{"model":"oxcoder9b-merged","messages":[{"role":"user","content":"What is 2+2?"}],"max_tokens":32}',              # 基线 OK
  '{"model":"oxcoder9b-merged","messages":[{"role":"user","content":"Say hello in Chinese."}],"max_tokens":24}',      # 基线 OK
  '{"model":"oxcoder9b-merged","messages":[{"role":"user","content":"Explain what a gated delta network is in one sentence."}],"max_tokens":48}',  # 基线 FAIL
  '{"model":"oxcoder9b-merged","messages":[{"role":"user","content":"Write a Python one-liner to reverse a string."}],"max_tokens":64}',          # 基线 FAIL
  '{"model":"oxcoder9b-merged","messages":[{"role":"user","content":"List 3 benefits of unit testing."}],"max_tokens":128}'                        # 基线 FAIL
)
```

### 11.4 每步「过了」的标准

```text
prefill 正常     → _tools/layer-norm.txt 的 L00 行 = "L00 prefill T=2 nan=0 l2=759.8896"
verify 正常      → L29/L30/L31 全 nan=0，l2 ≈ 15116.80 / 16646.69 / 25971.44
logits 正常      → logits-diag.txt 的 [scan] nan=0
功能通过         → 5 请求 × 3 轮 = 15/15
异常定位         → _tools/verify-error.txt 里有 [exc] 行（catch-all 已挂）
```

---

## 12. 恢复指令

新对话打开本项目后执行 `/resume`，Agent 将读取本文件并从 **§7.3 动作 1** 继续：
**dump verify 路径的 qc/kc/vc/z + state_out + KV cache，与 prefill 逐字节比对。**

---

## 13. 历史归档（压缩保留，原文见 git 历史）

### 13.1 后训练线（9B OxCoder + 27B KittyRev）

```text
方案 Z（2026-10-31 封板）：双 adapter 分离
  · Z-B  PASS：kitty 逆向工具路由（hit 30 · 75.0% · 编造 0）
  · Z-2A PASS：NSFW 门控（cov 64.62% · code 62.5% · tool_call 0）
  · 六轮 A 腿对照完成；终报 train/logs/z-final-report.md

量化验收（唯一达标版 G1 混合，约 7.4 GB）：
  mlp.gate/up 升 Q6，其余 Q5 → recall 0.6333 / leak 0.0333 / fpr 0 / trap 0.1111
  对照：bf16+4bit recall 0.5667/leak 0；全 Q5+4bit leak 0.1333（超标）
  判据：GateRecall ≥0.90 · GateLeak ≤0.05 · GateFPR ≤0.05 · TrapRefusal ≤0.10

27B GEN3 线（v4/v5 意愿强化，旧版 A13–A27）：
  · A15：SRA 版 vs 原版 40 条 RE 固定集（定论见旧版 §A15.3）
  · A23：V2 路线判为「否证」（保留证据，不再迭代）
  · A24：★ 核心发现「E2 下错误总数恒定为 6」
  · A25：六数据点证明敏感的是「具体干扰组合」不是「干扰数量」；
         2026-11-03 19:43 首次完整回归基线（四档全绿 PASS）
  · A26：v4 数据核心矛盾（system × 该拒/该答交叉分布 + system 覆盖不足）
  · A27：v5 四条改造（方案 C：内容决定，不是 system 决定）；2026-11-04 13:30 起训

训练监控铁律（仍有效）：任何训练必须同时起专职监控子 agent，
  每 10 分钟汇报 [MONITOR HH:MM] step=N loss=X lr=Y 步速=Zs/step 显存=a/r GiB 判定=绿/黄/红
```

### 13.2 双线文件分类（强制，2026-11-01 定稿）

```text
train/lines/9b-oxcoder/      9B 线（Qwen3.5-9B · 本机 12G 卡）
train/lines/27b-kittyrev/    27B 线（Qwen3.8-27B · 云端 GPU）
train/lines/_shared/         两线共享，只读
硬规则：不跨线写；产物落位固定；评测集隔离（9B 只用 9b-oxcoder/data/eval/**）；
       共享区只读；新增脚本带线前缀（9B: z_*/2b_*/p3_*；27B: gen3_*/local_*/convert_*/gsq_*）
路径真相源：from _dsh_paths import TRAIN, L9B, L27B, SHARED, M9B_DATA, M9B_OUT, M9B_MODELS
           （train/lines/_shared/scripts/_dsh_paths.py）
```

### 13.3 环境要点（仍有效）

```text
Python  ：C:\ProgramData\anaconda3\python.exe（3.13.9）—— PATH 里的 python 是 0 字节商店别名
PowerShell 7：C:\Program Files (x86)\PowerShell\7\pwsh.exe（PATH 内无 pwsh.exe，必须全路径）
CMake   ：_tools\cmake-4.1.2-windows-x86_64\bin\cmake.exe
CUDA    ：C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0
compute-sanitizer：<CUDA>\compute-sanitizer\compute-sanitizer.exe（不在 bin\）
                   实测 9B 引擎完全干净（无越界/无竞态/无未初始化读）
```

### 13.4 更新历史

```text
- 2026-11-08 00:05：本文件完全重写（操作者指令）。主体切换为 NInfer Windows 移植当前断点；
                    旧版 2622 行（A1–A27 + §1–§26）结论压缩到 §13，原文见 git 历史。
```
- 2026-11-08 20:30：**9B 交付形态成立** —— ①③④ 完成（15/15、对话、冷启 7s/TTFT 225ms）、
  ② 视觉链路打通（--vision + HTTP URL 图文问答可复现）；⑤ 34.4 tok/s，投机连破 7 层、
  最后一层 = GDN conv 的 27B 常量（kValueRows 6144 / kHidden 5120，三处 .cu）。
  引擎侧新增：tokenizer 缺字段早退、q8 swiglu 9B 形状、q8/bf16 projection 各 2-3 个形状、
  pair k=4096、gdn fold 32 层、mtp k∉{2048,5120} 回退非 pair。
  详见 `_work/ninfer-9b/TASKPOINT.md`（子任务级逐层记录）与 commit af914b6。
- 2026-11-08 22:00：**⑤ 投机链路打通并定性** —— 连破 13 层（pair k4096 / mtp attention 四合一 /
  q8 两形状 / bf16 一形状 / fold 24 层 GDN 几何 / slice 三处 / Q5 static K 三处 / split_bf16_features 几何），
  `--spec mtp` 可完整生成 192 token；但 `decode.rounds=191` 证明 MTP 接受率≈0，
  投机为负收益（31.4 vs 无投机 34.4）。结论：34.4 tok/s 是当前权重的天花板，
  突破需重训 MTP 头或换 dflash 权重。①③④② 全部完成并可用。
