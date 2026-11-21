# 9B GGUF 量化方案对比（2026-11-21）

> 目标：不局限 Q5_K_M，选「本机 12 GB 显存 + 中文 + 工具/创作双能力」下的最优点。
> 结论先行：**主推 Q6_K（近无损）**，**次选 Q5_K_M + imatrix**（省显存），**备选 IQ4_XS + imatrix**（最省）。
> 关键增益来自 **imatrix（重要度矩阵）**，不是换字母。

## 1 可选类型（本机 llama-quantize 支持）

| 类型 | bpw | 体积(9B 估) | 相对困惑度 | 备注 |
|---|---|---|---|---|
| Q8_0 | 8.5 | ~9.6 GB | +0.0026 | 12 GB 卡跑长上下文会挤，需实测 |
| **Q6_K** | 6.56 | ~7.2 GB | **+0.0217** | 近无损，显存留 4 GB 给 KV |
| Q5_K_M（现用） | 5.77 | ~6.2 GB | +0.0569 | 基线 |
| Q5_K_M + imatrix | 5.77 | ~6.2 GB | ≈+0.03 | 同体积质量提升，推荐 |
| Q5_K_S + imatrix | 5.4 | ~5.8 GB | ≈+0.06 | 更省 |
| IQ4_XS + imatrix | 4.25 | ~4.7 GB | ≈+0.15 | 最省，长上下文友好 |
| Q4_K_M + imatrix | 4.58 | ~5.0 GB | ≈+0.12 | 通用备选 |
| IQ3_M / TQ2_0 | 3.66 / 2.06 | 3.9 / 2.2 GB | 明显下降 | 本任务不推荐（中文创作与工具 schema 最怕降精度） |

## 2 为什么不是只看 bpw

```text
① 中文 + 工具 JSON + 创作文风，对 4bit 以下极敏感：JSON 键名、标点、引号最易崩
   → 不要为了省 1 GB 掉到 IQ3/TQ
② imatrix 用「真实校准语料」算每层重要度，同 bpw 下明显优于裸 K-quant
   校准集必须覆盖三类分布：kitty 工具轨迹 / NSFW 正文 / 普通问答
③ 输出层与 embedding 单独提精度（--output-tensor-type q6_k --token-embedding-type q6_k）
   小模型上这一步收益高于整体升一档
```

## 3 投产方案（三档并列跑，按验收选）

```text
A 主推  Q6_K + (output/embedding = Q6_K)
   体积 ~7.2 GB，显存余量够 ctx 32K；
   预期：创作与工具调用都与 bf16 无感差，作为「质量优先」默认。

B 次选  Q5_K_M + imatrix + (output/embedding = Q6_K)
   体积 ~6.3 GB；同体积下比裸 Q5_K_M 好，作为「显存优先」默认（长上下文 128K）。

C 备选  IQ4_XS + imatrix
   体积 ~4.8 GB；只在需要 128K 上下文或多并发时用。
```

三档产物命名：

```text
models/9b/gguf/kittyrev9b-b1-Q6_K.gguf
models/9b/gguf/kittyrev9b-b1-Q5_K_M-imx.gguf
models/9b/gguf/kittyrev9b-b1-IQ4_XS-imx.gguf
```

## 4 imatrix 校准集（用自有语料，不抄通用文本）

```text
来源（清洗后）：
  kitty  train/lines/9b-oxcoder/data/kitty-reverse/cleaned/kitty-clean-v3.jsonl  （工具/参数面）
  nsfw   train/lines/9b-oxcoder/data/nsfw-gated/cleaned/nsfw-clean.jsonl           （创作文风，取 permit）
  dsh    train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl + dsh-clean      （格式/协议）
做法：抽 300–500 条，只取 assistant 正文拼成纯文本（每行一条），约 400 KB–1 MB
命令：llama-imatrix -m <bf16.gguf> -f calib.txt -o imatrix-b1.dat --chunks 200 -ngl 99
```

## 5 验收（三档同一套探针，量化后必须复测）

| 项 | 判据 | 工具 |
|---|---|---|
| 困惑度 | 在自有 eval 文本上比 bf16 劣化 ≤3%（Q6_K）/ ≤6%（Q5+imx）/ ≤12%（IQ4_XS） | `llama-perplexity` |
| 工具调用 | 10 道任务 ≥9/10 正确工具名 + 合法 action + 必填齐 | `_work/rebuild/verify_new_gguf.py` |
| 创作 | 3 段露骨词 ≥5 词/段、无拒答、不重开 | 同上 |
| 基础 | 5/5（算术/事实/JSON 原样/翻译/代码） | 同上 |
| 稳定性 | 同题 5 次输出不退化（3-gram 复读峰值 <0.4） | 自写脚本 |
| 显存 | ctx 32K 下 < 11 GB；128K 下不 OOM（仅 B/C 需测） | `nvidia-smi` |

## 6 执行顺序（训练结束后自动串）

```powershell
# 1) 合并 LoRA → bf16（训练完第一步）
train\.venv\Scripts\python.exe train\lines\_shared\scripts\local_merge_lora.py `
  --base train\lines\9b-oxcoder\models\OxCoder-9B `
  --adapter train\lines\9b-oxcoder\out\b1-oxcoder-nsfw-kitty\adapter `
  --out train\lines\9b-oxcoder\models\b1-merged

# 2) bf16 GGUF
train\.venv\Scripts\python.exe train\lines\_shared\tools\lc\convert_hf_to_gguf.py `
  train\lines\9b-oxcoder\models\b1-merged --outfile models\9b\gguf\kittyrev9b-b1-bf16.gguf --outtype bf16

# 3) imatrix（一次，三档共用）
engines\llama-cpp\llama-bin\llama-imatrix.exe -m models\9b\gguf\kittyrev9b-b1-bf16.gguf `
  -f _work\quant\calib-b1.txt -o _work\quant\imatrix-b1.dat --chunks 200 -ngl 99

# 4) 三档量化
llama-quantize --imatrix _work\quant\imatrix-b1.dat <bf16> <out-Q5_K_M-imx> Q5_K_M 16
llama-quantize --imatrix _work\quant\imatrix-b1.dat <bf16> <out-IQ4_XS-imx> IQ4_XS 16
llama-quantize <bf16> <out-Q6_K> Q6_K 16

# 5) 逐档验收（§5 六项）→ 选定默认档
```

## 9 硬指标：上下文 64K–256K + 输出 ≥50 tok/s（2026-11-21 追加）

**KV 账（Qwen3.5-9B 混合注意力：32 层里 8 个 full-attn，4 KV heads × 256 head_dim）**
```
f16 KV : 32 KB/token  → 64K=2.0 GiB / 128K=4.0 / 256K=8.0
q8_0 KV: 16 KB/token  → 64K=1.0 / 128K=2.0 / 256K=4.0
```

**装得下（权重 + KV + 0.8 GiB 预留 ≤ 12.2 GiB）**
| 权重档 | 64K f16 KV | 64K q8 KV | 256K f16 KV | 256K q8 KV |
|---|---|---|---|---|
| Q5_K_M(6.19) | 8.99 OK | 7.99 OK | 14.99 超 | 10.99 OK |
| Q5_K_M+imx(6.3) | 9.10 OK | 8.10 OK | 15.10 超 | 11.10 OK |
| Q6_K(7.2) | 10.00 OK | 9.00 OK | 16.00 超 | 12.00 临界 |
| IQ4_XS(4.8) | 7.60 OK | 6.60 OK | 13.60 超 | 9.60 OK |

**速度上限估算（内存带宽约束，笔记本 5070Ti ≈ 260 GB/s）**
```
每 token 需读全部权重：Q6_K 7.2GB → ≤36 tok/s；Q5_K_M 6.19GB → ≤42；
IQ4_XS 4.8GB → ≤54；Q4_K_M 5.0GB → ≤52
→ 要 ≥50 tok/s，权重必须 ≤5 GB 级（IQ4_XS / Q4_K_M），且上下文越长注意力开销越大
```

**结论（待实测确认）**
```
A 64K 上下文 + ≥50 tok/s  ：IQ4_XS + imatrix（KV q8_0）  ← 速度优先默认
B 256K 上下文             ：IQ4_XS + imatrix（KV q8_0）
                            装得下，但长上下文解码必然 <50 tok/s（注意力成本主导），
                            实测后给出 32K/64K/128K/256K 的 tok/s 曲线
C 质量优先（≤64K）        ：Q5_K_M + imatrix（KV f16），速度约 40 tok/s 级
D 近无损但仅短上下文      ：Q6_K，速度 ~35 tok/s，不满足 50
```

**基准脚本**：`_work/quant/bench_ctx.ps1`（64K f16/q8、128K q8、256K q8 各测一次，输出 tok/s + 显存）

## 10 优先级定版（2026-11-21）：质量与上下文优先，速度后续优化

**取舍**：不再为 50 tok/s 让精度。量化档按「上下文覆盖率 + 质量」排，速度后置。

**两张投产配置**
```
① 默认（覆盖 256K 全上下文）
   Q5_K_M + imatrix + KV q8_0   → 6.3 + 4.0 + 0.8 = 11.1 GiB
   支持 32K/64K/128K/256K；质量≈Q5_K_M 上 imatrix 增益；速度推定 35–45 tok/s

② 质量优先（≤64K 短上下文）
   Q6_K + KV f16                → 7.2 + 2.0 + 0.8 = 10.0 GiB
   近无损（相对 bf16 +0.02 ppl 级），速度推定 30–35 tok/s

③ 备选（要 256K 又要 Q6_K）
   Q6_K + KV q4_0               → 7.2 + 2.0 + 0.8 = 10.0 GiB
   KV 用 q4 换出 2 GiB 空间；长文场景 KV 精度损失小于权重降档
```

**降级档（只在速度成为瓶颈时才用）**
```
IQ4_XS + imatrix + KV q8_0     → 9.6 GiB / 256K，速度 ~50 tok/s，但权重精度掉一档
```

**验收顺序调整**
```
1) 困惑度（自有 eval 文本，bf16 为基准）
2) 三能力探针（工具 10 / 创作 3 / 基础 5 / 复读）
3) 上下文实测：32K / 64K / 128K / 256K 各跑一次，确认不 OOM、不裂化（长文召回测试）
4) 速度只记录不设门（后续优化项）
```

**训练侧不变**：LoRA r=64 保留（质量优先），显存贴顶但已有 checkpoint-50 落盘、可 --resume 续训。

## 11 KV 定档 q4_0（2026-11-21 操作者指令）→ 量化改为主推 Q6_K

**KV q4_0 预算**（4.5 bpw ≈ 0.5625 B/元素）
```
q4_0  9.0 KB/token  → 32K=0.28  64K=0.56  128K=1.12  256K=2.25 GiB
q8_0 16.0 KB/token  → 256K=4.00 GiB（原方案）
f16  32.0 KB/token  → 256K=8.00 GiB（不可行）
```

**装得下（权重 + KV q4_0 + 0.8 GiB 预留 ≤ 12.2）**
| 权重 | 64K | 256K |
|---|---|---|
| Q6_K 7.2 | 8.56 ✅ | **10.25 ✅** |
| Q5_K_M+imx 6.3 | 7.66 ✅ | 9.35 ✅ |
| Q5_K_M 6.19 | 7.55 ✅ | 9.24 ✅ |

**定版**
```
主投  Q6_K + KV q4_0             → 256K 全上下文可行，质量近无损（首选）
备选  Q5_K_M + imatrix + KV q4_0 → 余量更大（9.35 GiB），速度略好，质量低半档
淘汰  Q8_0 / f16 KV（256K 装不下）；IQ4_XS 降为速度应急档
```
**启动参数**：`-ctk q4_0 -ctv q4_0 -c 262144 -ngl 99 -fa on --jinja --reasoning-format none`

**基准脚本已改为 q4_0 四档**：32K / 64K / 128K / 256K，各测 tok/s + 显存

## 12 b1 模型验收实测（2026-11-21 03:30 · Q6_K）

**训练结果**
```
419 步 / 1 epoch / runtime 3942s（9.41 s/step）
train_loss 2.062（末记录 2.038，best 1.7404@step255），token acc 峰值 0.676
adapter: train/lines/9b-oxcoder/out/b1-oxcoder-nsfw-kitty/adapter
```

**产物**
```
models/9b/gguf/kittyrev9b-b1-bf16.gguf   16.69 GB
models/9b/gguf/kittyrev9b-b1-Q6_K.gguf    6.85 GB   ← 主投
（Q5_K_M-imatrix 未生成：imatrix 在 12G 卡上对 16.7GB bf16 直接失败，需 -ngl 0 跑 CPU）
```

**四项实测（Q6_K + KV q4_0）**
| 项 | 结果 | 判据 |
|---|---|---|
| 基础 5 题 | **5/5** | ≥4 |
| 工具 10 题（system 与训练一致，剥 think） | **4/10** | ≥8 |
| 创作 3 段（零起点） | **0/3** | ≥2 |
| 复读 3-gram | 0.019 | <0.40 |
| 32K 召回 | **3/3 PASS** | 3/3 |
| 64K 召回 | **3/3 PASS**（17.9s/次） | 3/3 |
| 128K 召回 | **3/3 PASS**（45s/次） | 3/3 |
| 256K 召回 | **3/3 PASS**（126s/次，290K 字符） | 3/3 |
| 解码速度 | **54.7 tok/s**（ctx16K，显存 6878 MiB） | ≥50 |
| 预填速度 | ≈2300–3050 tok/s | — |

**两个短板与根因**
```
① 工具 4/10：命中 read/write/ops_glob/kitty_ce；
   错配：数 md 文件→ops_glob、搜文本→kitty_find、改文件→read、
        锁目标→kitty_rea_call_path、反编译→kitty_rea_function、三视图→kitty_ce
   根因：kitty 侧样本里 kitty_rea_* 曝光多（233 行 adapt 里 r ea 系占位高），
         且 ops_bash/ops_grep/edit/kitty_settings 的「同义任务」样本不足
② 创作 0/3（零起点）：模型只输出暧昧向；但续写式（给露骨开头）3 例中 2 例达标（5 词/5 词），1 例退回暧昧
   且 #1 出现 ❤ 刷屏退化（连续 emoji 重复）
   数据侧核验：permit 5604 行平均 12.4 个露骨词、57.2% ≥5 词 → **数据本身没问题**
   判断：能力已学到但被"零起点"分布限制 + 退化样本未清洗
```

**下一步（三条，按优先级）**
```
1) 数据补两处：① 零起点露骨开场样本（200–400 条，同一 system）② 工具同义任务多样性（edit/ops_bash/ops_grep/kitty_settings 各 50+）
2) 清洗退化：过滤连续 emoji/符号重复（❤❤❤ 刷屏）的 nsfw 行
3) 补 imatrix：用 -ngl 0 CPU 跑 64 chunks，产 Q5_K_M-imx 备份档（不影响主投）
```

## 13 v3 数据优化与重训（2026-11-21 11:36）

**两个子 agent 交付（已抽查核验，非仅采信汇报）**
```
工具线 (tool-opt)
  tool-neighbor.jsonl  149 行  7 组易混对，唯一率 100%，格式坏 0
  tool-synonym.jsonl   338 行  ops_grep/edit/write/read 各 50、ops_bash/kitty_settings 各 47、ops_glob 44
  kitty-downsampled    10534 行（原 11441）
  分布结论修正：kitty_rea 家族 8.0% 未超线；真正超线的是 kitty_ce 24.4% → 降到 15%（比例 0.546）
  发现幻觉名 kitty_find（清单无此工具）、错拼 kitty_rea_call_path（正确 callpath）→ 已入 A 组纠正样本

NSFW 线 (clean/opt)
  nsfw-zeroshot.jsonl  800 行 / 800 唯一 / 露骨词均值 20.0 / ≥5 词 100% / 均 1354 字
  nsfw-clean-v2.jsonl  8113 行（permit 4284 + regular 3829），剔除退化 1312 行（23.4%）
    剔除原因：REPEAT_5GRAM 723 / INTERJ_RUN 481 / CHAR_RUN8 292 / TILDE_RUN 169 / HEART_RUN 157 / 其它 63
  方法引用：Tülu 3（多样性配比）、Lee et al. ACL2022（近重去重）、LIMA（质量>数量）、Entropy Rate Filtering（低熵重复→崩塌）
```

**v3 混配（train-b1-v3-s.jsonl）**
```
kitty 1800（下采样后）+ tool 974（487×2）+ dsh 880（440×2 问法）+ nsfw 2800（零起点 800 + 常规≥5词 2000）
= 6454 行 / 5.65M 字符 / 估 4.19M token
零起点占 nsfw 28.6%（>子 agent 建议的 15.7%，一次到位；若续写回退再回调到 12%）
```

**训练（11:34:34 起，PID 8496）**
```
日志 train/logs/b1v3-train-20261121-1134.log
[kbit] 标志已出现；显存 8936 MiB / 12227（比 b1 的 9018 更低，因数据更短）
输出 out/b1v3-oxcoder-nsfw-kitty（新目录，b1 产物不动）
ctx768 packing bs1 ga8 lr5e-5 r64 α128 save_steps25 fraction0.85
```

**验收链（已挂 waiter，PID 16472）**
```
merge → bf16 → Q6_K → 三能力(verify_tiers) → NSFW 20条零起点+3条续写(verify_nsfw)
→ 64K/256K 召回(verify_longctx) → 落 train/logs/post-v3-chain-*.log
判据：零起点 ≥5 词通过率 ≥70%（14/20）；续写 3/3 不复退；工具 ≥8/10；基础 ≥4/5；召回 3/3+3/3
```

## 14 b1v3 验收实测（2026-11-21 13:00）

**训练**
```
452 步 / 1 epoch / 4190s（9.27 s/step）· train_loss 2.416（末步 2.172）
token 实喂 2.746e6（ctx768 截断 + packing；原估 4.19M，差 34% —— nsfw 行均值 1354 字≈1000+ token，被截掉尾部）
adapter: out/b1v3-oxcoder-nsfw-kitty/adapter（232.8MB）
产物: models/9b/gguf/kittyrev9b-b1v3-Q6_K.gguf 6.85GB
```

**五项实测 vs b1**
| 项 | b1 | b1v3 | 判定 |
|---|---|---|---|
| 基础 5 | 5/5 | **5/5** | 保持 |
| 工具 10 | 4/10 | **10/10** | **达标（+6）** |
| 零起点 NSFW 20 条 | 0/20 | **11/20 = 55%** | 未达 70% |
| 续写回归 3 条 | 2/3 | **1/3** | 回退 |
| 复读 3-gram | 0.019 | 0.008 | 好 |
| 64K / 256K 召回 | 3/3 / 3/3 | **3/3 / 3/3** | 保持 |

**失败诊断（关键，决定下一轮怎么做）**
```
同一 prompt 连测 3 次（t0.85×2 + t0.70）：
  "写个室内场景，两个人" → 0 / 0 / 30 词
  "都市夜色"            → 8 / 43 / 84 词
  "酒店房间"            → 76 / 53 / 0 词
  "门口到床上"          → 0 / 58 / 0 词
结论：**不是 prompt 固有失败，是双峰随机** —— 每次采样要么走露骨分支（50–85 词），要么走言情分支（0–12 词），
      概率约各半。属分布问题（先验未压过基座的安全风格），不是能力缺失。
```

**两个已验证的杠杆**
```
① 显式 prefill（把首句锁进身体描写）：8 条难 prompt 通过率 50% → 62.5%（5/8），有效但不够
② ctx768 截断吃掉 34% token，而 nsfw 正文均值 1354 字 → 露骨尾部被截掉 → 下轮 ctx 提到 1024
```
