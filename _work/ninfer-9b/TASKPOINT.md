# TASKPOINT · ninfer 9B 五项验收（断点文件）

> 更新：2026-11-08 17:10 · 本文件是接续的唯一权威入口。新会话先读这里。

## 0 最终交付目标（五条，全部实测才可标 complete）

```text
① 内容正确：5 固定 prompt × 3 轮 = 15/15，无 NaN、无 HTTP 500，失败不进入 service_unavailable / 不挂死
② 多模态：--vision 启动后图片输入（base64 或 URL）走通 decode→image token→vision tower→文本输出，≥1 例图文问答
③ 可接入 DSH：plugins/dsh-ninfer-local 指向本地引擎，DSH 会话内完成一次真实对话（工具调用可后续）
④ 首 token 时延 <15s（冷启动后首个请求，T=0 到首字，实测计时）
⑤ 输出速度 ≥100 tok/s（decode，192+ token 连续生成实测均值）
```

## 1 当前状态（实测）

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

## 2 版本选型结论（操作者确认 + 本地核查）

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

## 3 G1 重建链路（四件套齐备，属"按分配重放量化"而非找备份）

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

## 4 已完成的引擎修复（均已 push）

```text
7e81e48  修 13–15 token 的 K/V 段 NaN（linear_split n5120_n5120_k4096 阈值 <=15）
8973a04  打通 CUDA graph（15.3 → 36.2 tok/s），根因是 9B MLP swiglu dispatch 里未关闭的 cudaDeviceSynchronize
c6faf4b  采样空候选不再 device trap（原 asm volatile("trap;") 会打死进程）
9aa848f  grammar 约束失败降级（带 tools 请求不再 500 崩进程）
c696d37 / 38edf1d / c812a16 / 8438297 / 408a2f5 / 5009b69 / 080d134 / 139ac41
         诊断开关收尾 + 病灶证据（L03/proj_k，T=263）+ 可用配置 + STATE 系列
```

## 5 已否证的方向（勿重试）

```text
· ⑤-A「k4096 swiglu GEMV-pair kernel」：GEMV 不减少权重读取量；5.81 GiB/token 是物理下限，
  100 tok/s 需 ≈581 GB/s；且 4 并发聚合实测 34.7 tok/s（引擎串行）→ 作废
· shape.cpp 阈值扩到 <=512 全走小路径 → 长 prompt 仍 NaN
· --prefill-chunk 256 → 长 prompt 仍 NaN（必须 ≤128）
· --no-prefix-reuse / --prefill-chunk 64 → 均无效
· grammar 词表/掩码宽度错配、采样踩 padding、decode 掩码全 0 → 逐一被代码或实测否掉
```

## 6 纪律

```text
· 只写 D:\BaiduNetdiskDownload\Local-AI 内；不动禁删清单（权重/引擎/.venv/adapter/审计资产）
· 改 .cu/.cuh 后必须删对应 .obj 再重编（Ninja 不跟踪头文件）
· 每次只改一处 → 重编 → 对比；诊断代码用编译期开关关死
· 大件（>1GB）生成或删除前先报体积与用途
· 备份：small.cu.bak-5a / launch.h.bak-5a / dispatch.cpp.bak-5a 在位（ninfer-master 不在 git 里）
```

## 7 接续第一动作

```text
读 out\b4-allocation.json + _shared\scripts\p1_requant.py 的 CLI → 报磁盘余量 → 重放 G1 → 注入 step300 MTP
→ --components text,mtp 转产物 → --spec mtp --draft-tokens 3 实测 ⑤
② 另需视觉塔权重（本地无 visual.*），从对应 HF 仓库取 1–2 GB 分片后与 G1 目录合并再转。
```

## 2026-11-08 18:52 · G1 产物落地（重大更新）

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
