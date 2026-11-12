# REASONING-DATA · 开源推理链（CoT）数据集清单与取用方案

> 目的：本地 27B IQ2 的短板里有一条是「思考链质量」——长度失控、空转、不收敛。
> 开源推理链数据可以补「怎么一步步把问题拆开并自我检查」，但要按体量与许可筛选，不能整包倒。
> 所有 HF id 已于 2026-10-21 用 `hf-mirror.com/api/datasets?search=` 实测存在（带下载量）。

---

## 1 数据集清单（按用途分组，全部已验证）

### A 通用推理链（教学质量最高，优先）

| 数据集 | HF id | 体量 | 下载 | 许可 | 用途 / 判断 |
|---|---|---|---|---|---|
| OpenThoughts-114k | `open-thoughts/OpenThoughts-114k` | 114k | 90.5k | Apache-2.0 | **首选**。114k 精筛数学/代码/科学 CoT，DeepSeek-R1 生成，长度适中 |
| OpenThoughts3-1.2M | `open-thoughts/OpenThoughts3-1.2M` | 1.2M | 22.7k | Apache-2.0 | 备选。体量大、需重度采样；适合做「多样性」而非全量 |
| Bespoke-Stratos-17k | `bespokelabs/Bespoke-Stratos-17k` | 17k | 26.5k | Apache-2.0 | **首选**。带「思考→自我修正」结构，1.7 万条覆盖数学+代码，风格接近我们要的「收敛」 |
| LIMO | `GAIR/LIMO` | 817 | 21.6k | Apache-2.0 | **必看**。817 条就打出强推理，证明「少而精 + 结构化 CoT」有效，适合做种子 |
| s1K | `simplescaling/s1K` | 1k | 8.2k | Apache-2.0 | 同 LIMO 思路（1k 精选 + 测试时扩展），用于风格对齐 |
| OpenR1-Math-220k | `open-r1/OpenR1-Math-220k` | 220k | 117k | Apache-2.0 | 数学主粮，R1 轨迹，含 verify 字段便于筛正确性 |
| NuminaMath-CoT | `AI-MO/NuminaMath-CoT` | 860k | 245k | Apache-2.0 | 数学基础盘，CoT 较短，适合「别啰嗦」的对照 |
| NuminaMath-TIR | `AI-MO/NuminaMath-TIR` | 72k | 6.1k | Apache-2.0 | **工具调用 + 推理**混合（TIR=工具集成推理），与 kitty 场景最接近 |
| OpenMathReasoning | `nvidia/OpenMathReasoning` | 3.2M | 73.6k | CC-BY-4.0 | 大体量备选，含多解/多轮，需筛 |

### B 代码 / 工程推理（对逆向最有用）

| 数据集 | HF id | 体量 | 下载 | 许可 | 判断 |
|---|---|---|---|---|---|
| OpenCodeReasoning | `nvidia/OpenCodeReasoning` | 736k | 12.3k | CC-BY-4.0 | 代码 CoT + 解题链，**最贴合「逆向=读代码推理」** |
| OpenCodeReasoning-2 | `nvidia/OpenCodeReasoning-2` | 更大 | 6.2k | CC-BY-4.0 | 二代，质量筛选更严 |
| codeforces-cots | `open-r1/codeforces-cots` | 数十万 | 5.3k | Apache-2.0 | 竞赛题推理链，难度高、链长 |
| codeforces | `open-r1/codeforces` | 题面+测试 | 59.7k | Apache-2.0 | 出题+判题配套用 |

### C 工具调用 / Agent（补 kitty 场景）

| 数据集 | HF id | 体量 | 下载 | 许可 | 判断 |
|---|---|---|---|---|---|
| ToolACE | `Team-ACE/ToolACE` | 11k | 36.9k | Apache-2.0 | 工具定义+调用链，格式规范，**补「选工具/给参数」** |
| xLAM function-calling | `Salesforce/xlam-function-calling-60k` | 60k | 19.9k | CC-BY-4.0 | 函数调用大合集，含多轮与错误处理 |
| Magpie-Pro-300K | `Magpie-Align/Magpie-Pro-300K-Filtered` | 300k | 3.8k | Apache-2.0 | 通用指令多样性（防能力退化），少量混入即可 |

### D 蒸馏型（谨慎用）

| 数据集 | HF id | 判断 |
|---|---|---|
| AM-DeepSeek-R1-Distilled-1.4M | `a-m-team/AM-DeepSeek-R1-Distilled-1.4M` | 1.4M 全蒸馏。**只做小比例抽样**，否则会把「别人的思考腔调」整体搬进来，和我们的工作纪律冲突 |

---

## 2 用量判断（重要，别整包倒）

| 目标 | 数据量 | 理由 |
|---|---|---|
| 让模型「会分步 + 会自检」 | 5k–15k 条高质量 CoT | LoRA 学的是模式不是知识；超过 50k 边际收益极低 |
| 保持通用能力不退化 | 混 5%–10% 通用指令（Magpie 抽样） | 纯领域数据会让模型在其他任务上「变傻」 |
| 与 kitty 场景配比 | 我们的数据 60% : 推理链 30% : 通用 10% | 主线仍是工作纪律，推理链是「思考方式」的补丁 |

**长度约束**：我们的训练 ctx 是 2048（27B offload 时更低到 512–1024）。CoT 数据集里大量样本 > 8k token，必须按 token 截断或直接丢弃 —— 统计见 `fetch_reasoning.py --stats`。

---

## 3 许可与合规

```text
Apache-2.0 / CC-BY-4.0：可商用、可二次分发，保留出处即可
蒸馏型（R1 生成）：数据本身可训练，但产出模型不要再声称「自研推理能力」；内部使用没问题
不要用：来源不明、带个人隐私、或明确禁止训练的数据集
落盘一律在 D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\data\reasoning\ 内，不入库（.gitignore 已排除）
```

---

## 4 取用流水线（脚本已就位）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev

# 4.1 拉样本（走 hf-mirror + datasets-server rows API，不装 datasets 也能跑）
& "C:\ProgramData\anaconda3\python.exe" scripts\fetch_reasoning.py --list
& "C:\ProgramData\anaconda3\python.exe" scripts\fetch_reasoning.py --dataset open-thoughts/OpenThoughts-114k --limit 4000 --out data\reasoning\openthoughts-4k.jsonl

# 4.2 体检：长度分布 / 去重 / 与自有 eval 的污染检查
& "C:\ProgramData\anaconda3\python.exe" scripts\fetch_reasoning.py --stats data\reasoning\openthoughts-4k.jsonl

# 4.3 混入训练集（60/30/10 配比，输出到 data\large-mix\）
& "C:\ProgramData\anaconda3\python.exe" scripts\mix_reasoning.py --base data\large --reason data\reasoning --ratio 0.3 --out data\large-mix
```

判据：
```text
每条样本 est_tokens ≤ 1500（与主集一致）
去重后重复率 < 2%
与 eval/bench 题目 40 字前缀零重叠
混合后总量 ≈ 主集 / 0.7
```

---

## 5 现成清单落地位置

```text
train/lines/27b-kittyrev/kitty-rev/data/reasoning/        下载的推理链样本（不入库，已 gitignore）
train/lines/27b-kittyrev/kitty-rev/scripts/fetch_reasoning.py   抓取 + 体检（datasets-server 免依赖）
train/lines/27b-kittyrev/kitty-rev/scripts/mix_reasoning.py     按配比混入主训练集
train/lines/27b-kittyrev/kitty-rev/REASONING-DATA.md            本文件（清单与判断）
```

---

## 6 一句话建议

```text
先用 OpenThoughts-114k 抽 4k + Bespoke-Stratos-17k 抽 3k + LIMO 全量 817 + OpenCodeReasoning 抽 3k
≈ 1.1 万条推理链，混入 60/30/10 配比，ctx 截到 1500 token 以内。
这比「下载 1.2M 全量」更可能训出我们要的「短而准、会自检」。
```

---

## 7 实测：这些数据在 ctx 2048 下能留下多少（关键）

用 `fetch_reasoning.py` 实抓实测（上限 1500 token，超出即丢）：

| 数据集 | 取样 | 保留 | 保留率 | 结论 |
|---|---|---|---|---|
| GAIR/LIMO | 817（全量探测） | 46 | **5.6%** | 推理链极长，1500 上限几乎全废 |
| open-thoughts/OpenThoughts-114k | 300 | 2 | **0.7%** | 平均 2k–8k token，ctx 2048 装不下 |
| AI-MO/NuminaMath-CoT | 120 | 120 | **100%** | p50 仅 304 token，**ctx 2048 下的最优选择** |
| GAIR/LIMO（`--truncate headtail`） | 150 | 150 | 100%（140 条被截） | 保头 60%+尾 40%，带「中段已省略」标记 |

**结论（决定训练参数）**：
```text
① ctx 2048：主用短 CoT 源（NuminaMath-CoT / TIR / ToolACE / xLAM），长 CoT 只在 reason 目录里做对照
② 想让 OpenThoughts/LIMO 这类长链真正可用 → ctx 必须 ≥4096（8B 可行；27B offload 下代价高）
③ 折中：--truncate headtail，学「起手+结论」而不是学「中段复读」，与我们的「短而准」目标一致
```

---

## 8 前沿模型思维链蒸馏（Opus5.5 / GPT6Astra / Grok4.7 / DSV4Pro / K3）

管线已就位：`scripts/distill_cot.py` + `distill/routes.json` + `data/reasoning/seeds.jsonl`
（300 条任务提示，取自 gold 层 9 个类别：轨迹/反例/知识/错误恢复/收口/指针链/双视图/收敛/压缩）。

```powershell
# ① 探活（不花 token）：逐路由打 /models，判定 OK / BAD-KEY / NO-ENDPOINT / NO-KEY
& "C:/ProgramData/anaconda3/python.exe" scripts/distill_cot.py --probe --all

# ② 单路由蒸 200 条（key 从环境变量取）
$env:DEEPSEEK_API_KEY = "<key>"
& "C:/ProgramData/anaconda3/python.exe" scripts/distill_cot.py --gen --route dsv4pro --seeds data/reasoning/seeds.jsonl --out data/distill/dsv4pro.jsonl --limit 200 --max-tokens 2048

# ③ 五路由全跑（各自一个文件，断点续跑）
& "C:/ProgramData/anaconda3/python.exe" scripts/distill_cot.py --gen --routes all --seeds data/reasoning/seeds.jsonl --out data/distill --limit 200 --resume

# ④ 体检 + 合并（超长可截断）
& "C:/ProgramData/anaconda3/python.exe" scripts/distill_cot.py --stats data/distill/dsv4pro.jsonl
& "C:/ProgramData/anaconda3/python.exe" scripts/distill_cot.py --merge --dir data/distill --out data/reasoning/distilled.jsonl --max-tokens 1500 --truncate
```

**当前探活结果（2026-10-21 实测）**：
```text
opus5.5 / gpt6astra / grok4.7 / dsv4pro / k3 / local-ninfer  →  全部 NO-KEY
原因：这些 key 存在 DSH 凭据库里（refs 名：DEEPSEEK_API_KEY / OPENCODE_API_KEY / COMMANDCODE_API_KEY /
      NVIDIA_API_KEY / ZAI_API_KEY / DASEINAI_API_KEY），但**没有导出到 shell 环境**。
两条可走的路：
  A. 操作者把对应 key 导出为环境变量（或把 routes.json 的 base_url/model 改成实际可用值），再跑 --gen
  B. 走 DSH 自身已配置的网关（本会话的 opencode-go / commandcode-goat 路由），
     由 DSH 侧发起调用；此时不用 distill_cot.py，而用 AgentTeams 成员指定 model/provider 跑批量任务
```

**蒸馏纪律**：
```text
1 只蒸我们自己的任务提示（seeds 来自 gold 层），不蒸通用题库——否则学生学到的是教师的口头禅
2 reasoning 字段单独保留（meta.hasReasoning），训练时可按需并入或拆成 reasoning 段
3 同一教师同一 prompt 只留一条；跨教师对比用同一 seeds，便于按一致性过滤
4 蒸馏数据占比 ≤30%，主粮仍是自有契约/轨迹/知识数据
5 产出模型不得对外声称具备教师模型的能力（合规底线）
```

---

## 9 能力测试集（主流开源基准）

清单与字段映射：`eval/bench/manifest.json`（16 个集，hf_id 全部实测存在）
抓取：`eval/bench/fetch_bench.py`（走 datasets-server，免装 datasets）
运行：`eval/bench/run_bench.py`（OpenAI 兼容端点，按 type 判分）

```powershell
# 看清单
& "C:/ProgramData/anaconda3/python.exe" eval/bench/fetch_bench.py --list

# 抓子集（已实测通过：MMLU-Pro 20 / GSM8K 20）
& "C:/ProgramData/anaconda3/python.exe" eval/bench/fetch_bench.py --set MMLU-Pro --limit 200 --out eval/bench/data/MMLU-Pro.jsonl
& "C:/ProgramData/anaconda3/python.exe" eval/bench/fetch_bench.py --set all --limit 50

# 跑（引擎起来后）
& "C:/ProgramData/anaconda3/python.exe" eval/bench/run_bench.py --data eval/bench/data --limit 50 --base http://127.0.0.1:1234 --model qwen3.8-27b-ablit-swift15-iq2s --out eval/bench/logs/bench-baseline.json
```

覆盖：MMLU-Pro / GPQA-Diamond / GSM8K / MATH-500 / AIME25 / HumanEval / MBPP / LiveCodeBench-lite /
IFEval / BBH / C-Eval / CMMLU / TruthfulQA / CyberSecEval / CTF-SatML24 + 自有 kitty-rev 验收集。

判分说明：
```text
mcq      抽答案字母与 gold 比（accuracy）
numeric  抽最后一个数做数值比较（容忍 1e-4）
code     只统计「是否给出代码块」（pass@1 需本地执行单测，本脚本不做）
open     不判分，原样落盘供规则/人工抽检
rubric   自有 kitty-rev 集，由 eval/eval_kitty.py 按行为判据判
```

---

## 10 无教师 key 的替代方案：实测抓取结果（2026-10-21）

操作者无法提供五个教师模型的 API key，因此**放弃蒸馏，改走纯开源数据**。抓取全部走
`scripts/fetch_reasoning.py`（hf-mirror + datasets-server，无需 key）。

| 数据集 | 请求量 | 实收 | 说明 |
|---|---|---|---|
| AI-MO/NuminaMath-CoT | 3000 | **400**（一次 curl 30s 超时中断） | 短 CoT，p50 331 token，dup 1%，污染 0 |
| AI-MO/NuminaMath-TIR | 2000 | **389**（同上中断） | 工具集成推理，p50 517 token |
| open-thoughts/OpenThoughts-114k | 1500 `--truncate headtail` | **1500**（1479 条被截头尾） | 长链，截后 p50 1457 token |
| Team-ACE/ToolACE | 1200 `--truncate headtail` | **1200** | 工具调用，p50 仅 70 token，非常适合本 ctx |
| Salesforce/xlam-function-calling-60k | 1500 | **0**（config 解析返回 None） | 需显式 `--config`；ToolACE 已覆盖同类，暂跳过 |
| GAIR/LIMO | 150 | 150（截断版） | 短池验证用 |

**去重后可用 1791 条**（按 user 前 40 字去重，原 3639 → 掉 1848，主因 OpenThoughts 共用同一 system 句式）。

### 混入结果（30% 配比）

```powershell
& "C:\ProgramData\anaconda3\python.exe" scripts\mix_reasoning.py --base data\large --reason data\reasoning --ratio 0.30 --out data\large-mix
& train\.venv\Scripts\python.exe scripts\validate_dataset.py --dir data\large-mix --ctx 2048 --md logs\quality-mix.md
```

```text
base 2736 + reason 1172 = 3908 train（ratio 0.30）
eval 304 / dpo 48 原样复制
质检 VERDICT: PASS（struct 0 / dup 0 / contract 0 / tool_call 0 / over_ctx 0）
产物 data/large-mix/  +  logs/quality-mix.md
```

### 判读

```text
1 短 CoT（NuminaMath / ToolACE）是这套 ctx=2048 的主力，长 CoT 只留截断版
2 教师蒸馏不是必需品：开源链已覆盖"分步+自检"的行为模式，缺的是我们自己的任务分布
3 xlam 未取到不影响结论（ToolACE 12k 已含工具定义+调用链）
4 若后续要补量：NuminaMath 系列用 --resume 重跑即可续，成本≈0
```
