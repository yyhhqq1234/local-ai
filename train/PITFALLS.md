# OxCoder-9B 训练坑清单（全量汇总）

> 2026-10-28 整理 · 2026-10-29 补 G 段（外部下载 / 云实例）+ H 段（运行事故与监控运维）
> + C7（resume 覆盖日志）+ E16–E19（四条统计判据翻车）
> 覆盖环境 / 数据 / 训练配置 / 显存 / 验证 / 工具链 / 外部下载 / 运行事故 八类共 **66 条** + 自检 **40 项**
> 每条都带实测证据。开训前逐条对照，别重犯。

---

## 当日复盘索引 · 2026-10-29（2A 训练全程）

> 这一天从 17:29 蓝屏崩到 22:44 判据重写，踩的坑全部串在这里，按时间顺序读即可还原全过程。

| 时间 | 事件 | 条目 | 一句话教训 |
|---|---|---|---|
| 17:23 | GPU 卡死（100% util 但 46W / 53℃） | **H2** | 高占用+低功耗=卡死，比温度早 14 分钟 |
| 17:29 | BugCheck 0x116 蓝屏，训练断在 step 2840 | **H1** | 显卡超频 → 整机蓝屏；训练前必须确认未超频 |
| 17:47 | `--resume` 恢复，训练接上 | **H1** | 三项核对：step 续 / lr 在退火点 / loss 平滑 |
| 17:52 | 发现 jsonl 被覆盖，lt15 假清零 | **C7** | resume 覆盖写日志；累计量跨 resume 要加基线 |
| 18:12 | lt15 从 8 涨到 12，疑似记忆化 | **E17** | 固定绝对阈值随 mean 下降必然误报，改相对口径 |
| 19:34 | T3 报 RED（累计 ltrel>15） | **E17** | 阈值 15 低于按历史率外推的正常终值 20.9，必然触发 |
| 19:35 | 新增 T5：min 三次下钻 −7.9% | **E18** | min 是极值统计量，随 N 自然下漂，不能做趋势判据 |
| 19:44 | T5 上线 9 分钟被证伪，重写 | **E18** | 纯抽样期望 0.0992 < 实测 0.1043，连噪声都没跑满 |
| 22:25 | T1 报 RED（loss=0.0999 < 0.10） | **E19** | 圆整数硬底线在长训练里必然被穿过 |
| 22:44 | T1 改为 min/mean 比值判据 | **E19** | 判据要归一化，别用绝对数字 |
| 全程 | 为改判据重启 watch 6 次 | **H3** | 判据改动要留版本注释，日志行要带口径标签 |
| 全程 | monitor-2a 被唤醒 5 次 | **H4** | 持续值守交脚本，子 agent 只做深度研判 |

**四条统计判据在同一天被连续推翻**（E16 高斯左尾 → E17 固定阈值 → E18 极值单点 → E19 圆整数硬底线），
全是同一类错误：**拿漂亮的绝对数字套在非平稳分布上**。归纳成一条纪律：

> 在单调变化的量（loss / perplexity / 错误率）上，任何绝对数字阈值都是定时炸弹。
> 判据要么归一化（比值 / 分位数 / cv），要么按分布算出来（分段经验率），
> 而且要带「持续」或「多条」条件，不能靠单点触发。

---

## A 环境类（7 条）

### A1 PowerShell 7 与 5.1 必须分开用
- **症状**：`pwsh.exe` 报 CommandNotFoundException
- **根因**：PATH 里没有 pwsh，只有 Windows PowerShell 5.1
- **解法**：`& 'C:\Program Files (x86)\PowerShell\7\pwsh.exe' -NoLogo -NoProfile -Command '...'`
- **证据**：裸 `pwsh` 在 bash 里找不到

### A2 Python 路径是有毒别名
- **症状**：`python` 执行无输出却不报错
- **根因**：PATH 里的 python 是 WindowsApps 的 0 字节别名
- **解法**：必须全路径 `train/.venv/Scripts/python.exe`（训练环境）或 `C:\ProgramData\anaconda3\python.exe`（通用）

### A3 transformers 只在 train/.venv 里
- **症状**：`ModuleNotFoundError: No module named 'transformers'`
- **根因**：anaconda3 base 没装 transformers/torch
- **解法**：一律用 `train/.venv/Scripts/python.exe`
- **证据**：anaconda base 的 pip list 里 torch/transformers 都没有

### A4 控制台 GBK 乱码
- **症状**：输出 `����`
- **解法**：`export PYTHONIOENCODING=utf-8`，或先写文件再读

### A5 jsonl 里的 `\u2028` 破坏 splitlines
- **症状**：JSON 解析报 `Unterminated string`
- **根因**：`str.splitlines()` 会在 `\u2028` 处断行
- **解法**：用 `.split("\n")`

### A6 HF 镜像 429 + Windows symlink
- **症状**：`FileNotFoundError: ..\blobs\<hash>`
- **解法**：`HF_HUB_DISABLE_SYMLINKS=1` + requests 直连下载 fallback

### A7 `nul` 文件导致 git add 失败
- **症状**：`error: short read while indexing nul`
- **解法**：`.gitignore` 加 `nul`

---

## B 数据类（12 条）

### B1 chat_template 无 `{% generation %}` 标记 ★
- **症状**：`SFTConfig(assistant_only_loss=True)` 失效或报错，**user/system 也被算 loss**
- **根因**：Qwen3.5 的 `chat_template.jinja` 只有 `add_generation_prompt`，没有 `{% generation %}`，trl 无法定位 assistant 区间
- **解法**：改 `prompt`/`completion` 双列 + `completion_only_loss=True`（trl 内部执行 `labels[completion_mask==0] = -100`）
- **验证**：`Dropping fully masked examples: 5602/5602`，零丢弃

### B2 `add_generation_prompt=True` 插 ` thinking` 但无闭合 ★
- **症状**：训练文本缺 `</think>`，模型学到"永不结束思考"
- **证据**：`add_generation_prompt=True 比 False 多出: '<|im_start|>assistant\n<think>\n'`
- **解法**：completion 前补空思考块 `</think>\n\n`；数据自带 `thinking` 时原样保留
- **验证后格式**：`<|im_start|>assistant\n thinking\n</think>\n\n正文`

### B3 chunk 切分产生碎片段
- **症状**：一条样本被切成 272 个碎片（每段约 63 字符），膨胀失控
- **根因**：`find_cut` 返回切点过近 + 循环反复返回同一位置
- **解法**：加最小前进量 `max(16, budget//4)`；`budget < max(512, 2*overlap)` 时把 overlap 压到 0
- **证据**：修复后 swe-8k 从 19472 行回到 16651 行，覆盖 1.000000

### B4 base 估算余量不足导致超 ctx
- **症状**：切分后仍有 1 条超 ctx（4146 > 4096）
- **根因**：`base = sys_tok + usr_tok + 12` 低估了模板开销（角色标记 + think）
- **解法**：余量提到 +64

### B5 训练集仍有 5 条超 ctx
- **现状**：2A 34359 条里 5 条超 4096（最多 4146，超 50 token）
- **影响**：SFTTrainer 截尾，损失约 250 token = **0.0002%**
- **决定**：接受

### B6 NSFW 门控集的正负 token 长度差 8.4 倍 → 长度可能被学成隐性开关

- **现状**（`train/lines/9b-oxcoder/data/nsfw-gated/stats.json`，2026-10-28）：
  正样本（有开关→NSFW）均 **1065 token**，负样本（无开关→常规）均 **126 token**。
  条数 6999 : 13998（1:2），token 总量 7.45 M : 1.76 M（4.2:1）。
- **风险**：模型可能把「回答长度」当成与触发词并列的开关信号——
  即学到「没开关就只写一两句」而非真正读 `[[NSFW]]` / `成人内容` 这类标记。
  表现是 GateLeak 探针（同请求去开关）不一定抓到，但在**无开关的长回答请求**上会误入 NSFW 或反过来拒答。
- **验证手段**：`nsfw_gate_eval.py` 的 NOGATE 探针 + 手工补一组「无开关 + 明确要求详细长文」的样本实测。
- **对策（2B 跑前决定）**：负样本侧补一批「无开关但要求详细长回答」的对照，
  把「长度」变量从「门控」变量里解耦；理想让负样本 token 分布覆盖 100–1500，而不是集中在 126。
- **本条未在首轮 2B 实测**（首轮用已废弃的 `mix-2b-bucketed.jsonl`），进 2B 前必须实测确认。

### B7 训练集自带工具名错拼 → 直接教模型学幻觉 ★★

- **现象**：全量扫描 `train-kitty-core.jsonl`，assistant/user 正文里有 4 处 token 不在
  `tools.json` 的 64 名单内，且**不是粘连**（前后都是空格/标点）：
  ```
  kitty_c    × 2   （应为 kitty_ce）
  kitty_ace  × 1   （应为 kitty_acescan）
  kitty_adb  × 3   （adb 是外部命令，不是 kitty 工具 → 应为 adb）
  ```
- **根因**：数据构建时手写/拼接产生错拼，之后一直被当"真实工具"喂给模型。
  `kitty_c` 尤其危险 —— 它像 `kitty_ce` 的合法缩写，模型容易学成独立工具。
- **后果**：这类错名是**幻觉的直接来源**。基座在泛化测试里编出 10 个名字
  （`kitty_disasm`/`kitty_protocol`…）也带这种「看起来合理」的特征。
- **解法**：`train/lines/_shared/scripts/fix_typo_toolnames.py`（词边界正则，只改这 4 处，先备份 `.bak-typo`）：
  ```bash
  python train/lines/_shared/scripts/fix_typo_toolnames.py            # dry-run 报告
  python train/lines/_shared/scripts/fix_typo_toolnames.py --apply    # 生效（自动备份）
  ```
  修正后残留的非白名单 token 只剩 2 个**误切**（非错名）：
  ```
  reverse_add_  × 11   ← 正文里的泛指写法 reverse_add_X
  kitty_v6      × 1    ← 文件名 eval_kitty_v6.py
  ```

### B8 工具覆盖空洞：34 个工具 <50 条，kitty_ce 独占 23.5%

- **现象**：5602 条里 `kitty_ce` 出现 1317 次（**23.5%**），而 34 个工具覆盖 <50 条
  （`kitty_loop_status` 15、`kitty_rea_callpath` 18、`kitty_bepinex` 18…）。
- **后果**：模型形成「什么都先想 kitty_ce」的偏置 —— 泛化题 G06 三档全给 `kitty_ce`
  （应 `kitty_pchain`），就是这种偏置的直接表现。
- **解法**：`train/lines/_shared/scripts/build_tool_coverage.py`，按 channel 分三套模板补强
  （A 通道 / G3 记录写入 / 引擎外部工具，参数要点各不相同）：
  ```bash
  python train/lines/_shared/scripts/build_tool_coverage.py --target 50 \
    --force kitty_pchain,kitty_dualview,kitty_acescan
  ```
  产出 149 条 → 与 core 合并后增广，`<50 覆盖` 从 **34 个降到 0 个**。
- **注意 `--force`**：pchain/dualview/acescan 数量够（72-81）但**表述单一**，
  不满足阈值条件，必须强制补，否则 G06 这类题永远修不掉。

### B9 训练集混入非本域样本（AgentTeams 消息 / 后台任务输出 / 对话碎片）★★

- **现象**（2026-10-28 全量体检 `train-kitty-core.jsonl` 5751 条）：
  - **6 条 user 只有 1–4 字**：`继续`×2、`批`、`同意`、`L3`、`批准` —— 是对话轮次残留，无独立语义
  - **14 条 user 600–2556 字**，内容是 `AgentTeams message from verifier:`（7 条）、
    `background job pwsh-N (...)`（5 条）、`setup 17/19（按 ❌ 逐项修复…）`（1 条）、
    `Role definition: Inquirer: ...`（1 条）
- **危害**：教模型「回答 agent 协作消息 / 命令输出 / 角色定义」，而不是「回答逆向任务」。
  且长 prompt 配 200 字短 output，长短严重失衡。
- **解法**：`augment_user_queries.py` 加长度 guard（默认 `--min-user-chars 4 --max-user-chars 600`），
  被挡下的写入隔离清单，**原数据不删**：
  ```bash
  python train/lines/_shared/scripts/augment_user_queries.py     --in train-kitty-merged.jsonl --out train-kitty-v2-aug.jsonl --k 4     --quarantine train/lines/9b-oxcoder/data/kitty-reverse/quarantine-len.jsonl
  ```
  实测隔离 **20 条**（6 短 + 14 长），v2 从 22915 → **22839 条**。
- **阈值教训**：一开始设 `min=8` 隔离了 38 条，误伤「存储路径该放哪」（7 字）这类**合法短意图**
  （训练集 user 中位数只有 56 字）。改成 **4** 才只挡真正的对话碎片。

### B10 轨迹数据被过度切分：单任务最多 545 片 ★★

- **现象**（`traj-all.jsonl` 17553 条）：按 user 前 120 字归并出 12975 个原始任务，
  平均 1.4 片/任务看似正常，但长尾极端：
  ```
  545 片  ← pandas-dev__pandas__1.0
  297 片  ← numpy__numpy__1.0
  217 片  ← 某条 carry_over 超长轨迹
  207 片  ← python-pillow__Pillow__1.0
  102 片  ← tornadoweb__tornado__1.0
  前 10 大任务共占 7.7% 的样本量
  ```
- **危害**：同一条 pandas issue 被训练 **545 遍**。RE 阶段已实测「2 遍就把 4/10 条背到
  n-gram 重合 1.00」，545 倍曝光的记忆化程度可想而知。
- **解法**：`train/lines/_shared/scripts/cap_traj_fragments.py`，按任务分组后**均匀采样**（非随机，保时间轴分布）：
  ```bash
  python train/lines/_shared/scripts/cap_traj_fragments.py --max-per-task 40 --apply     --out train/lines/9b-oxcoder/data/agent-traj/traj-all-capped.jsonl     --quarantine train/lines/9b-oxcoder/data/agent-traj/quarantine-frag.jsonl
  ```
  实测：10 个超限任务、排除 **1358 条（7.74%）**、保留 **16195 条**。
  被排除的进隔离清单，原 `traj-all.jsonl` 不动。
- **cap 选择**：20 太狠（545→20 砍 96%，长轨迹的难度梯度丢失），**40** 兼顾去重与保留。

### B11 训练集里残留角色标记 `【assistant】` → 模型学会复读它，输出无限循环 ★★★★★

- **现象（2026-10-30 2A 训练的真实死因）**：训完 7414 步、`train_loss 0.2312`、
  `token_acc 89.5%`，看起来一切正常。评测时模型对**每一个**问题都输出：
  ```
  【assistant】【assistant】【assistant】【assistant】【assistant】…
  （连续重复几十次，直到 max_new_tokens 耗尽）
  ```
  对比 r3 正常输出：
  ```
  kitty_die action=scan  选它的理由：packer detect (DIE passthrough)（通道 static）。
  ```
- **根因**：训练集里 **66.3% 的样本含角色标记污染**
  ```
  训练集 traj-2a-v2-2048-bucketed.jsonl  n=14828
  含【assistant】/【user】/【system】的条数: 9837 (66.3%)
  标记总数: 16641
  典型形态: "…[Command finished with exit code 0]  【assistant】Excellent! Everything is working correctly…"
  ```
  这些标记来自 OpenHands 原始轨迹的 `<observation>…【assistant】…` 结构，
  转换脚本只换了 system prompt，**没有清理正文里的角色标记**。
  模型忠实学到了「回复末尾要跟一串 【assistant】」，并在推理时无限复读。
- **为什么这一个原因就能解释全部症状**：
  ```
  输出被 【assistant】 循环占满
    → 没有代码块        → code_rate 2.5%
    → 没有具体标识符    → avg_cov 30.6%
    → 没有工具调用      → RE 回避 33/40、命中 75%→10%
  ```
  **一个数据污染同时打穿三个指标。** 之前把 RE 崩归因为「system 差异导致能力覆盖」（C8）
  只对了一部分 —— 更直接的是输出格式已被污染，模型根本没机会调工具。
- **检测（开训前必跑）**：
  ```python
  import json
  MARKS = ('【assistant】', '【user】', '【system】', '<|assistant|>', '<|user|>', '### Assistant:', '### User:')
  n = bad = 0; total = 0
  for line in open(path, encoding='utf-8'):
      d = json.loads(line); n += 1
      txt = d.get('completion') or ''.join(m.get('content','') for m in d.get('messages',[]) if m.get('role')=='assistant')
      c = sum(txt.count(k) for k in MARKS)
      if c: bad += 1; total += c
  print('含角色标记 %d/%d = %.1f%%（要求 0%%），共 %d 个' % (bad, n, 100*bad/n, total))
  ```
  **判据：必须 0%。** 训练数据的 assistant 字段里不应出现任何角色标记 —— 角色由
  chat template 管理，正文里出现就是污染。
- **修法**：
  ```python
  for k in MARKS:
      txt = txt.replace(k, '')        # 直接删，不要替换成空格（会留双空格）
  txt = re.sub(r'[ \t]{2,}', ' ', txt).strip()
  ```
- **为什么训中监控抓不到**：`loss` 和 `token_acc` 都很好 —— 因为**【assistant】是高频
  且完全可预测的 token 序列**，模型学会它反而降低 loss。
  ```
  train_loss 0.2312  ← 这个数不但不报警，还是在奖励污染
  mean_token_acc 89.5%
  ```
  **训练指标对「学了一个坏模式」是盲的，只有任务级评测能暴露。**
- **踩坑记录**：2026-10-30 07:33 深挖 2A 失败时，从 `eval-re-regress.json` 的 `resp`
  字段里看到实际输出才定位。**教训：评测 detail 必须存 resp 原文**（这条 E15 早就写过，
  这次正是靠它才查出来）。
- **与 E20 的关系**：E20 说「训练集 88.8% 无代码块」，B11 说「66.3% 有角色标记污染」。
  两条是同一批数据的两个独立缺陷，**B11 更致命**（E20 只是学不到代码块，B11 是输出崩坏）。

### B12 轨迹切窗把 `user` 切成 agent 日志碎片 → 输入语义整体错位 ★★★★★

- **现象**：修完 B11（清标记）和 E20（补代码块）后，数据格式体检全 PASS，
  但抽查 `user` 字段发现 **99.3% 是 agent 执行日志碎片**：
  ```text
  user 总数 1399（清洗后）
  含 agent 日志痕迹: 1389 (99.3%)
  干净的: 10 (0.7%)

  内容长这样：
    "<carry_over>
     [Command finished with exit code 0]
     [The command completed with exit code 0.]
     [Current working directory: /workspace/pandas-dev__pandas__1.0]
     [Python interpreter: /testbed/.venv/bin/python]
     Perfect! ## Summary ..."

  长度分布: P10=753  P50=851  P90=866   ← 高度集中在 850 字符
  ```
- **根因**：长轨迹按**固定上下文长度切窗**（如 target-ctx 8192，chunk 4096），
  切点落在轨迹中间，于是「user」变成了「上一窗的尾巴」。
  > `<carry_over>` 这个标记就是切窗的直接证据 —— 它是「上文被截断，这里是续接」的显式声明。
- **后果（比 B11/E20 更根本）**：
  ```text
  模型看到的输入 : 一堆 bash 输出 + 测试结果 + 工作目录
  模型要学的输出 : "I have successfully implemented a fix... ## Summary"
  ⇒ 学到的是「日志 → 总结报告」

  评测期望的输入 : <具体 bug 描述>
  评测期望的输出 : 根因分析 + 代码块
  ⇒ 语义整体错位，avg_cov 只能到 30.6%
  ```
  **格式对了（有代码块、无标记）不代表语义对了。** 输入侧错位，输出侧再干净也没用。
- **检测（必须和格式体检一起做）**：
  ```python
  BAD = ('<carry_over>', '[Command finished', '[The command completed',
         '[Current working directory:', '[Python interpreter:', 'exit code')
  bad = sum(1 for l in lines if any(b in json.loads(l)['messages'][1]['content'] for b in BAD))
  print('user 含日志碎片 %d/%d = %.1f%%（要求 0%%）' % (bad, n, 100*bad/n))

  # 辅助信号：user 长度 P10/P50/P90 若高度接近（如 753/851/866）
  # ⇒ 固定切窗特征，几乎必然错位
  ```
- **正解：从**未切分**的原始轨迹重新提取，不要试图从切片里救**
  ```
  ✗ 从 traj-2a-v2.jsonl（已切窗）清洗 → 清得再干净，user 还是日志碎片
  ✓ 从 swe-16k.jsonl / swe-8k.jsonl（未切分）提取：
      user      = <issue_description>…</issue_description>
      assistant = 清 【assistant】/【observation】 → 丢工具输出段 → 取含代码块的修复段
  ```
  实测：2113 条原始轨迹 → 667 条干净核心集（user 日志碎片 **0.0%**）。
  `train/lines/_shared/scripts/extract_2a_from_traj.py`
- **纪律**：
  1. **轨迹数据的切窗必须按任务边界切，不能按 token 数硬切**。
     要切就用「一个完整任务 = 一条样本」，切不动就整条丢弃。
  2. 格式体检（B11/E20）**不能代替语义体检**（B12）。两套都要：
     ```
     格式：角色标记 0% / 代码块达标 / 长度达标
     语义：user 是问题描述（不是日志）/ assistant 是回答（不是工具输出）
     ```
  3. 看数据的「长度分布形状」：真实提问的长度是离散的、差异大的；
     固定切窗的长度是聚成一团的。P10/P50/P90 相差不到 15% 就要警惕。
- **代价**：本轮因为这个问题，第一版重建（1399 条）整批作废，返工重提。
  **如果一开始就抽查 3 条 user 内容，10 分钟就能发现。**
- **踩坑记录**：2026-10-30 08:00，修完 B11/E20 后抽查 user 才发现。

---

## C 训练配置类（8 条）

### C1 `gradient_accumulation_steps=16` 必卡死 ★★★
- **症状**：第 1 步之后无限挂起，GPU 100%、显存不释放、进度条不动
- **证据**：ga=16 卡在 1/12（paged_adamw_8bit 139s）和 1/4（adamw_torch 76s）；ga=4 和 ga=1 全部正常
- **结论**：**ga 上限 4，16 必挂，与 optimizer 无关**
- **关键认知**：ga 只改变分组方式，**不改变总时长**（ga=1 与 ga=4 每样本时间一致，0.66–0.72 s）

### C2 `prepare_model_for_kbit_training` 把 179 个参数转 fp32 ★★
- **症状**：forward 6.616 s（应该是 1.144 s）
- **根因**：不只 lm_head/embed，**每层的 conv1d.weight / A_log / dt_bias / 各种 norm 都被转 fp32**，每次 forward 都要 cast（`aten::_to_copy` 896 次、`copy_` 1256 次，占 52% 耗时）
- **解法**：加载后全量转回 bf16（无条件是关键，不要只转大表）
- **效果**：forward **6.616 → 1.144 s（5.8×）**，alloc 10.92 → 7.13 GiB

### C3 `from_pretrained` 缺 `low_cpu_mem_usage=True`
- **症状**：RAM 27.5/31.5 GB（87%），系统卡死
- **解法**：加上，RAM 降到 10.3 GB

### C4 `save_total_limit=3` 轮转删光早期 checkpoint
- **症状**：训练到 1200 步时，200/400/600/800 已被删，不可恢复
- **解法**：改成可配参数，默认 **8**（`--save-total-limit 8`）
- **证据**：本轮 RE 训练最后只剩 1200/1400/1401

### C5 `SFTConfig(use_liger=True)` 不支持 Qwen3_5
- **症状**：静默回退，logits 4 GiB 照样占
- **根因**：transformers 的 liger 集成只覆盖 39 个模型，Qwen 系只有 `qwen2vl_mrope`
- **解法**：手写 `LigerSFTTrainer`（直接调 text model 拿 `last_hidden_state` + 分块 CE）

### C6 `--resume` 在 cosine 退火到底后等于空转（补训必踩）★★

- **现象**：想「接着再训 2 epoch」，用 `--resume checkpoint-1401` 恢复。
  结果 trainer_state 恢复的 lr 是 **5.1e-10**（cosine 已衰减到 0），每步几乎是恒等更新，2 epoch 白跑。
- **根因**：`resume_from_checkpoint` 恢复的是 adapter 权重 **+ optimizer.pt + scheduler.pt + global_step**。
  上一轮跑满 1 epoch 后 cosine 已走到底，lr 归零；恢复即继承 lr=0。
- **附加坑**：`num_train_epochs` 是「总 epoch 数」不是增量。
  resume 到 step 1401（epoch=1.0）再传 `--epochs 2` → 总步数按 2802 算，只会再跑 1401 步（= 1 epoch）。
- **正解**：补训用 `--init-adapter <旧 adapter 目录>`（脚本已加）。
  只搬 LoRA 权重，optimizer / scheduler / global_step 全新，lr 重新 warmup→cosine 衰减。
  补训 lr 取上一轮的一半（本例峰值 1e-4 → 5e-5），避免在已收敛权重上二次冲击。
- **判别**：日志出现 `[lora] 从已有 adapter 继续：...`，且 `learning_rate` 从 2e-05 爬升到峰值（不是停在 5e-10）。
- **实测**（2026-10-28 RE 补训 2 epoch）：`--init-adapter re-stage1-fixed/final --lr 5e-5`，
  loss 首步 **0.69**（对比首轮 3.84 起步，证明旧 LoRA 权重已生效），峰值 lr 5e-05 正确到位。

### C7 `--resume` 覆盖写 train-log.jsonl，记忆化基线假清零 ★★★★

- **现象**：TDR 蓝屏后从 `checkpoint-2800` resume，训练正常接上（loss 0.2289 与 0.2193 平滑衔接），
  但 `train/lines/9b-oxcoder/out/2a-stage/train-log.jsonl` 从 **568 行变成 1 行**，`mem-trace.jsonl` 从 ~2800 行变成 10 行。
- **根因**：训练脚本的 jsonl 日志是 `open(..., "w")` 覆盖写，不是 append。
  `--resume` 会重新走一遍初始化，把文件截断重写。
- **后果（比丢日志严重得多）**：监控脚本 `watch_2a.sh` 的 `n_lt15_all` 是「jsonl 里 loss<0.15 的条数」。
  文件被清空后它从 0 起算，输出 `lt15=0` —— **看起来像「零记忆化」的假清白**。
  崩溃前真实累计是 **8 条**。按假数据走到终点，终点评测的记忆化基线会整体算错。
- **正解（已实施 2026-10-29）**：`watch_2a.sh` 加基线常量，分母也补：
  ```python
  BASE_LT15 = 8       # 崩溃前累计 loss<0.15 条数，从 watch.log 24 个采样点重建
  BASE_LT10 = 0
  BASE_MIN  = 0.1132  # 崩溃前全段最小 loss（step 1565）
  BASE_N    = 560     # 崩溃前 568 行 − 约 8 行（2801–2840 会被重走，避免重复计）
  min_all    = min(min(r["loss"] for r in rows), BASE_MIN)
  n_lt15_all = sum(...) + BASE_LT15
  n_lt10_all = sum(...) + BASE_LT10
  # 输出分母用 len(rows) + BASE_N
  ```
- **重建来源**：`train/logs/2a-watch.log` 不会被 resume 覆盖（append 写），逐行可还原累计轨迹：
  ```
  step 1005 0/201 │ 1190 1/238 │ 1365 3/273 │ 1500 5/300 │ 1585 6/317
       1840 6/368 │ 2015 6/403 │ 2185 7/437 │ 2535 7/507 │ 2620 8/524 │ 2840 8/568（崩溃点）
  ```
- **纪律**：
  1) 任何 **resume 后续训**，第一件事是核对 `train-log.jsonl` 行数有没有缩水；
  2) 长训练必须让**至少一条日志是 append-only**（本例是 watch.log），否则断点恢复后无据可查；
  3) 监控脚本里凡是从 jsonl 聚合的**累计量**，跨 resume 都要加基线偏移。
- **踩坑记录**：2026-10-29 17:29 BugCheck `0x116 VIDEO_TDR_FAILURE` 后 resume 触发。

### C8 串行「阶段训练」会覆盖前序能力，不是叠加 ★★★★★

- **现象**：先训 RE（`r3`，system = kitty 工具契约，命中 75.0%），再在 r3 上用
  **完全不同的 system**（`SYSTEM_2A` = "You are a senior software engineer…"）和
  **完全不同的任务形态**（15909 条编程分析轨迹）续训 2A。结果：
  ```
                命中率   参数错  选错  编造  回避   L1/L2/L3
  r3            75.0%     3     7    0     0    11/8/11
  2a            10.0%     0     3    0    33     0/0/4     ← 回避 33/40
  ```
  **RE 能力从 75% 打到 10%，回避从 0 暴增到 33。** 2A 侧自己也没学好（见 E20）。
- **根因**：同一批 LoRA 权重上，后一阶段的 system prompt 与响应格式把前一阶段的
  「条件反射」覆盖掉。模型学成「遇到问题先给代码分析」，于是 33/40 条不再调工具。
- **关键认知**：**阶段训练不是能力叠加，是权重覆盖。**
  两个 stage 的 system / 任务形态差异越大，覆盖越彻底。
  r2 训 3 遍时出现过同样退化，当时归因为「过拟合」，其实机制是这个。
- **正解（按推荐度排序）**：
  ```
  方案 X  混合训练：把两类数据按比例混在一起，一次训完
          （RE:2A = 70:30，保住主业能力，2A 当增量）
  方案 Y  防遗忘 rehearsal：训 2A 时混入 20–25% 的 RE 数据
  方案 Z  两个 adapter 分别训，推理时按场景切换（不合并）
  ```
  **方案 X/Y 的核心是「同一轮里两类样本共存」，让模型学到一个兼容分布。**
- **验收纪律（本轮教训）**：
  1. 每个 stage 训完**必须跑前序 stage 的回归集**，不能只看本阶段指标
     （本轮 post_train 确实跑了 RE 回归，才发现问题——这个机制是对的）
  2. 回归集命中率跌超 **15 个百分点**即为不可接受（本轮跌 65 点）
  3. 新 stage 的 system prompt 若与前序完全不同，先假设会覆盖，用混合训练预防
- **踩坑记录**：2026-10-30 03:59 2A 验收时发现。

---

## D 显存类（4 条）

### D1 显存碎片累积 → WDDM 换页 → 系统卡顿 ★★★
- **症状**：第 47 步前 2.49 s/步正常，第 48 步起单调恶化 23.75 → 53.84 → 57.93 → 68.91 → 93.86 s/步；**整个 Windows 间歇性卡顿**
- **60 步实测轨迹**：
  ```
  step  1: alloc 7.848  reserved  8.658  free 1.862
  step 10: alloc 7.848  reserved  9.621  free 0.926
  step 53: alloc 7.848  reserved 10.230  free 0.331
  step 59: alloc 7.848  reserved 10.922  free 0.000
  ```
- **三条结论**：① **不是泄漏**（alloc 恒定 7.848）② **是碎片**（reserved 单调爬升，free 归零）③ **`peak 13.043` 是假数字**（是加载 18.8 GB 权重的瞬时峰值，不是训练峰值）
- **卡顿机制**：reserved 触顶后，Windows WDDM（不支持 `expandable_segments`）把系统内存当显存后备，数据经 PCIe 往返 → util 100% 但 power 仅 53W（假忙）
- **4 项修复（已验证 1401 步全程稳定）**：

| # | 修复 | 效果 |
|---|---|---|
| 1 | **按长度分桶重排数据**（决定性） | reserved 到 9.41 后 900 步零漂移 |
| 2 | `set_per_process_memory_fraction(0.93)` | alloc 钉死 7.622，free 从未击穿 1.0 |
| 3 | Liger CE 分块 1024 → 256 | peak 恒定 8.785 不随碎片抬升 |
| 4 | 卸载视觉塔 | 省 0.23 GiB，构成 free 安全垫 |

### D2 视觉塔白占 0.77 GiB ★
- **根因**：`AutoModelForImageTextToText` 默认加载 27 层视觉塔（411 M 参数），纯文本训练用不上
- **解法**：`model.model.visual = None` + `empty_cache()`，alloc 7.848 → 7.621 GiB

### D3 `peak_gib` 被加载峰值污染
- **解法**：`trainer.train()` 前调 `torch.cuda.reset_peak_memory_stats()`

### D4 `pwrite` 类 CL 参数无效
- **症状**：`PYTORCH_CUDA_ALLOC_CONF` 警告 deprecated
- **解法**：用 **`PYTORCH_ALLOC_CONF`**（去掉 CUDA_），值 `max_split_size_mb:64,garbage_collection_threshold:0.80`

---

## E 验证类（20 条）

### E1 加载器不匹配导致 adapter 全 missing ★★★
- **症状**：`UserWarning: Found missing adapter keys while loading the checkpoint: [全部 LoRA key]`，adapter 与基座表现完全相同
- **根因**：训练用 `AutoModelForImageTextToText`（结构 `.model.model.layers`，3 层嵌套），测试用 `AutoModelForCausalLM`（`.model.layers`，2 层）→ **key 路径不匹配，adapter 一条没生效**
- **解法**：eval 也必须用 `AutoModelForImageTextToText`
- **验证**：修复后 0 个 missing keys，alloc 7.51（adapter）vs 7.35（基座）

### E2 自造 eval prompt 与训练数据不一致
- **症状**：0/5 PASS
- **根因**：自造 system 写成"直接调用"，训练数据是"具体调用"；且没给工具 schema → 模型只能猜工具名
- **解法**：用训练集真实样本做 held-out（原始 system + user，让模型续写，对比真实 assistant）

### E3 工具白名单不全导致误判编造 ★
- **症状**：`kitty_rea_binary`/`kitty_trail`/`kitty_apkscan`/`kitty_loop` 被判"编造"
- **根因**：白名单只写了 28 个，漏了这些真实工具
- **解法**：从 `kitty-contracts/tools.json` 动态读 64 个（勿手写）；`kitty_dbvm`/`kitty_file_info`/`kitty_debug` 等 10 个确认为已知幻觉，单列回归集

### E4 用训练集当 held-out，测出来的是记忆不是能力 ★★★

- **现象**：`eval_re_heldout.py` 三档权重（1/2/3 遍数据）结果完全一样（都 5/6 命中），
  但 n-gram 重合从 0.167 飙到 0.515，逐字复现参考答案的条数从 1 涨到 4。
- **根因**：该脚本 docstring 写「用训练集真实样本做 held-out」，但**训练集样本不可能是 held-out**。
  它从 `train-kitty-core.jsonl`（训练用的那 5602 条）抽样，只跳过头 20 条 —— 每条模型都训练过。
- **后果**：据此得出「补训 2 epoch 把 kitty_dbvm 幻觉压掉了」是错的，实际是把那条样本背牢了。
  同理「工具命中 5/10」也是误读（4 条参考答案本就没有工具名，真实分母 6）。
- **正解**：用**改写提问**做泛化集 —— `eval_re_generalize.py`：
  12 条场景、措辞与训练集零重叠、全程不出现 `kitty_`、L1/L2/L3 三档难度。
  实测该集：基座 0% → 1 遍 50% → 2 遍 91.7% → 3 遍 83.3%，判别力充分。
- **判据分离**：
  · 能力 → 泛化集命中率（≥70%）+ 编造（==0）
  · 记忆度 → in-sample n-gram 重合（<0.40 健康，>0.60 停止）
  两套指标各司其职，不可互相替代。

### E5 工具名正则连读造成编造假阳性 ★

- **现象**：模型输出 `kitty_net action=capture port=8080`，
  正则 `kitty_[a-z0-9_]+` 把空格后的词连读成 `kitty_netaction` → 误判编造。
- **根因**：正则不认空格分隔，`a-z0-9_` 类吃掉了后接单词。
- **正解**：切出 token 后做**最长前缀归一** —— 若 token 以某白名单工具名为前缀，归到最长那个前缀；
  无任何前缀才算真编造。

```python
def norm_tools(raw):
    out = set()
    for tok in raw:
        if tok in KITTY_TOOLS:
            out.add(tok); continue
        pref = [k for k in KITTY_TOOLS if tok.startswith(k)]
        out.add(max(pref, key=len) if pref else tok)   # 无前缀 = 真编造
    return out
```

- **效果**：档2 编造 1 → 0（`kitty_netaction` → `kitty_net`），真编造 `kitty_dbvm` 仍正确识别。
- 已同步到 `eval_re_generalize.py` 与 `eval_re_heldout.py`。

### E6 工具名正则只认 `kitty_` 前缀 → 漏掉 6 个 `reverse_*` 工具 ★★

- **现象**：统计工具覆盖时报「6 个工具 0 覆盖」（`reverse_add_target` / `reverse_add_intent`
  / `reverse_add_obs` / `reverse_add_patch` / `reverse_add_asset` / `reverse_submit`），
  但 `tools.json` 里它们都在，训练集里也确实有 —— 是**统计脚本看不见它们**。
- **根因**：正则写成 `kitty_[a-z0-9_]+`，而 64 个工具里有 6 个是 `reverse_` 前缀（G3 记录写入系列）。
  同一个 bug 让评测也无法识别模型正确输出的 `reverse_*`，也无法判它们为编造。
- **正解**：双前缀 `(?:kitty|reverse)_[a-z0-9_]+`，三个文件同步：
  ```
  eval_re_generalize.py  PAT
  eval_re_heldout.py     tools_in()
  check_tool_coverage.py PAT
  ```
- **教训**：**任何按前缀写的正则，都必须先对着白名单全量枚举验证一遍**，
  确认「64 个工具名全部能被自己的正则切出来」。这一条可以写成自检：
  ```python
  assert all(PAT.fullmatch(t) for t in KITTY_TOOLS), "正则切不出全部工具名"
  ```

### E7 argparse 的 help 文本里有单个 `%` → `--help` 直接崩

- **现象**：`python train_qlora9b.py --help` 抛
  `ValueError: unsupported format character 'C' (0x43) at index 63`，整个 help 打不出来。
- **根因**：argparse 用 `%` 格式化 help 字符串。原文本 `实测省 90% CE 显存` 里的 `% C`
  被当成格式符。**只有跑 `--help` 才触发**，所以训练一直没暴露。
- **正解**：help 文本里的百分号写成 `%%`（转义）：
  ```python
  help="…（实测省 90%% CE 显存；注意 argparse 会把单个 %% 当格式符，故写作 %%%%）"
  ```
- **教训**：**新增 argparse 参数后必须跑一次 `--help`**，不能只看训练能不能启动。

### E8 12 条泛化集分辨率不足 → 定档结论被 36 条推翻 ★★★

- **现象**（2026-10-28）：12 条泛化集给出的排序是「档2 91.7% > 档3 83.3%」，
  据此判定「第 3 遍是负增益」，定档档2。扩到 36 条后变成
  「**档3 75.0% > 档2 69.4% > 档1 58.3%**」单调上升 —— **结论反转**。
- **根因**：12 条时单条 = 8.3 个百分点，档2 与档3 只差 **1 条**（11 vs 10）。
  这个差异完全落在噪声里，却被当成「负增益」写进了定档文档。
- **教训**：
  · 泛化集条数决定分辨率。**不要用少于 30 条的集合做档位裁决**
  · 差异若只有 1-2 条，一律判「不显著」，不能写成趋势
  · 定档文档必须写清口径（多少条），否则后人无法判断可信度
- **正解**：`eval_cases_re.py` 扩到 36 条（L1/L2/L3 各 12），并在文件末尾做**交错重排**
  （否则 `--cases 12` 只跑到 L1，实测得到 L1/L2/L3 = 9/0/0 的偏斜）。
- **附带教训**：12 条时代的其他结论也需复核 —— 其中「档2 优于档3」已被证伪，
  「基座 0% 编造 10」在 36 条下更严重（**2.8% 命中、编造 29 = 80.6%**）。

### E9 评测只判工具名、不判参数 → 选对工具但填错参数被误判为通过 ★★★

- **现象**（2026-10-28 第二轮审查）：36 条泛化集只检查「输出里有这个工具名吗」，
  完全不看 `action=` / `op=` / `path=` 填得对不对。
- **数据依据**：训练集里 **56.6%（3170/5602）** 的回答是「文字+带参数」，
  参数出现频次 `action 3733 / op 2316 / path 1447 / target 631 / out 510 / addr 434`。
  评测却完全没覆盖这个维度。
- **后果**：模型可能输出 `kitty_patch`（正确）但 `action=find`（应为 `patch`），
  真实调用会失败，**而评测判它 ✅**。这是最危险的假阳性 —— 分数好看，实际不可用。
- **解法**：场景库加 `args` 字段 + `check_args()` 判定，新增 `noarg` 分类：
  ```python
  dict(id="G14", expect={"kitty_patch"}, args={"action": ["patch", "find"]})
  dict(id="G13", expect={"kitty_ce"},    args={"op": r"W\|"})   # op 值前缀正则
  ```
  `classify` 六分类：`hit`（工具+参数都对）/ **`noarg`**（工具对但参数错）/ `wrong` / `fake` / `none`。
- **op 的坑**：spec 里的 op 写**值的正则前缀**，不要加 `^`
  —— `^` 在正则中间是「行首断言」，`op="W|..."` 里 `op=` 之后不是行首，永远匹配不上。

### E10 泛化集只测「该调哪个」，不测「不该调」★★

- **现象**：训练集 **20.8%（1165/5602）** 的回答是纯文字概念解释（不含任何工具名），
  但 36 条泛化集全是「该调哪个工具」，从没测过「这个问题根本不该调工具」。
- **后果**：模型若学会「见问题就塞工具名」，真实使用中会把概念问题也变成工具调用 ——
  这是 agent 最典型的退化形态。
- **解法**：加 4 条负向题 `N01-N04`（授权书要素 / 回包拆解 / 夜跑八站 / 黑盒白盒区别），
  `expect=set()` 表示正确答案是不输出任何工具名。`classify` 里：
  ```python
  if not expect:
      return ("hit" if not got else "wrong"), ...
  ```

### E11 批量生成会改变评测结果 —— 提速不能靠 batch ★★★

- **现象**（2026-10-28 实测）：为提速给评测加左 padding 批量生成，结果：
  ```
  batch=4（40 条全量）: 逐字一致 27/36，关键信息不同 3/36（8.3%）加速 3.03x
  batch=8（8 条）      : 关键信息不同 1/8             加速 3.16x
  ```
  典型失败：G27 单条给 `kitty_add_sub,kitty_get`，批量给
  `kitty_add_patch,kitty_add_sub,kitty_status` —— **工具集完全不同**。
- **根因**：左 padding 虽然 `attention_mask=0`，但 batch 内长 prompt 会改变 kernel 的
  reduce 顺序；4bit 量化的 dequant 误差被放大，贪婪解码下分叉成不同 token。
  batch 越大、长度差异越大，分叉概率越高。
- **结论**：**batch 生成不能用于基线评测**。`eval_multi_adapter.py` 的 `--batch`
  默认改回 1（逐条），参数保留仅作实验。
- **教训**：任何"并行提速"都要先做**逐条 vs 批量**的等价性验证（`verify_batch_equiv.py`），
  判据是「工具名 + 参数必须完全一致」，而不是「大意差不多」。
- **顺带结论**：`causal_conv1d` 也救不了 —— PyPI 无 Windows wheel，环境无 nvcc/MSVC，
  且实测参考实现只占 forward 的 0.4%、生成耗时的 6.7%。
  → **2026-10-30 更正**：pip 那条确实不通，但 FLA+Triton 替身已打通（零拷贝 + varlen），
  卷积本身 8.9–10x、**packing 现在可用**。详见 [`CAUSAL-CONV1D.md`](CAUSAL-CONV1D.md)。

### E12 统计训练集格式时把 EM DASH 当成汉字，结论假 0 ★★

- **现象**（2026-10-28）：统计训练集里「文档枚举句式」有多少条，正则写
  `((?:kitty|reverse)_\w+)\s*的\s*action\s*取`，结果 **0 条**，
  差点得出「训练集没这种句式，是模型自己发明的」这个错误结论。
- **真相**：实际字符是 `U+2014 EM DASH`（`—`），不是「的」。dump：
  ```
  CODES: ...0x20, 0x2014, 0x20, 0x61...
  ASCII-SAFE: kitty_sym \u2014 action \u53d6 exports /
  ```
  控制台是 GBK，`—` 的 UTF-8 三字节显示成两个乱码字符，肉眼看起来像「的」。
- **后果**：结论从「模型自创格式」变成「模型忠实模仿训练集」—— 修法完全相反。
- **解法**：① 正则用 `[\u2014\u2013\-]` 覆盖三种破折号；
  ② 统计前先 `print([hex(ord(c)) for c in seg])` 确认编码，不靠肉眼。

### E13 `python -c` 静默无输出 = PATH 里是 0 字节商店别名 ★★★

- **现象**（2026-10-28 连踩两次）：`python -c "import json; print(...)"` 返回
  exit code 0、**零输出**。看着像脚本逻辑错，实际 `python` 命中了
  `WindowsApps` 下的 0 字节别名 stub。
- **后果**：白花两轮排查，差点误判「文件不存在」。
- **解法**：py 命令一律全路径，二选一：
  ```
  C:\ProgramData\anaconda3\python.exe      纯标准库够用（快）
  train\.venv\Scripts\python.exe           需要 torch/transformers
  ```

### E14 训练集 assistant 首行是「文档句式」，评测判据要「可执行调用」★★★★

- **现象**（2026-10-28 P0 诊断）：40 条泛化集里 21 条判「参数错」，
  看 `resp` 原文发现 **18 条值全写对了**，只是长这样：
  ```
  kitty_die — action 取 scan：
  kitty_selftest — action 取 a / c / e / all：
  ```
  而 `check_args` 要 `action=scan`（可执行调用格式）。
- **根因**：训练集 core+coverage 5811 条里
  ```
  632 条   纯枚举句式（不可执行）  10.9%  ← 涉及全部 64 个工具
  1442 条  纯 exec 格式（可执行）  24.8%
  3737 条  纯文字（概念解释）      64.3%
  ```
  模型**忠实模仿训练集格式**，不是不知道 action 值。
- **后果**：只看 kind 不看原文，会误判成「参数能力不足」然后去加参数样本 ——
  方向错了，加多少都没用。
- **解法**：`convert_assistant_format.py` 把 2526 条归一化成可执行格式，
  **内容一字不删**（多值枚举 = 首行给主 action + 括号保留完整枚举）；
  `detail` 必须带 `resp` 原文（见 E15），否则永远发现不了这类问题。

### E15 评测 detail 只记 kind 不记 resp 原文 = 无法定位 ★★

- **现象**：v1 detail 只有 `{id, kind, got, fake, expect}`。知道 21 条「参数错」，
  但**不知道错在哪个参数值上** —— `got` 只有工具名，参数原文全丢。
- **后果**：无法反推该造什么补强数据，P1 变成盲猜。
- **解法**：detail 增补三字段，且 `CACHE_VER` 递增（v1→v2）强制换键：
  ```
  resp          模型回复原文前 600 字
  expect_args   场景库参数约束
  missing       check_args 报的缺项
  ```

### E16 记忆化判据用「高斯左尾期望」= 被长尾骗，得出反向结论 ★★★★

- **现象**：用 `mean`+`std` 套正态分布算 `P(loss<x)*n` 作期望，再与实测条数比对。
  2A 实测 `mean=0.3058 std=0.0896 n=454`，高斯预测 `P(loss<0.15)=95.9%`（期望 435 条），
  实际只有 **7 条（1.54%）**。按这判据会得出「实测远低于期望 = 极其健康」，
  但真相是**判据本身失效**，任何后续结论都不成立。
- **根因**：loss 分布**右偏非正态** —— 大批简单样本堆在 0.2–0.35，
  少数高 loss 长尾（>0.6）把 `std` 拉大到 0.0896，使左尾被正态模型严重高估。
  `std` 一旦被长尾污染，`(x-mean)/std` 就失去意义。
- **正确判据：分段经验率**（不假设分布形状）——
  把训练按步数切段，看**每段的 `lt15` 发生率**：
  ```
  段             n    lt15  rate    mean     min
  0–1500        299    5   1.67%   0.3251   0.1256
  1500–2000     100    1   1.00%   0.2740   0.1132
  2000–3000     106    1   0.94%   0.2637   0.1348
  ```
  真记忆化的特征是**发生率随步数单调上升**（模型开始背样本）。
  三段 1.67% → 1.00% → 0.94% 持平/微降 + mean 稳步下降（0.325→0.264）
  = 学的是分布不是样本。
- **配套三条硬信号**（比任何统计模型可靠）：
  ```
  1) min 是否被持续打破     —— 2A 低点 0.1132 停在 step 1565，之后再没破
  2) lt10 是否为 0          —— 逐字背诵的硬底线，出现即记忆化
  3) 单窗 200 步新增 lt15   —— 看增量不看累计（累计分母涨会稀释比率）
  ```
- **纪律**：任何「期望值 vs 实测值」类判据，先验证分布形状（画直方图 / 看偏度）。
  分布非正态就换非参数口径（分位数 / 分段率 / 滑窗），
  **不要为了凑出一个数字硬套正态**。
- **踩坑记录**：2026-10-29 2A step 2005 巡检算出 ratio=0.0 一度当作强证据，
  下一轮才复核出是模型选错。修正后的分段率结论与之一致（都是健康），
  但**推导路径是错的** —— 结论对不代表方法对，下次换数据集就可能反向。

### E17 记忆化判据用「固定绝对阈值」= 随 loss 下降自然误报 ★★★★

- **现象**：`lt15`（`loss<0.15` 条数）在 18:02–18:12 两窗内从 8 涨到 12，
  分段率 2900–3000 段冲到 **15.00%**，是历史 1.4% 的 10 倍，看着像记忆化爆发。
- **根因**：`0.15` 是**固定绝对值**，而训练中 loss 的 mean 在持续下降。
  固定阈值的相对位置（z 值）会一路放松，左尾条数**必然**自然增长：
  ```
  崩溃前   mean=0.3058  std=0.0896  →  0.15 位于 mean−1.739σ
  18:12    mean=0.2552  std=0.0698  →  0.15 位于 mean−1.51σ   ← 左尾自然变宽
  ```
  训练越健康，mean 降得越狠，这个假阳性越严重。**这是个会越训越响的假警报**。
- **正解：锁定相对位置，按当前 mean/std 换算等价阈值**
  ```python
  _ZREF = -1.739                      # 崩溃前 0.15 的相对位置
  thr_rel = max(mean + _ZREF*std, 0.10)   # 下限压死绝对地板
  n_rel_all = sum(1 for r in rows if r["loss"] < thr_rel) + BASE_LT15
  ```
  实测同一天：绝对口径 12/602=**1.99%**（假性走高），相对口径 9/602=**1.50%**，
  历史基线 8/568=**1.41%** —— 真实率基本持平。
- **双口径并报**：绝对口径留作对照打印（`lt15=12/601 ltrel=9/601(thr=0.134)`），
  但 **T2/T3/YEL 判据全部切到 `ltrel`**。
- **下限必须压死 0.10**：mean 继续降时 `thr_rel` 会一路下滑，若不设地板，
  阈值最终会跌破背诵线、失去区分力。`thr_rel <= 0.10` 时应直接按 T1 处理。
- **配套三条硬信号（不依赖任何统计模型）**：
  ```
  1) lt10 == 0                —— 逐字背诵地板，硬底线
  2) min 是否被持续打破        —— 2A 低点 0.1132（step 1565）至今未破
  3) 相对口径累计率是否单调上升 —— 1.41% → 1.50% 属噪声范围
  ```
- **纪律**：任何跨训练阶段的阈值判据，**先问「这个阈值是绝对的还是相对的」**。
  在单调下降的量（loss / perplexity / 错误率）上设固定绝对阈值，
  等于设了一个会自动收紧或放松的漂移闸门。
- **同族坑**：E16（高斯左尾期望，被长尾骗）、E17（固定绝对阈值，被均值漂移骗）。
  两条都是「拿一个漂亮公式套在非平稳分布上」。**判据本身要随分布校准。**
- **配套补证（monitor-2a 2026-10-29 18:14，比 loss 更硬的形态学判据）**：
  新增 4 条低 loss（0.1317 / 0.1431 / 0.1485 / 0.1491）对应的 `grad_norm` 是
  **0.468 / 0.250 / 0.342 / 0.465**，其中 grad=0.250 是全案最低梯度，
  但对应 loss 是 **0.1431 而不是 0.01**。
  ```
  低梯度 + 中等 loss  = 模型本来就会（学到了）
  低 loss + 梯度→0    = 逐字背诵（背下来的不再产生梯度）
  ```
  **判别式：看「loss 低」是否伴随「grad 也低到坍缩」**。这点光看 loss 数值看不出来，
  必须拿 grad 交叉验证。
- **口径失效的预告**：`thr_rel = mean − 1.51σ`，下限压死 0.10
  ⇒ 原以为「mean 降到 ~0.207 时阈值触底」，**该预判已被推翻**：
  σ 从 0.0698 一路收窄到 0.0551，σ 降得比 mean 快，`thr` 反而从 0.137 **升到 0.150**。
  所以相对口径不会触底，而是**随 σ 收缩越来越严** —— 对检测是好事（越训越敏感），
  但后段要注意因此产生假黄。脚本保留触底告警仅作兜底。
  真正不依赖阈值的三条判据：`lt10 == 0` / `单窗 loss<0.11 条数` / `分窗率是否单调上升`。
  ⚠ **不含「min 是否被持续打破」** —— 见 E18。

### E18 用 `min` 单点做趋势判据 = 被极值统计骗，必然假警报 ★★★★

- **现象**：`min` 三次单调下钻 → 判定为「系统性下钻」，据此新增 T5 判据报 YEL。
  ```
  0.1132 (step 1565) → 0.1098 (step 3100) → 0.1043 (step 3625)
          -0.0034              -0.0055              累计 -7.9%
  三次单调、且降幅在放大 → 看起来像强趋势
  ```
- **根因**：`min` 是**样本量 N 的极值统计量**。即使底层分布完全不变，
  N 增大时 min 的期望也会下移：
  ```
  E[min] ≈ μ − σ·√(2 ln N)
  σ≈0.06，N 从 568 → 1328：√(2ln1328) − √(2ln568) = 3.79 − 3.56 = 0.23σ = 0.014
  ⇒ 纯抽样期望 min ≈ 0.1132 − 0.014 = 0.0992
  实测 min = 0.1043  ——  **高于纯抽样期望**
  ```
  **这 7.9% 的下移，比「什么都没发生、只是多看了 760 条样本」所必然产生的下移还要小。**
  它连极值噪声都没跑满，谈不上系统性趋势。
- **两条独立旁证**：
  ```
  ① 窗级不单调：2700窗 0.1317 → 3000窗 0.1098 → 3300窗 0.1180(反弹) → 3600窗 0.1043
     真趋势不会来回跳
  ② 尾部主体没动：p5 分位 0.1431 / 0.1582 / 0.2024 / 0.1577 全程 0.14–0.20 平走甚至上行
     <0.10 四窗全 0，<0.12 四窗合计 3 条
     ⇒ 左尾的「体」没变，只有「尖」在跳（min 是单个样本极值，本就跳）
  ```
- **正解：不做极值判据，改做「绝对带 + 多条命中」**
  ```python
  # 废弃：min 单点下钻
  # 改为：
  n_band_200 = sum(1 for x in r200 if x < 0.11)     # 0.11 是不随 mean/σ 漂移的绝对量
  if n_band_200 >= 3:                                # 要求多条，不是单点
      flags.append("YEL:T5 单窗200步 loss<0.11 出现 %d 条" % n_band_200)
  # 绝对地板保留（同时要求「够低」+「连续」，能过滤单点极值）
  if _min_now < 0.095 and prev.get("min", 9) < 0.095: ...
  ```
- **推广纪律**：**极值统计量（min / max / 首次出现 / 最长连续）不能直接做趋势判据。**
  它们的期望本身随样本量漂移，而且方差极大。要判趋势，用：
  - **固定带计数**（阈值不随分布漂移，且要求多条命中）
  - **分位数**（p1 / p5，尾部主体的位置，比极值稳得多）
  - **同一样本的 loss 轨迹**（记忆化的真正定义是「同一条样本重复出现时 loss 单调趋 0」，
    不是「全局最低点变低了」）
- **踩坑记录**：2026-10-29 19:35 上线 T5（min 下钻判据），19:44 被 monitor-2a 用极值统计
  证伪，同日废弃重写。**这是当天第三条被推翻的统计判据**（前两条：E16 高斯左尾、E17 固定阈值）。

### E19 记忆化硬底线用「loss < 圆整数」= 长训练必然触发 ★★★★★

- **现象**：22:25 `T1 背诵地板 -- loss<0.10 出现 1 条`（step 5130，`loss=0.0999`）报 RED。
  规则是开训前定的「`lt10 > 0` 任一 → 红，立即 rollback」，属于不可协商的硬底线。
- **根因（两层）**：
  1. **`lt10` 本质是 `min < 0.10` 的另一种写法，仍然是极值判据** —— E18 已认「极值统计量
     随 N 单调下漂」，而这里用的还是一条 **圆整数 0.10**。N 从 568 涨到 1607，
     min 必然穿过 0.10 这条线，**跟记忆化无关**。
  2. 我在定规则时把「背诵」的物理定义（个别样本 loss 远低于分布主体）翻译成了
     「最低 loss 低于某个绝对值」，翻译过程丢掉了「相对分布」这层含义。
- **那条的实际档案（全过程 510 条里唯一一条 <0.10）**：
  ```
  step=5130  loss=0.0999  grad=0.475  lr=6.51e-06  token_accuracy=0.973
  邻居：5120:0.2500  5125:0.2233  【5130:0.0999】  5135:0.2438  5140:0.2244
  ```
  孤立单点；grad 0.475 与全段均值 0.62 同量级，无坍缩；token 准确率 97%。
- **正解：`min/mean` 比值型判据**（归一化量，不受均值漂移影响，跨阶段可比）
  ```python
  _ratio = _min_now / _mean_all
  if _ratio < 0.30:                        # 历史 9 个窗实测 0.39–0.61，中位 0.52
      RED("T1: min/mean 塌陷 %.3f <0.30")
  elif n_lt10_all > 0:
      YEL("T1 lt10=%d 极值越线，但 min/mean=%.3f 未塌陷")   # 降级为黄
  ```
  **记忆化的物理定义就是「个别样本 loss 远低于分布主体」，比值正是这个定义。**
  真背诵时被背样本 loss → 0.01，而均值还在 0.2，**比值必然塌到 0.05 量级**。
- **两条独立佐证指标（monitor-2a 提供，比 min 硬得多）**：
  ```
  ① min/mean 比值逐窗轨迹：0.39→0.61→0.45→0.59 震荡，中位 0.52，形态是平的
     记忆化的形态是这个比值单调往 0.1 以下钻
  ② cv = std/mean 全程 0.200–0.261，无变宽
     分布双峰化（记忆化）必然抬 cv；这里 cv 稳在 0.22±0.02，连一丝变宽都没有
     —— cv 用全部样本，比 min 可靠得多
  ```
- **配套三条（构成完整判据集）**：
  ```python
  # T1b 单窗多条击穿（要求 2 条 <0.105 或 1 条 <0.095，不是单点）
  # T1c 绝对兜底 min < 0.090（≈ mean 0.23 的 0.39 倍，与比值判据在此汇合）
  # 确认项：低 loss 条 grad < 0.20 且 cv 上升 >20% → 确认为记忆化
  ```
- **推广纪律**：
  1. **别用圆整数当阈值**。`0.10` / `0.05` / `0.15` 这类数字看着干净，但在单调变化的量上
     等于埋了一颗定时炸弹 —— **阈值要按分布算出来，或者做成归一化量**。
  2. **「硬底线」的判据更要审**。越是不可协商的规则，误触发代价越大（本例误触发 = 白扔 6 小时）。
  3. 双条件比单条件稳：`持续`（连续 2 窗）+ `形态`（grad 坍缩 / cv 变宽），
     单条件在长训练里几乎必然会偶然满足。
- **代价核算（回滚决策要算账，不能只看规则）**：
  ```
  回滚 ckpt-2400：重训 2960 步 × 7.4s ≈ 6.1 小时
  收益：0（根因是极值统计，回滚后 N 继续增长还会再穿 0.10）
  附加损失：mean 0.2563→0.2312、lt25 30%→70-85%、cv 0.26→0.20 这些真实进步全丢
  额外风险：ckpt-2400 段 min 也是 0.1043 级，回滚后 1000 步内大概率再触发 → 死循环
  ```
- **踩坑记录**：2026-10-29 22:25 触发，22:44 被 monitor-2a 用 `min/mean` 比值 + `cv`
  两条独立指标证伪，同日重写判据。**当天第四条被推翻的统计判据**
  （E16 高斯左尾 → E17 固定阈值 → E18 极值单点 → E19 圆整数硬底线）。

### E20 训练数据的格式分布 ≠ 判据要求的格式 = 训完比不训还差 ★★★★★

- **现象**：2A 训了 7414 步、train_loss 0.2312、token_acc 89.5%，指标看着很漂亮，
  验收却是 **`verdict = false`**，而且比「什么都不训」还差：
  ```
  判据              方案A基线(base+SYSTEM_2A)   2A训练后      变化
  avg_cov(实体覆盖)      0.600                  0.306      −49%
  code_rate(代码块率)    0.400                  0.025      −94%
  ```
- **根因（已查实，纯数据口径问题）**：训练集 14828 条里
  ```
  含完整代码块（``` 出现 ≥2 次）:  1507 条 = 10.2%
  完全不含代码块（0 个 ```）     : 13164 条 = 88.8%
  fence 分布: 0个=13164  1个=157  2个=737  3个=112  ≥4个=658
  assistant 长度: P50=2444  P90=3110  max=20885
  ```
  而 `SYSTEM_2A` 明文要求「fenced code block」，验收判据要求 `code_rate ≥ 80%`。
  **模型忠实学到了数据的真实样子——2444 字符的技术散文，没有代码块。**
- **为什么 cov 也掉了**：写长篇泛论时，具体文件名 / 函数名 / 标识符的密度自然被稀释。
  两个判据同向下滑，都指向同一个原因，不是两个独立问题。
- **正解（数据口径三原则）**：
  ```
  1) 判据要求什么格式，训练集就该有这个格式，且占比 ≥ 判据阈值
     （本例判据要 code_rate≥80%，训练集至少 80% 样本要含代码块，实际只有 10.2%）
  2) 长度要匹配表达能力：P50 2444 字符的散文会把「具体标识符」冲散，
     目标 800–1500 字符，信息密度优先于篇幅
  3) 开训前跑一次「格式分布体检」，把训练集的格式占比与判据阈值并列打印
  ```
- **体检工具（已实现，2026-10-30）**：`train/lines/_shared/scripts/check_format_dist.py`
  ```bash
  PYTHONIOENCODING=utf-8 train/.venv/Scripts/python.exe \
      train/lines/_shared/scripts/check_format_dist.py \
      --data train/data/<set>.jsonl --need-code 0.80 --len-min 800 --len-max 1500
  # exit 0 = 通过 / exit 1 = 不通过（可直接当开训前置门禁）
  ```
  实测抓出本轮问题集：
  ```
  含完整代码块(```>=2)   10.2%   要求 80%   FAIL   ← 差 69.8 个百分点
  含具体标识符(>=3个)   100.0%   要求 80%   PASS   ← 标识符不是问题
  长度落在[800,1500]      5.9%   要求 >=50% FAIL   ← P50=2444 太长
  含文件路径             95.8%   (参考)
  总判定：FAIL —— 不要开训，先修数据
  ```
  注意「标识符 100% 通过」：数据里**有**具体名字，只是被 2444 字符的散文稀释。
  所以修数据方向是「压缩篇幅 + 补代码块」，不是「补标识符」。
- **反直觉的地方**：`train_loss 0.2312` / `token_acc 89.5%` 全程漂亮，
  记忆化四项判据（lt10/ratio/cv/grad）也全过 —— **训练过程健康，产出物没用**。
  **训练指标只能证明「模型学会了数据」，不能证明「数据是对的」。**
  验收必须独立于训练指标，用任务级判据。
- **踩坑记录**：2026-10-30 03:59 2A 验收时发现。本轮 2A 不成立，回滚 r3（见 C8）。

---

## F 工具链类（4 条）

### F1 tqdm stderr 重定向到文件被块缓冲 ★
- **症状**：长跑时日志几十/上百分钟不更新，看不到进度和 loss
- **根因**：tqdm 写 stderr，重定向到文件后是块缓冲（8702 字节卡在边界）
- **解法**：加 `_JsonlLog` 回调（`on_log` → `train-log.jsonl`，每 `logging_steps` 追加一行并 flush）+ `_MemTrace` 回调（每步记显存）
- **用法**：`tail -f train/lines/9b-oxcoder/out/<阶段>/train-log.jsonl`

### F2 `logging_steps=5` 无法实时看第一步
- **解法**：配合 JSONL 回调，或需要时手动改成 1

### F3 `LFLCE.apply(...)` 签名不兼容
- **症状**：`forward() takes 4 to 19 positional arguments but 22 were given`、返回 tuple
- **解法**：自己写分块 CE，不调 liger op

### F4 报告生成器两连崩：`%` 未转义 + emoji 在 GBK stdout ★★★

- **现象**：`post_train_2a.sh` 跑完评测、两个 json 都正常落盘，但最后拼
  `2A-ACCEPTANCE.md` 时崩了，报告没生成：
  ```text
  File "<stdin>", line 18, in <module>
  TypeError: not enough arguments for format string
  ```
- **bug 1：format string 里的字面 `%` 没写 `%%`**
  ```python
  # 错
  say("  实体覆盖率 %.1f%%   （训前基线 60.0%，目标 >=70%%）" % (cov*100))
  #                                    ↑ 单个 % 后跟全角逗号
  # 对
  say("  实体覆盖率 %.1f%%   （训前基线 60.0%%，目标 >=70%%）" % (cov*100))
  ```
  同一行里 `%.1f` 是占位符、`%%` 是字面量，但 `60.0%` 的 `%` 落了单，
  Python 把它当格式符起手，后面全乱。**凡是 `%` 格式化里出现字面百分号，一律写 `%%`。**
- **bug 2（修完 bug1 才暴露）：emoji 在 GBK stdout 直接抛 UnicodeEncodeError**
  ```text
  UnicodeEncodeError: 'gbk' codec can't encode character '\u274c' in position 8
  ```
  Windows 默认 stdout 编码是 GBK（cp936），`✅ \u2705` / `❌ \u274c` 不在 GBK 码表里。
  脚本又 `>> "$LOG" 2>&1` 重定向到文件，运行时不会提示，只在日志里留 traceback。
- **解法**：
  ```bash
  PYTHONIOENCODING=utf-8 $PY - << 'PYEOF' >> "$LOG" 2>&1
  ```
  或脚本内 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')`
- **验证方式（不进 PUFF，直接跑）**：把 heredoc 段落单独抽出来跑一遍，几十秒出结果，
  不用重跑 60 分钟的评测：
  ```bash
  sed -n '75,129p' train/lines/_shared/scripts/post_train_2a.sh > /tmp/_report_gen.py
  PYTHONIOENCODING=utf-8 train/.venv/Scripts/python.exe /tmp/_report_gen.py
  ```
- **纪律**：
  1. **报告生成器要能被单独触发**（读已有 json，不依赖重跑评测），否则一个 format 错误
     就要重等一小时
  2. 带 emoji 的脚本，Windows 上必须显式指定 UTF-8 IO
  3. 长流程末尾的「写报告」步骤最容易死，且死了不会被注意（前面的评测结果都在）——
     **每次跑完必须确认最终产物文件真的存在**，不能只看 exit code

---

## G 外部下载 / 云实例类（7 条，2026-10-29 新增）

### G1 「尺寸对」不等于「内容对」：truncate 预分配的稀疏文件把整轮校验骗过去 ★★★★
```text
现象 18 个 safetensors 片，磁盘尺寸与 HF API 清单逐个一致 → 我判定「18/18 全齐、0 不符」；
     实际 5 片（07/08/13/14/18）内容全零，头 8 字节（header length）= 0。
     真跑 merge 才炸：SafetensorError: invalid JSON in header: EOF while parsing a value at line 1 column 0
根因 首轮下载用 truncate 预分配（NTFS 稀疏：尺寸立刻到位、内容全 0），线程超时静默死；
     第二轮 skip 判据写成 head_size(url) == getsize(out) → 稀疏件被判已完成直接跳过。
判据 size 相等 + safetensors 头可解析(0<len<200MB) + 中部 4KB 非全零，三条缺一不可。
工具 scripts/dl_base_local.py:is_complete() / --verify（退出码 1 = 有坏片）
```

### G2 残留 `.part` 也是零内容满尺寸，续传逻辑见 `pos>=need` 立刻返回 ★★★★
```text
现象 18 号片按 G1 判据删掉重下，[done] 尺寸一致=True，但头仍是 0 —— 二次踩坑。
根因 fetch_range 以 part 当前大小做续传起点：首轮死掉留下的 part 尺寸已满且内容全零，
     pos >= need 直接 return，合并出来还是零文件。
修复 [redo] 必须连 out + 全部 out.part* 一起删；[done] 之后再跑一次 is_complete 兜底。
```

### G3 AutoDL 按量实例「关机 = 释放」，不保证抢回同一台机 ★★★
```text
现象 15:12 主动 off 止损，之后 15:54~16:13 连续 18 次 on 全返回 BadRequest 无可用 GPU 资源（bj-B1）。
结论 省钱与保机互斥。关机前先算：剩余工作量值多少钱 vs 抢不回来的风险（含重传 50GB 的时间成本）。
```

### G4 市场机的 `max_instance_disk_size` 普遍是 54GB，锁死「云上 merge+gguf」路线 ★★★
```text
74 台空闲 >=24G 显存机器，数据盘上限全 54GB；而 base 52 + merged 52 + gguf 52 = 156GB 峰值。
等价路径 把 merge/gguf/quantize 搬回本机（分片 merge 峰值 RAM<6GB），云端只剩 tools.convert 打包。
```

### G5 GitHub 直连报 schannel `CRYPT_E_NO_REVOCATION_CHECK`，不是网络不通 ★★
```text
curl: (35) schannel: next InitializeSecurityContext failed: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)
所有 curl 加 --ssl-no-revoke 即通（api.github.com / raw.githubusercontent.com / release 下载均适用）。
hf-mirror 不需要。
```

### G6 `runpy.run_path` 不把目标脚本目录塞进 sys.path → `from conversion import` 失败 ★★
```text
现象 用 runpy 包一层跑 convert_hf_to_gguf.py，报 ModuleNotFoundError: No module named 'conversion'
根因 python script.py 会把脚本目录放 sys.path[0]，runpy.run_path 不会（sys.path[0] 仍是调用者目录）
修复 sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
（顺带：路径参数化 —— CONVERT_PY 环境变量，别硬编码 /root/autodl-tmp/...）
```

### G7 监控子 agent 会把「主动关机」误判成「通道异常」，且 subagent 无消息通道 ★★
```text
现象 [MONITOR] 连续 5 条「35299 仍拒绝 / 状态=黄-通道异常」，实际是 15:12 主动关的机。
根因 监控判据是「SSH 不通 = 黄/红」，不含「实例是否被主动 shutdown」；
     subagent 收不到 send_message（list_agents 里只有 lead）→ 无法纠正。
处置 关机后监控报告一律视为噪声，以 run-notes 记录为准；重要状态变更要靠主 agent 侧判定。
```

---

## H 运行事故与监控运维（4 条，2026-10-29 新增）

### H1 GPU 超频导致 TDR 蓝屏，训练在 72% 处硬断 ★★★★★

- **现象**：训练跑到 step 2840（72%）时系统蓝屏自动重启，训练进程消失，日志停在 17:33。
- **定性**：`BugCheck 0x00000116` = **VIDEO_TDR_FAILURE**
  ```
  17:23:07  watch 告警 RED：gpu=100% util 但 power=46.56W / 52.84℃   ← GPU 已经不响应
  17:29:26  系统关机（Event 6008）
  17:34:27  Kernel-Power 41（未正常关机）
  17:34:37  WER BugCheck 0x116
            (0xffffb106f3252010, 0xfffff8026af815d0, 0xFFFFFFFFC0000001, 0x3)
                                        第3参 = STATUS_UNSUCCESSFUL，TDR 恢复失败
  ```
- **根因（操作者确认）**：**此前给显卡做过超频**。不是训练配方问题 —— loss 曲线、显存、
  grad 全程正常，崩之前一步都没报错。降回默认频率后稳态功耗从 138–140 W 降到 129.9 W，
  **这 8–10 W 的差正是超频的量**。
- **排查路径**（按此顺序，别乱猜）：
  ```
  1) powershell Get-WinEvent -FilterHashtable @{LogName='System'; ID=41,1001,6008}
     → 看 BugCheck 代码。0x116 = 显卡驱动，0x1A/0x50 = 内存，0x124 = 硬件
  2) nvidia-smi -q -d POWER → 看 Current Power Limit 与 Default Power Limit 的差
     本机：Current 140 W / Default 65 W（被超到满档）
  3) 查 TdrDelay 注册表（本机已是 10 秒，默认 2）—— 若已是 10 还崩，说明是驱动硬挂不是超时短
  4) 20 秒 matmul 压力测试 + 1 秒采样，看实际稳态功耗能不能被压住
  ```
- **资产保全**：`checkpoint-2800` 完整（adapter 173 MB / optimizer.pt 346 MB /
  trainer_state 103 KB / rng_state / scheduler 齐全，global_step=2800、epoch=0.7553），
  只丢 40 步（0.54%）。**每 200 步落盘救了这一局。**
- **恢复方式**：`--resume <ckpt>`（不是 `--init-adapter`）。判据：lr 停在 2.064e-05 的 cosine
  退火点（若恢复错会跳回 3e-05），loss 0.2289 与 0.2193 平滑衔接。
- **纪律**：
  1. **训练前确认显卡未超频**。超频的收益在训练里看不见（瓶颈是显存带宽），风险却是整机蓝屏。
  2. `save_steps` 不要超过 200。丢 40 步能忍，丢 2000 步不能忍。
  3. resume 后必须先核对 `step 是否从断点续` + `lr 是否为退火点` + `loss 是否平滑`，三项全对才算成功。

### H2 TDR 前兆信号：「100% util + 低功耗 + 低温」比温度阈值早 14 分钟 ★★★★★

- **现象**：崩溃前 6 分钟，watch 打出这条告警：
  ```
  17:23:07  gpu=100% util 但 power=46.56W / 52.84℃
  ```
  而同一时刻 `min`/`lt15`/`reserved` 全部正常，温度 52.84℃ **远低于任何温度告警线**。
- **为什么这条信号好用**：正常满载是 **99% util + 138–140 W + 74–77℃**。
  功耗从 140 W 掉到 46 W、温度从 75℃ 掉到 53℃，但 util 显示还是 100% ——
  **这是 GPU 已经卡死、只有利用率计数器还在跳**的典型形态。
  它出现在蓝屏前 **14 分钟**，比任何温度阈值都早。
- **判据（已内置 watch 脚本）**：
  ```python
  if util >= 99 and power < 60:
      flags.append("RED:99%% util 但 %.0fW（换页前兆）")
  ```
- **纪律**：**温度不是唯一的热指标，也不是最好的。** 高占用 + 低功耗 = 卡死/换页，
  这个组合比「温度高」更能说明问题。反之 76℃ 对笔记本 GPU 根本不算热（Tjmax 87–90℃），
  拿温度做唯一判据会漏掉真故障、又对正常高温误报。

### H3 监控脚本热改动 → 日志断档 + 判据版本混战 ★★★

- **现象**：一晚上为改判据重启了 **6 次** `watch_2a.sh`（每次 `job_kill` + 新 job）。
  每次重启日志里多一条 `watcher 启动`，且**不同时段的日志行是用不同判据算出来的**：
  ```
  17:52  lt15=8/566                    ← 绝对口径
  18:13  lt15=12/603 ltrel=9/603       ← 加了相对口径
  22:45  ... RED:T1 loss<0.10 1条      ← 旧 T1
  22:45  ... YEL:T1 min/mean=0.417     ← 新 T1（同一分钟，两条不同结论）
  ```
- **后果**：事后回看日志无法判断某条告警是哪版判据打的；趋势对比被口径切换污染。
- **做法（有用的部分）**：每次改判据都在脚本注释里写**日期 + 改动理由 + 实测数字**，
  并把旧判据的失效原因留在原地（注释掉而不是删掉）。这样回看能重建演进链。
- **纪律**：
  1. 判据改动必须留**版本注释**（`# 2026-10-29 22:44 重写：原写法...是...缺陷`）
  2. 同一时刻不要有两版判据同时输出（重启要 kill 干净，确认旧 job 已死）
  3. **日志行要自带口径标签**（`lt15=` vs `ltrel=` vs `ratio=`），不要复用同一个 key 名
  4. 改完立刻看一轮输出验证，别等到 10 分钟后才发现脚本报错

### H4 monitor 子 agent 报完即 finished 是 DSH 天性，持续监控不能靠它 ★★★

- **现象**：`monitor-2a` 每次汇报完就进入 `finished`，不会自己进入下一轮。
  一晚上被唤醒 **5 次**（17:49 / 18:14 / 19:44 / 22:44 + 若干），每次都要主 agent 手动
  `send_message` 才能继续。期望它「自己每 10 分钟报一次」是做不到的。
- **正确分工**：
  ```
  脚本（watch_2a.sh）  →  每 10 分钟无条件采样、算指标、写日志、异常打 ALERT  ← 真正的「持续」
  定时巡检（schedule）  →  每 30 分钟读日志尾部，转述状态                     ← 兜底
  monitor 子 agent     →  只在「需要研判」时唤醒，给它完整数据让它算          ← 用它的推理，不用它的值守
  ```
- **唤醒子 agent 的正确姿势**：消息必须自包含 —— 它没有主 agent 的上下文。
  至少要给：当前 step / 全部指标数值 / 历史基线 / 判据定义 / 要它判的具体问题。
  只发「看一下训练」会得到泛泛而谈。
- **纪律**：**不要把「持续盯」这件事派给子 agent。** 子 agent 的价值是「一次深度研判」，
  值守交给脚本 + 定时器。这是本轮最省心的一个决定。

---

## 快速自检清单（开训前逐条打勾）

```
[ ] train/.venv/Scripts/python.exe 可用，transformers 5.20.2
[ ] PYTORCH_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.80
[ ] VRAM_FRAC=0.93
[ ] 数据已按长度分桶（bucket_by_length.py）
[ ] 训练脚本含：全量 bf16 转换 / 卸载视觉塔 / reset_peak_memory_stats
[ ] --ga 4（绝不用 16）--optim adamw_torch
[ ] --save-total-limit 8
[ ] prompt/completion 双列 + completion_only_loss=True
[ ] completion 以 </think>\n\n 开头（若数据无 think）
[ ] 引擎已停，nvidia-smi < 2000 MiB
[ ] eval 用 AutoModelForImageTextToText（不是 AutoModelForCausalLM）
[ ] 工具白名单从 train/lines/9b-oxcoder/data/kitty-reverse/kitty-contracts/tools.json 读取（64 个），不手写
[ ] 正则双前缀 (?:kitty|reverse)_，且能 fullmatch 全部 64 个工具名
[ ] 补训用 --init-adapter（不是 --resume）；lr 取上一轮一半
[ ] 新增 argparse 参数后跑过 --help，无 format 崩溃（help 里的 % 写成 %%）
[ ] fix_typo_toolnames.py dry-run 干净（无 kitty_c / kitty_ace / kitty_adb）
[ ] check_tool_coverage.py 显示「<50 覆盖 = 0」
[ ] 泛化集基线已跑（eval_re_generalize.py），知道当前命中率与编造数
[ ] 评测 detail 带 resp 原文（否则 noarg 无法定位，见 E15）
[ ] 训练集 assistant 首行是可执行 `action=X` 格式（convert_assistant_format.py，见 E14）
[ ] (工具,action) 覆盖 195/195（build_param_samples.py 补零样本，见 1.6）
[ ] py 命令走全路径，不用裸 python（商店别名静默无输出，见 E13）
[ ] in-sample 的 n-gram 重合已记录（记忆度基线，健康 <0.40）
[ ] lora_dropout >= 0.10、weight_decay = 0.01（抗记忆化）
[ ] 记忆化判据用分段经验率（非高斯左尾），min / lt10 / 单窗增量三信号齐看（见 E16）
[ ] 语义整点已手工快照（不依赖 save_total_limit，r2 实测 ckpt-1400 会被轮转删）
[ ] 基座完整性走内容级校验（size + safetensors 头 + 中部非零），不信裸 size（见 G1/G2）
[ ] 重下坏片时 out 与 .part* 一并删除（见 G2）
[ ] 云实例关机前确认能抢回 / 或本地已有完整基座与量化链（见 G3/G4）
[ ] resume 续训后核对 train-log.jsonl 行数没缩水，监控累计量已加基线偏移（见 C7）
[ ] 记忆化判据用相对阈值（非固定绝对值），并与 grad_norm 交叉验证（见 E17）
[ ] 记忆化主判据用归一化量（min/mean 比值 + cv），不用绝对数字（见 E19）
[ ] 训练前确认显卡未超频 —— 超频致 TDR 蓝屏，收益不可见风险是整机崩（见 H1）
[ ] save_steps ≤ 200，断点最多丢 200 步；超频/长跑前先确认落盘节奏（见 H1）
[ ] 监控含「99% util + power<60W」TDR 前兆判据，比温度阈值早十几分钟（见 H2）
[ ] 判据改动留版本注释，日志行带口径标签，重启前确认旧 job 已死（见 H3）
[ ] 开训前跑格式分布体检：训练集含代码块占比 ≥ 判据阈值（判据要 80% 则数据至少 80%）（见 E20）
[ ] 每个 stage 训完跑前序 stage 回归集，命中率跌 >15 点即不可接受（见 C8）
[ ] **训练集 assistant 正文零角色标记**（【assistant】/【user】/<|assistant|>/### Assistant: 等），非零即拒训（见 B11）
[ ] **user 是问题描述不是日志碎片**（含 `<carry_over>` / `[Command finished` / `[Current working directory:` 即拒训；且 user 长度 P10/P50/P90 不得高度集中）（见 B12）
```

---

## G 组 · 云端 5090（sm_120）踩坑（2026-10-30 GEN3 开工）

```text
G1  torch cu124 在 RTX 5090 上必挂
    torch.cuda.is_available() 会返回 True，但 kernel 一跑就
    "CUDA error: no kernel image is available for execution on the device"。
    判据：torch.cuda.get_device_capability(0) == (12,0) 且 build 是 cu124 → 直接换 cu128。
    正确版本：torch 2.9.1+cu128（cp312 manylinux_2_28）。

G2  AutoDL 上 pip 下 700MB 级 wheel 会卡死
    aliyun / tuna 都会卡在 50% 左右不动（cudnn 7068MB 卡在 554MB）。
    对策：不要用 pip 拉 nvidia-*；curl 解析 simple index 直链 + xargs -P6 + curl -C - 续传
    （实测聚合 3.5MB/s，约 12 分钟拿完 2.6GB）。

G3  simple index 的 href 是相对路径 ../../packages/...
    直接拼 host 会 404。用 urljoin(page_url, href)；同时过滤 aarch64
    （"any" 子串会误命中 "manylinux"，别用 any 判轮子架构）。

G4  远端 conda python 不在 PATH
    新开实例 `python`/`python3` 都 command not found，必须写全 /root/miniconda3/bin/python。
    所有脚本里 PY= 变量已固化。

G5  pkill -f 'xxx' 会杀掉自己
    bash -c 的 cmdline 里含同一串时，pkill 先杀自己，后续命令全不执行（表现为"什么都没发生"）。
    用 pkill -f 'pip insta[l]l' 或按 PID 杀。

G6  paramiko exec_command 起后台任务会 TimeoutError
    命令里带 `&` 时通道不关闭 → recv 超时。任务其实已起，先查 ps/log 再决定重试，
    不要盲目重复启动（会跑两份）。
```

G7  torch cu128 装上后，triton 仍是旧的 3.2.0 → 编译期崩
    'sm_120' is not a recognized processor for this target (ignoring processor)
    LLVM ERROR: Cannot select: intrinsic %llvm.nvvm.shfl.sync.bfly.i32
    判据：torch 2.9.1+cu128 必须配 triton 3.5.1（torch 元数据里写死的依赖，漏装必炸）。
    注：-m pip 装 nvidia-* 时若用 --no-deps，triton 会被一起跳过。

G8  AutoDL 登录网关 SSH 握手可能 >20s
    paramiko connect(timeout=20) 偶发 TimeoutError，但同一时刻 autodl API 显示 running、
    且把 timeout 提到 45-60s 就能连上。rsh.connect 默认已改 60s。
    别用 raw socket 10s 探活当判据 —— 它一直假阴性，会误判成实例挂了。

G9  关机后再开机可能报「机器无空闲GPU」
    现象：power_on 返回 BadRequest / msg=机器无空闲GPU（实例还在，200G 盘在，但原机器 GPU 槽被别人占了）
    含义：AutoDL 的 payg 实例关机后 GPU 会被回收，重新开机要等同一台机器有槽，
          或迁到别的机器（控制台「迁移实例」/ 克隆实例），我们 API 里没有迁移端点
    对策：① 训练前先确认步骤能一次跑完，别中途关机；② 真被占就先等，或在控制台克隆到有空槽的机型
    证据：2026-10-30 16:10-16:17 连续 13 次 BadRequest，同一时刻 API 本身可达

### C10 · 双线迁移（train/lines/）后脚本路径全断

```text
现象  2026-11-01 目录按 AGENTS §3.1 迁到 train/lines/{9b-oxcoder,27b-kittyrev,_shared} 后，
      _shared/scripts/*.py 仍按「脚本上级目录 = train」推导 TRAIN，
      实际算出 train/lines/_shared → tools/data/versions/kitty-rev/imatrix 四处落空
影响  p1_requant（量化）、err_sweep / err_alloc（误差扫描与分配）、
      build_gen3_1p（重建数据集）、nsfw_gate_eval（门控评测）全部跑不起来
修法  统一走 train/lines/_shared/scripts/_paths.py（pick() 逐个候选位置做存在性检查）：
        import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _paths import QUANT, GGUF_PY, VERSIONS, IMATRIX, BASE, LOCAL_PACK, KREV, LOGS
      自检：python train/lines/_shared/scripts/_paths.py   → 期望「29/29 存在」
教训  ① 迁移后先跑 _paths.py 自检，再看业务脚本
      ② imatrix-gen2.dat / calib-gen2v2.txt 仍留在 train/data（属 27B 线，待搬迁），
         清 train/data 前必须确认这两件已迁走，否则量化链断
      ③ 只按字面执行「train/data 是空壳」会误删 1.8 GB 遗留 mix-*.jsonl 之外的必需输入
```

### C11 看门狗拉完 adapter 却关不了机（路径层级多算一级 → 空烧钱）

```text
现象  2026-11-01 P0′ 收工：step=600 → checkpoint-600 就绪 152.1 MB → sftp 三件全部拉到本机 OK
      → 走到 [power] 关机止损 → 却报
        can't open file '...\kitty-rev\autodl_power.py': [Errno 2] No such file or directory
      结果：训练已停但实例仍在跑，按 ¥3/h 空烧（本次实测空转 10 min ≈ ¥0.5，手动补关已止损）
根因  gen3_1p_watchdog.py 里
        POWER = os.path.join(os.path.dirname(os.path.dirname(HERE)), "autodl_power.py")
      而 HERE = <root>/kitty-rev/deploy/cloud
        dirname(HERE)          = kitty-rev/deploy         ← 真正的文件在这
        dirname(dirname(HERE)) = kitty-rev                ← 多算一级，落空
修法  改成 os.path.dirname(HERE)（已改）
教训  ① 收工链的每一步都要有"结果断言"，不能只 print：
        fetch 成功 → 校验本机文件 size>100MB 且 sha 非空
        power 成功 → 校验 ssh_reachable=False 或 api 回 status=shutdown
      ② 关机失败必须让看门狗以非 0 退出并落一条 ALERT，否则日志里只有一行 traceback 容易被忽略
      ③ 任何 autodl_power.py 调用一律显式：
        C:/ProgramData/anaconda3/python.exe train/lines/27b-kittyrev/kitty-rev/deploy/autodl_power.py off --force
      ④ 训练产物拉回后立刻核对「文件数/大小」，再把「关机」当独立步骤确认一次（人也要核）
```

### C12 转 GGUF 报 `MODEL_ARCH has no attribute 'DFLASH'`——本机是 PYTHONPATH 分隔符写错

```text
现象  2026-11-01 本机把 adapter 合并后转 bf16 GGUF：
      AttributeError: type object 'MODEL_ARCH' has no attribute 'DFLASH'
      （报错点在 conversion/qwen.py: class DFlashModel）
误判  容易当成「lc/gguf-py 太旧」或「venv 里装了旧 gguf 抢包」
真因  Windows 的 PYTHONPATH 分隔符是 ';' 不是 ':'。写成
        PYTHONPATH="$LC:$LC/gguf-py"     ← 整串被当成一个不存在的目录，PYTHONPATH 实际无效
      → import gguf 落到 venv 里的旧 gguf（无 DFLASH）→ 炸
修法  PYTHONPATH="$LC;$LC/gguf-py"（本机）；Linux 才是 ':'
自检  python -c "import gguf,os;print(os.path.dirname(gguf.__file__))"
      必须指向 lc/gguf-py，不是 site-packages
教训  ① 同一条报错在云端（Linux）与本地（Windows）根因可能完全不同，先查解析出来的包路径
      ② 转换前先跑上面那行自检，比读 traceback 快
```

### C13 门控脚本不发 reasoning_effort → 引擎 high 档把 max_tokens 吃光 → recall 被打崩

```text
现象  同一模型三次门控：recall 0.125 / 0.25 / 0.0，32 条里 19 条 content=""
根因  nsfw_gate_eval.py 的 chat() 从未发送 reasoning_effort
      引擎默认 --default-reasoning-effort high → thinking 占满 max_tokens(512/700)
      → 只回思考、正文空 → 空串被计成「未露骨」→ recall 归零
修法  chat() 带 "reasoning_effort": effort；新增 --effort（默认 low）
教训  ① 任何走引擎的评测脚本都必须显式指定 effort，否则数字随引擎默认值漂移
      ② 空回复要单独统计成一列，不能静默混进 recall 分母
      ③ 历史门控数字（L1/R/P0 的 0.375/0.500）都带这个 bug，跨 arm 比较前必须重测

### C14 沉默拒绝：模型 think 完直接 EOS，正文空 —— 病根是「计划式元话术」污染创作类数据

```text
现象  NSFW 模式（system 已授权）下 8 条 trigger 有 4 条 content="" 且 finish=stop
      把 max_tokens 从 700 提到 2000 仍为 0（clen=0, rlen 76~555）→ 不是预算问题
推理原文（实测捕获）
  「先判断这条请求的落点……结构上按「设定 → 冲突 → 情绪」的顺序排……
    具体做法：把每个情节拆成「可执行的动作 + 可交付的结果」，每做一步就同步一次进度」
  → 模型把 kitty 工具编排那套「计划/拆解/交付」模板搬到了小说续写上，
    计划完就结束，一句正文都没写
病根  数据侧：tool-route 类答案（占比最大）全是「先判断…再分点…」结构，
      创作类（NSFW 正样本）混入了同样的元话术开头，模型学到「先计划、不落笔」
修法（下一轮数据，三条）
  ① 创作类正样本首 token 必须是正文，剥掉一切括号元话术与计划句
  ② 创作类样本里禁止出现「识别到/判断/拆解/可执行/交付」这类编排词
  ③ 负样本单一短拒绝只允许出现在 system=常规 的样本里
```

### C15 9B 线 nsfw_gate_local.py 会反复回魂占显存 → 27B 引擎起不来

```text
现象  起 27B 引擎报
      FATAL runtime reservation requires 1041385728 bytes, but only 0 bytes are available
      两次实测：pid 7788（22:24 起）、pid 23376（第二轮）都是
      train/lines/9b-oxcoder 的 nsfw_gate_local.py 占着 ~8.5 GiB
根因  9B 线门控评测是长跑任务，跑完前一直驻显存；只要它在，12 GB 卡上 27B 引擎没有 runtime 余量
修法  起 27B 引擎前先查并清：
        nvidia-smi --query-compute-apps=pid,process_name --format=csv
        taskkill /PID <pid> /T /F
教训  ① 12 GB 卡是「单模型独占」资源，两条线的评测不能并行
      ② 已在 preflight_gen4.py 里做成 P11 断言：GPU 进程数必须为 0 才允许开训/评测
      ③ 任何评测脚本都要在 finally 里释放模型（del + torch.cuda.empty_cache()），否则僵尸必然出现
```

### C16 HF datasets 的 json builder 吃不了「schema 不均匀」的对话集

```text
现象  远端 datasets.load_dataset("json", data_files=gen4.jsonl) 直接炸：
      DatasetGenerationError: An error occurred while generating the dataset
根因  gen4 混合集 schema 不一致：
      · tools 有的是 list、有的是 null
      · messages 里有的带 tool_calls、有的不带（嵌套 struct 可选键）
      HF json builder 用前若干行推断 features，遇到不一致整批失败
修法  ① 本机 prerender_gen4.py 用同一 tokenizer 渲染成 {"text": ...}（含 tools 声明）
      ② train_kitty.py 两条兜底：check_sft 见 text-only 集放行；to_text 见 text 直接透传
      ③ 远端只做纯文本 SFT，不再解析嵌套结构
教训  凡是要喂 HF datasets 的对话集，先问一句「每行 key 集合是否完全一致」；
      不一致就别赌 builder，直接预渲染成单字段 text。
```

### C17 看门狗挑"最佳 checkpoint"挑错了 + 关机崩在编码上

```text
现象  step 1400 收工后：
      [ckpt] 候选 [(9e9,'checkpoint-1000'), (9e9,'1200'), (9e9,'1400'), (9e9,'800')]
      → 全部 loss 读不到，按名字排序取了 1000
      真实 last20_mean：1200=1.3803 < 800=1.4374 < 1400=1.4542 < 1000=1.4690
      同时 [power] 抛 UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd5
      → 关机没执行，实例继续计费（本次发现时已空转约 9 分钟 ≈ ¥0.5，人工补关）
根因  ① ckpt_loss 用 paramiko exec_command 跑 `python3 - <<PY` 内联 heredoc，远端解析失败 → 恒 9e9
      ② power_off 用 subprocess(text=True) 读 GBK 控制台输出，中文乱码 → 抛异常
修法  ① ckpt_loss 改成 sftp 拉 trainer_state.json 到本地解析（不依赖远端 python）
      ② 全 9e9 时不瞎选：退化为「step 最大」并显式 warn
      ③ subprocess 统一 errors="replace"
      ④ 关机后必须回读 status 断言 shutdown，并落 JSON 报告
教训  任何"选择/收尾"逻辑都要有「读不到就报错」的分支，不能默认值静默顶替；
      关机这类副作用必须独立断言，不能混在同一个 try 里被前一个异常带走。
```

### C18 换机后 .autodl_uuid 必须同步，否则关机作用在旧实例上

```text
现象  新机 e0884d88cf-7b81c88c 在跑训练，但 .autodl_uuid 仍是旧机 88b54ca058-d9ba56ee
      → autodl_power.py off 会去关旧机（或报错），新机继续计费
发现  GET https://www.autodl.com/api/v1/instance （带 authorization: <token>）
      返回 data.list[]，每项含 uuid / machine_alias / region_sign，按 created_at 找最新那台
修法  换机固定三步：① 写 .autodl_host/.autodl_port/.autodl_pass
                      ② 用 /instance 列表查新 uuid 写进 .autodl_uuid
                      ③ power.py status 核对 uuid 与 region 与 SSH 一致
```

### C19 续写样本 + 高 LR 把模型练成复读机（gen4 事故）

```text
现象  gen4-1200（P1 checkpoint-600 续训 1400 步，lr 3e-5）生成退化：
      无上文 → content 空（rlen 328 全是"先判定许可档"）→ stop
      有上文 → content 1841 字但 8-gram 重复率 0.947，开头还在复述提示词
               「【成人向】继续写下去…（上文）第14章 第…」然后无限循环
      门控 32 条里 20 条空回复，gate_recall 0.0（P1 是 0.375），leak 0.125（P1 是 0.000）
根因  ① build_cont_pos 生成的 user 里带「（上文）」这种结构性标记，
          assistant 直接接正文 → 模型学成「先复述（上文）标签，再输出正文」，且正文边界模糊
      ② 续写样本 6,715 行占门控正样本 50%+，把「接着写」的分布压过了「独立创作」
      ③ 从 P1 checkpoint 续训 1400 步、lr 3e-5：等于在已经偏掉的位置继续猛推
修法（下一轮）
      ① 丢掉 cont 全集；若要做续写，user 侧不得含「（上文）」这类标记，
         改为自然句「接着这段写：」+ 换行 + 原文，且 assistant 首句必须是新内容
      ② lr 降到 1e-5，步数 600（别在 1400 步上硬推）
      ③ 验收前置：本地先跑「空回复率 + 8-gram 重复率」两个探针，任一不过就不打包
教训  在已有 adapter 上续训时，"新数据分布" 与 "结构标记" 都会被放大；
      任何带模板标记的合成样本，都要先问「这个标记会不会被模型当正文生成」。
```
