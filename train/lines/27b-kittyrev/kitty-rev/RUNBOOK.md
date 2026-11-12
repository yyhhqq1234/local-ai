# RUNBOOK · kitty 逆向工作台能力后训练（可执行版）

> 目标模型：`ninfer-27b-kv-stream-3arch-20261019/model/Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer`
> 目标能力：**kitty 逆向工作台的项目级操作与行为纪律**（工具路由 / OP 语法 / 错误恢复 / 收口 / 成本收敛）
> 训练根：`train/lines/27b-kittyrev/kitty-rev/`（数据、契约、脚本、验收全在此；权重与大产物按 `train/README.md` 串行规则放 `train/`）

---

## 0 链路总图

```text
[只读] D:\DrCE(26.2.16)\kitty-toolbox\src\*.ts
   │  extract_contracts.mjs        ← 抽真实契约（64 工具 / 66 OP / 12 transition / 28 错误码）
   ▼  contracts/*.json
[本仓库] _work/session-audit/s*.jsonl
   │  harvest_sessions.py          ← 抽真实轨迹（s7–s11，21 正向 / 5 负向）
   ▼  data/real_sft.jsonl · real_neg.jsonl
   │  build_dataset.py             ← 契约模板 + 手写种子 + 真实轨迹 合成
   ▼  data/train.jsonl(171) · eval.jsonl(23) · dpo.jsonl(12) · stats.json
   │  train_kitty.py --stage sft   ← QLoRA（7 个 Linear，红线锁定）
   ▼  out/adapter
   │  train_kitty.py --stage dpo   ← 可选偏好对齐（beta=0.1）
   ▼  out/adapter-dpo
   │  ../scripts/merge.py → GGUF f16 → ninfer-v3 converter
   ▼  新 .ninfer（覆盖部署前先改名 .bak）
   │  eval/eval_kitty.py           ← 行为判据集（不是分数，是过/不过）
   ▼  logs/eval-<tag>.json
```

---

## 1 前置门槛（先判后跑，别先下 54 GB）

| # | 前置 | 判据命令 | 现状（2026-10-20 实测） |
|---|---|---|---|
| 1 | Python 3.12 + 训练栈 | `.\train\.venv\Scripts\python.exe -c "import torch;print(torch.cuda.get_device_capability(0))"` → `(12, 0)` | ✗ 未建（`.venv` 不存在） |
| 2 | bitsandbytes 0.50.2 win | `python -c "import bitsandbytes;print(bitsandbytes.__version__)"` | ✗ |
| 3 | transformers ≥5.8 | `AutoConfig` 能识别 `Qwen3_5ForConditionalGeneration` | ✗ |
| 4 | 全精度基座 | `train/lines/27b-kittyrev/base/Qwen3.8-27B/*.safetensors` 可加载 | ✗ 本地只有 `.ninfer`（推理产物） |
| 5 | ninfer-v3 converter | 能从 GGUF 产出可起引擎的 `.ninfer` | ✗ 本机已丢失（原 `D:\Ab1-Swift\engine\tools` 已删） |
| 6 | D 盘空间 | `Get-PSDrive D` | 执行前必查；27B 串行峰值 108 GB |
| 7 | 训练期停引擎/停同步 | 引擎占显存；百度网盘同步会打断大文件 | — |

**判定**：1–3 可装（`train/lines/_shared/scripts/setup_env.ps1`）；4 可下（54 GiB，hf-mirror）；**5 是整链唯一断点**——拿不到 converter，训完也回不到 `.ninfer`。

**因此实际推进顺序**：
```text
A. 现在：契约/数据/验收全部就位（已完成）→ 用 8B 基座验证数据与链路（不碰 27B）
B. 并行：确认 converter 来源（旧版引擎 tools 目录备份 / 上游 release / 自己重写 GGUF→ninfer 打包）
C. converter 到手：再下 27B 基座走全链
```

---

## 2 数据构造（已跑通，可重跑；当前 3040 条 / 48 DPO）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev

# ① 抽契约（只读 DrCE，写入本仓库 contracts/，零写入源目录）
node scripts\extract_contracts.mjs
# 期望：tools=64 ops=66 hot=10 transitions=12 errCodes=28  bridge=v0.2.9-open-name-resolve-fixed

# ② 精确轨迹（_work/session-audit 的 s*.jsonl）
& "C:\ProgramData\anaconda3\python.exe" scripts\harvest_sessions.py
# 期望：pos=21~23

# ③ 批量真实轨迹（~/.dsh/sessions 469 份存档，只读解帧）
& "C:\ProgramData\anaconda3\python.exe" scripts\harvest_bulk.py --prefix real_kitty
# 期望：pos=144 neg=3（含 kitty_* 调用，DrCE 为主）
& "C:\ProgramData\anaconda3\python.exe" scripts\harvest_bulk.py --require any --max-steps 20 --prefix real_disc
# 期望：pos=1014 neg=5（跨项目工具纪律）

# ④ 知识库扩产（先改 data/kb_re.jsonl 与 data/kb_tools.jsonl，再跑）
& "C:\ProgramData\anaconda3\python.exe" scripts\gen_kb.py
# 期望：kb_re_entries=55 kb_tool_entries=61 sft=510 dpo=23

# ⑤ 合成 + 裁剪 + 分组切分（写 data/large/）
& "C:\ProgramData\anaconda3\python.exe" scripts\run_expand.py --variants 8
# 期望：[shrink] kept=3040 dropped=448；train=2736 eval=304 dpo=48

# ⑥ 质检（不过不训）
& "C:\ProgramData\anaconda3\python.exe" scripts\validate_dataset.py --dir data\large --ctx 2048 --md logs\quality-latest.md
# 期望：VERDICT: PASS（struct/dup/contract/tool_call/over_ctx 全 0，eval 污染 0）
```

分布与分层见 [`README.md`](README.md) §2；质检明细见 `logs/quality-<date>.md`。

**数据体检**（`train_kitty.py` 内置；缺 `real-trajectory / op-syntax / tool-route / kb-re / kb-tool` 任一类直接退出）：
```powershell
& "C:\ProgramData\anaconda3\python.exe" scripts\train_kitty.py --size 8b --dry-run
```

---

## 3 训练

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev

# 3.1 环境（一次性，需联网；版本锁定见 docs/06 §5）
powershell -ExecutionPolicy Bypass -File ..\scripts\setup_env.ps1

# 3.2 基座（先 8B 验证链路，30 分钟级）
& ..\.venv\Scripts\python.exe ..\scripts\fetch_base.py --size 8b

# 3.3 冒烟 100 步（判据：loss 单调下降、无 NaN、无 OOM）
& ..\.venv\Scripts\python.exe scripts\train_kitty.py --size 8b --max-steps 100

# 3.4 正式 SFT
& ..\.venv\Scripts\python.exe scripts\train_kitty.py --size 8b --epochs 3

# 3.5 可选 DPO（在 SFT adapter 上继续）
& ..\.venv\Scripts\python.exe scripts\train_kitty.py --size 8b --stage dpo --sft-adapter out\adapter

# 3.6 27B（converter 确认后再做；ctx 512 + ga 32，offload 到 CPU，单步分钟级）
& ..\.venv\Scripts\python.exe scripts\train_kitty.py --size 27b --ctx 512 --ga 32
```

LoRA 红线（脚本内写死）：
```text
target_modules = q_proj k_proj v_proj o_proj gate_proj up_proj down_proj
禁止：gdn/a_log · gdn/dt_bias · gdn/convolution · gdn/a_projection · gdn/b_projection · gdn/norm · vision.*
```

---

## 4 回炉与部署

```powershell
# 4.1 合并（CPU，+54 GB，串行峰值）
& ..\.venv\Scripts\python.exe ..\scripts\merge.py --size 27b

# 4.2 转 GGUF f16（+54 GB）→ 确认 GGUF 可用再删 merged\
# 4.3 ninfer-v3 converter：GGUF → .ninfer（约 9–15 GB）
# 4.4 部署替换（先在部署目录改名，不删）
Rename-Item "...\model\Huihui-...-IQ2_S-mtp.ninfer" "Huihui-...-mtp.ninfer.bak"
Copy-Item "train\ninfer\<new>.ninfer" "...\model\Huihui-...-IQ2_S-mtp.ninfer"
# 4.5 起引擎验真：/v1/models 200 + 真实推理 finish=stop 即算通
```

**回滚**：起不来 → 删新文件 → `Rename-Item` 改回 `.bak` 原名 → 重启引擎（`ninfer-csunx\run-engine.ps1`）。

---

## 5 验收（对照 docs/03 §5）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev

# 基线（当前部署模型，未训练）
& "C:\ProgramData\anaconda3\python.exe" eval\eval_kitty.py --max-tokens 700 --out logs\eval-baseline-<date>.json

# 训后（adapter 合并部署后同一条命令，换 --model 或换部署名）
& "C:\ProgramData\anaconda3\python.exe" eval\eval_kitty.py --max-tokens 700 --out logs\eval-after-<date>.json
```

判据（脚本内 RULES 表，逐类）：

| 类别 | 过线条件 |
|---|---|
| tool-missing-escalate | 0 次工具调用 + 点明「不在可用集」+ 给确认路径 |
| contract-conflict | 0 次调用 + 明说「以 tools 列表为准」 |
| op-precision | 首个调用是 kitty_ce，S_NEW 带齐 4 段（vt/val/start/stop） |
| error-recovery* | 报错后首个动作是修正动作（OPEN / 取窗口 / 改 type），不是原样重试 |
| closeout | task-dispatch 含 `"type":"finish"` 且 evidence 非空 |
| cost-convergence | 调用 ≤1 + 明确停下汇报 |
| protocol-compression | 调用 ≤4 + 不整表复述（OP 行 <10） |
| spec-compliance | 汉字数达标或主动续写 |

**同时保留 docs/03 §5 的会话级指标**：同提示词 ≤10 步、p90 ≤15 步、无 abort、回读 ≤1 次。

---

## 6 红线

```text
磁盘  base / merged / gguf 三者任一时间最多并存两个；每阶段前 Get-PSDrive D
显存  27B QLoRA 必 offload；OOM 顺序：ctx 2048→1024→512 → 升 ga → 开 gradient_checkpointing
NaN   99% 是 LoRA 挂到 gdn.*（脚本已锁死 7 个 Linear）
同步  训练期退出百度网盘；train\{base,merged,gguf,hf,tmp} 加排除
写权限 只写 D:\BaiduNetdiskDownload\Local-AI\ 之内；DrCE 目录只读
引擎  训练前停引擎（占显存）；替换 .ninfer 前必须留 .bak
```

---

## 7 路径记录（不可用 / 已改道）

| 路径 | 状态 | 原因 | 改道 |
|---|---|---|---|
| 原地微调 `.ninfer` | ✗ | 引擎只有前向，容器是量化块+索引（99.5% 是量化张量） | 从 HF 基座训 |
| 从 `.ninfer` 反解 bf16 再训 | △ | 689 个量化张量不可逆，全模型近似 | 拉上游基座 |
| `s6/s9/s10` 全量当正样本 | ✗ | s9/s10 是 abort/1044 步事故；s6 无工具调用 | 只取 completed 且 ≤14 步（harvest 默认） |
| 直接对 27B 开训 | ✗ 当前 | 基座缺失 + 12 GB 显存必 offload + converter 缺失 | 8B 先验链路 |
| OpenAI 端点拉 chat 模板做 SFT | ✗ | 端点只出文本，不给 token 级标签 | 用 tokenizer.apply_chat_template 本地渲染 |

---

## 8 当前待办（按顺序）

```text
1. 确认 ninfer-v3 converter 来源（唯一硬断点）—— 找不到就别下 54 GB
2. 装训练环境（setup_env.ps1）+ 8B 基座，跑 --max-steps 100 冒烟
3. 冒烟通过后 jobs：8B 正式 SFT → eval 对比 → 决定是否上 DPO
4. 8B 验证数据有效后，再评估 27B 全链是否值得（时间成本按 offload 算）
5. 训练期把 data/ 增量补到 ≥1000 条（继续 harvest 新会话；DPO 对补到 ≥100）
```

---

## 9 复核命令（一条）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev; node scripts\extract_contracts.mjs; & "C:\ProgramData\anaconda3\python.exe" scripts\harvest_sessions.py; & "C:\ProgramData\anaconda3\python.exe" scripts\build_dataset.py --dry-run
```
