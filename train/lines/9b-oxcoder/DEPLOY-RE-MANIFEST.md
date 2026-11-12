# DEPLOY-RE-MANIFEST · RE 腿部署清单（冻结版）

> 冻结日期：2026-11-03
> 适用：OxCoder-9B 的 kitty 逆向工具路由（RE 腿）
> 状态：**已冻结，禁止再训练此 adapter**
> 依据：`TASKPOINT.md` §A20–A25（六次 SFT 尝试全部收敛到 81%±2.5，已证饱和）

---

## 1 冻结资产与哈希

| 项 | 路径 | sha256 | 体积 |
|---|---|---|---|
| **adapter 权重** | `train/lines/9b-oxcoder/out/z-re-v4/final/adapter_model.safetensors` | `016c1e56a724c9b232009c103c6195748d1a7a013fee89f8e4545324ef5ad1fe` | 173,189,008 B |
| adapter 配置 | 同目录 `adapter_config.json` | `1f1cbb15546a6a913aa2b07491bc5ddf0a023e70936d3091748412551823b3dd` | 1,319 B |
| **基座** | `train/lines/9b-oxcoder/models/OxCoder-9B/model.safetensors` | `d4fca6821fe35b46e684ab88217ec25cdbfcdf9fa208c01110be95a200fcc33b` | 18,819,722,360 B |
| 基座配置 | 同目录 `config.json` | `8ac5528af54ba07e7d7855d0b0f0e7297d0f5b228fe774261b6ed88bfba06498` | — |

```bash
# 校验命令（任何部署前先跑）
sha256sum train/lines/9b-oxcoder/out/z-re-v4/final/adapter_model.safetensors
# 期望 016c1e56a724c9b232009c103c6195748d1a7a013fee89f8e4545324ef5ad1fe
```

---

## 2 能力口径（**不要对外承诺 85%**）

```text
分档口径（同一 adapter · 同一 40 题固定集）：
  E1 无候选集（裸模型）        30/40 = 75.0%
  E2 有候选集 seed7            34/40 = 85.0%
  E2 有候选集 seed11           32/40 = 80.0%
  E2 双种子均值               33.0/40 = 82.5%   ← 部署档口径，对外用这个
  E3 有候选集+5 额外干扰        33/40 = 82.5%

结论：候选集把可用率从 75% 抬到 82.5%，代价是对「具体干扰组合」敏感
      （同 k=12 只换种子，34 → 32）
区间 77.5% – 85.0%（31 – 34 条）
同条件重跑 确定复现（greedy 解码）
完整 schema（19,991 字符）未测，预期低于上述值

敏感性与种子实测（_work/stability_probe.py）：
  k=12 seed=7  → 34    k=12 seed=11 → 32    k=12 seed=23 → 32
  k=24 seed=7  → 32    k=48 seed=7  → 34    k=64 seed=7  → 31
  ⇒ 敏感的是「哪几个干扰」，不是「几个干扰」；k=64 会掉到 31
```

---

## 3 system 模板（必须逐字使用，改一个字就重测）

```text
你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。

当前会话可用工具（只能从下列工具中选）：
- <工具名>: <描述≤60字符>  actions=[<逗号分隔的动作枚举>]
- …（共 8–12 条，见 §4 采样规则）
```

```text
来源：训练集 train-kitty-v3-clean.jsonl 第一条的 system（115 字符），
     由 eval_re_generalize.load_system() 读取，不在代码里手抄。
第二段的工具行格式由 re_clusters.fmt_tool() 生成：
  "- {name}: {desc[:60]}…  actions=[{acts}]"
```

---

## 4 候选集采样规则（决定成败的关键）

```text
每个任务注入 8–12 个工具，必须包含正确答案，其余从硬负例簇抽：
  ① 必含 expect 里的全部正确工具
  ② 同簇易混（11 个手工簇，见 train/lines/_shared/scripts/re_clusters.py 的 CLUSTERS）
  ③ 同通道近邻  ④ 少量跨通道
负向题（不该调用）：候选取「看起来相关」的簇，正解=不调用

★ 不要注入全 64 个工具：实测 k=64 掉到 31（77.5%）
★ 这与 DSH 实际做法一致 —— 工具是按会话/角色白名单注入的，不是全量下发
```

---

## 5 回归脚本

```bash
bash _work/regress_re.sh
```

```text
做四件事：
  1 校验 adapter sha256（与 §1 不符 → 直接 FAIL）
  2 E1 无候选集  → 判 ≥30      基线 30
  3 E2 候选集 seed=7 与 seed=11 各一次 → 判两次均值 ≥31   基线均值 33.0（34 / 32）
  4 E3 干扰档            → 判 ≥29     基线 33
任何一项不达标 → 输出 FAIL 并给回滚提示；全过 → PASS
耗时约 30 分钟（4 档 × 40 题）

注：E2 必须两个种子都拿到才判 PASS —— 缺 seed11 时脚本直接 FAIL，
    不允许降级成「仅 seed7」，否则「换种子就掉」这一场景会被漏掉。
```

**首次基线（2026-11-03 19:43，四档全绿）**

| 档 | 命中 | 参数错 | 选错 | 编造 | 回避 | L1/L2/L3 |
|---|---|---|---|---|---|---|
| E1 | 30 | 4 | 6 | 0 | 0 | 11/8/11 |
| E2 seed7 | 34 | 4 | 2 | 0 | 0 | 11/9/14 |
| E2 seed11 | 32 | 2 | 5 | 0 | 1 | 10/9/13 |
| E3 | 33 | 1 | 6 | 0 | 0 | 11/8/14 |
| **E2 均值** | **33.0** | — | — | — | — | — |

---

## 6 改动即失效清单

```text
下列任一项变动，§2 的 81% 口径立刻作废，必须重跑 §5 回归：
  · adapter 权重或其 adapter_config.json
  · 基座（含换 SRA / 换量化）
  · system 模板文案
  · fmt_tool 的描述截断长度（现 60 字符）
  · CLUSTERS 内容
  · 候选集规模 k（现 8–12）
  · 评测 40 题（eval_cases_re.py 的 CASES）
  · 推理引擎 / 量化方式 / 解码参数（greedy 必须保持 do_sample=False）
```

---

## 7 相关文件

| 文件 | 作用 |
|---|---|
| `train/lines/_shared/scripts/eval_re_deploy.py` | 三档评测（E1/E2/E3） |
| `train/lines/_shared/scripts/re_clusters.py` | 硬负例簇 + 候选集构造（共享模块） |
| `train/lines/_shared/scripts/eval_cases_re.py` | 40 条固定评测集 |
| `_work/stability_probe.py` | 敏感性与种子稳定性实测 |
| `_work/regress_re.sh` | 回归入口 |
| `TASKPOINT.md` §A20–A25 | 全部实验记录与结论推导 |
