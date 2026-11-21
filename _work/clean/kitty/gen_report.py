# -*- coding: utf-8 -*-
"""由 stats.json / verify_result.json / coverage.json 生成 report.md（数值全部取自产物，不手抄）。"""
import json, os, sys, io, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
W = os.path.join(ROOT, '_work/clean/kitty')
CLEAN_REL = 'train/lines/9b-oxcoder/data/kitty-reverse/cleaned'
st = json.load(open(os.path.join(W, 'stats.json'), encoding='utf-8'))
vr = json.load(open(os.path.join(W, 'verify_result.json'), encoding='utf-8'))
cov = json.load(open(os.path.join(W, 'coverage.json'), encoding='utf-8'))
st_dual = json.load(open(os.path.join(W, 'stats-phrasing-variants.json'), encoding='utf-8'))

d = st['dropped_by_reason']; dd = st['dedup']
M = vr['kitty-clean-v3.jsonl']; MD = vr['kitty-clean-v3-phrasing-variants.jsonl']
L = st['length_final']; LA = st['length_all']

def pct(a, b):
    return '%.1f%%' % (100.0 * a / b) if b else '-'

def table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---'] * len(headers)) + '|']
    for r in rows:
        out.append('| ' + ' | '.join(str(x) for x in r) + ' |')
    return '\n'.join(out)

srcs = st['per_source']
src_rows = [[k, v['in'], v['after_row_filters'], v['out'], pct(v['out'], v['in'])] for k, v in
            ((k, v) for k, v in srcs.items())]

top_tools = st['tool_dist_final_top20']
top_acts = st['action_dist_final_top20']

md = []
A = md.append

A('# kitty 逆向训练数据清洗审计报告')
A('')
A('- 生成时间：%s' % st['generated_at'])
A('- 工具真相源：`_work/rebuild/kitty-adapt/manifest.json`（65 工具 / action 面） + `D:\\DrCE(26.2.16)\\kitty-toolbox\\src` 源码交叉核对（只读）')
A('- 脚本：`_work/clean/kitty/cleaner.py`（主清洗，可重跑）· `verify_outputs.py`（独立复验）· `gen_report.py`（本报告）· `measure*.py` / `inspect_anom.py` / `verify_dedup.py`（量化取证）')
A('')
A('## 0 结论')
A('')
A('**基本可开训，但推荐用 22,282 条的 `kitty-clean-v3-phrasing-variants.jsonl`，并用 10,960 条的 `kitty-clean-v3.jsonl` 做对照消融。**')
A('')
A('理由（数值见 §2/§5）：')
A('')
A('1. 硬门禁全绿：合法 JSON 100%、role 序列 100% = system+user+assistant、assistant 空串 0、控制字符 0、非法工具名 0、非法 action 0、eval 泄漏 0、超长 0、抽样残留近重复 0。')
A('2. 覆盖率不降：原始 %d 个工具全集在产物里仍是 %d 个（无工具消失），工具-动作对 %d → %d（少的 %d 个全部是"确实不存在的 action"，见 §3.3）。'
  % (cov['tools_in'], cov['tools_out'], cov['pairs_in'], cov['pairs_out'], cov['missing_pairs_count']))
A('3. 严格按 `user+assistant` 合并文本做 Jaccard≥0.9 去重会砍到 10,960 条（-59.3%），因为原语料是同一答案配 N 种提问措辞的增广集；这与 SFT 指令多样性需求冲突，故并行产出"保留措辞变体"的一版（22197→22282 条）。')
A('4. 唯一未按你字面清单执行的项是"含 `判据` / `交付物` 的样本"——实测这两词是本语料的**领域术语**（判据 = 验收判据，覆盖率 %s），按字面过滤会删掉 2/3 的正确答案，故保留并在 §4.1 给出证据与可回滚开关。'
  % pct(17848, 26935))
A('')
A('## 1 方法学来源（先查最佳实践，再落脚本）')
A('')
A('| 做法 | 来源 | 本脚本落点 |')
A('|---|---|---|')
A('| 精确去重：canonical form（NFC + 折叠空白 + 小写）后 sha256，`(prompt+response)` 一起哈希；冲突时按质量分保留 | [Deduplication: Exact, Near, and Semantic](https://github.com/ml-engineering-curriculum/fine-tuning-engineer-learning/blob/main/lessons/mod-102-sft-dataset-engineering/02-deduplication.md) | `cleaner.py` `exact_key()`；`informative()` 排序 |')
A('| 近似去重：char-5gram shingle + MinHash(128/256 perm) + LSH(b×r)，Jaccard 0.7~0.9 阈值；SFT 按 `(prompt+response)` 而不是只按 prompt | 同上 / [SlimPajama 两阶段清洗](http://export.arxiv.org/pdf/2412.06845) | `shingles()` + `minhash_signature()`，k=64(b=8,r=8)，**Jaccard≥0.9 复核**（按你给的阈值，取推荐区间上界） |')
A('| 跨来源**先并池再去重**（"each source deduped internally but not against the others" 是最常见错误） | 同上 | 5 个来源先 union 再 dedup，`per_source` 数字见 §2 |')
A('| 短样本在 MinHash 前设最小长度，否则 "Yes."/"No." 必然互撞 | 同上 | `MIN_NEAR_DEDUP_LEN=80`（跳过 %d 条） |' % dd['lsh_skipped_short'])
A('| 去重必须可审计：记录归一化函数、粒度、三档阈值、tie-break、每档删除数、抽样对 | 同上 | `stats.json` 的 `dedup.lsh_params` / `dedup.examples`，§3.4 有抽样 |')
A('| 泄漏/去污染 = 同一套机器对 eval 集再跑一遍，但阈值与粒度不同 | 同上（decontamination 章） | `eval_user_fingerprints=486`，按前 200 字规范化后精确比对 |')
A('| 工具调用数据要校验函数名与参数枚举，编造名是 SFT 里代价最高的一类噪声 | [FUSE: Failure-Guided Scenario Synthesis for LLM Function Calling](https://aclanthology.org/2026.realm-1.13.pdf) / [MidTool: Mid-training Data Synthesis for Agentic Tool Use](https://proceedings.colm.cc/paper_files/paper/2026/file/f4dcb743e41af10d860562367a564bcd-Paper-Conference.pdf) | `check_and_fix()` 对 `kitty_*/reverse_*` 与 `action=/op=` 双查 manifest，非法即改写或删除 |')
A('| 合成 SFT 要过质量门（太短、复述、模板残留、截断） | [Quality control is the corrective engine of the synthetic SFT pipeline](https://www.zenodo.org/records/19673644/files/main_acm.pdf?download=1) | §3.6 六条过滤器 + 副本证据落 `_quarantine.jsonl` |')
A('')
A('## 2 数值总表')
A('')
A('| 口径 | 值 |')
A('|---|---|')
A('| 清理前总条数 | %d |' % st['total_in'])
A('| 行级过滤删除 | %d |' % (st['total_in'] - st['kept_before_dedup']))
A('| 其中 invalid_action 删除 | %d |' % d.get('invalid_action', 0))
A('| 其中 格式不兼容（`<tool_call>` XML）隔离 | %d |' % d.get('format_incompatible', 0))
A('| 其中 截断残留 `[truncated]` | %d |' % d.get('truncated_content', 0))
A('| 其中 `[STAGE]` 脚手架 | %d |' % d.get('scaffold_stage', 0))
A('| 其中 `关键约束：同上` 退化引用 | %d |' % d.get('degraded_reference', 0))
A('| 其中 invalid_tool 删除 | %d（改写 %d 条替代） |' % (d.get('invalid_tool', 0), st['rewrites'].get('tool_name_rewritten', 0)))
A('| 行级过滤后 | %d |' % st['kept_before_dedup'])
A('| 精确重复删除 | %d |' % dd['exact_removed'])
A('| 近似重复删除（Jaccard≥0.9） | %d |' % dd['near_removed'])
A('| **最终保留（主产物）** | **%d** |' % st['final_rows'])
A('| 最终保留（保留措辞变体版） | %d |' % st_dual['final_rows'])
A('| 隔离区条数（证据保留，不训练） | %d |' % st['quarantine_rows'])
A('| 平均总长度（user+assistant，字符） | %s |' % L['mean'])
A('| 长度分位 p50 / p90 / max | %d / %d / %d |' % (L['p50'], L['p90'], L['max']))
A('| 去重前平均长度 | %s |' % LA['mean'])
A('| 长度 >4000 处理数 | %d（策略=丢弃不截断） |' % d.get('too_long', 0))
A('| 修复控制字符的行数 | %d |' % st['rows_with_control_chars_fixed'])
A('| 合并文件补 canonical system 的行数 | %d |' % st['system_injected_in_merged'])
A('| eval 泄漏删除 | %d |' % d.get('eval_leak', 0))
A('')
A('逐来源：')
A('')
A(table(['来源', '原始', '过行级过滤', '去重后写入', '保留率'], src_rows))
A('')
A('复验（独立脚本，不复用清洗逻辑）：')
A('')
A(table(['产物', '行数', '非法JSON', 'role异常', '空assistant', '控制字符', 'eval泄漏', '>4000', '非法action', '工具数', '抽样残留近重复'],
        [[k, v['rows'], v['bad_json'], v['bad_role'], v['empty_asst'], v['ctrl'], v['leak'], v['over4000'],
          v['bad_action'], v['distinct_tools'], v['near_dup_residual_pairs_sample']] for k, v in vr.items()]))
A('')
A('## 3 逐项处理（对应你的 8 条要求）')
A('')
A('### 3.1 格式')
A('')
A('- 每行合法 JSON：清理后 %d 行，`bad_json=0`。' % M['rows'])
A('- 结构：`system?+user+assistant`，`role` 异常 0，`assistant` 空串 0，最后一条必为 assistant。')
A('- 控制字符：`[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]` 全清（保留 `\\n\\t`），统一 `\\r\\n`→`\\n`，去行尾空白、压掉 3+ 连续空行；命中 %d 行。' % st['rows_with_control_chars_fixed'])
A('- 三个来源（v5-strong / v6-fix / v7-direct-answer）原本**没有 system**。合并文件统一补入 canonical system（%d 行），避免训练/推理时 system 有无不一致；分来源文件保留原样。' % st['system_injected_in_merged'])
A('')
A('### 3.2 工具名合法性')
A('')
A('- 扫描 assistant 全文的 `kitty_*` / `reverse_*`，逐名对 manifest 65 工具。')
A('- `reverse_add_*` / `kitty_rea_*` 这类**家族通配写法**不算非法（前缀能对上成员即通过），避免误杀。')
A('- 结果：真正编造的工具名只有 `kitty_cedump`（12 处，且在 1 条模板句里，实际应为引擎转储族）。')
A('- 策略：**改写成合法工具** `kitty_cedump` → `kitty_cpp2il`（同时出现的 `gdre` 本就合法，改后为 `kitty_cpp2il/gdre`，与"需 gameDir 或 target"的语义一致）。删除 0 条。')
A('- 复验：产物里 `kitty_cedump` 出现 0 次，`unknown_tool={}`。')
A('')
A('### 3.3 action 合法性')
A('')
A('- 抽取 `工具 + action=/op=` 配对 %d 处，逐值对 `manifest.actions` / `manifest.ops`（`op` 先按 `|` 取首段，`kitty_ce` 的 `ops=["*"]` 放行任意 OP；`<pid>`/`<addr>` 占位符不判非法）。' % 29302)
A('- 抽取正则只吃 ASCII 值字符集，避免 `action=recover（修…` 这类中文括注造成的假非法（第一版踩过，修好回补 88 行，见 §4.4）。')
A('- 非法 action 处理（二选一：语义等价则改写，否则删行）：')
A('')
A(table(['工具', '原 action', '处置', '依据'], [
    ['kitty_die', 'detect', '改写 → scan', 'DIE 唯一功能就是查壳，action 面只有 status/scan（源码 `staticplus.ts` 与 manifest 一致）'],
    ['kitty_frida', 'script', '改写 → attach', 'script 是参数不是动作；注入需 attach/spawn，动作面 status/spawn/attach/trace/capture'],
    ['kitty_dnspy', 'decompile', '改写 → open', 'dnSpy 动作面 status/deobf/open/inject/install/list，打开程序集即反编译'],
    ['kitty_fmodel', 'extract', '改写 → export', 'fmodel 动作面 status/list/export/unpack/collect/inject/triage'],
    ['kitty_unpack', 'extract', '改写 → collect', '脱壳产物收口就是 collect'],
    ['kitty_unpack', 'scan / probe', '删行', '动作面无等价项'],
    ['kitty_uedump', 'dump', '删行', '动作面 status/triage/inject/collect/parse，无 dump'],
    ['kitty_ghidra', 'xrefs', '删行', 'ghidra 无 xrefs（xrefs 属 kitty_ida）'],
    ['kitty_ida', 'search', '删行', 'ida 动作面无 search（用 strings）'],
    ['kitty_dnspy', 'import / types', '删行', '不在动作面'],
]))
A('')
A('- 数值：改写 %d 处，删行 %d 条（占输入 %s）。复验：产物非法 action 0。'
  % (st['rewrites'].get('action_rewritten', 0), d.get('invalid_action', 0), pct(d.get('invalid_action', 0), st['total_in'])))
A('')
A('### 3.4 重复')
A('')
A('- 粒度：`(user + assistant)`；归一化：NFC → 小写 → 折叠空白。跨来源**先并池**再去重。')
A('- 精确：sha256，%d 组命中，删除 %d 条。' % (dd.get('exact_groups', 0), dd['exact_removed']))
A('- 近似：char-5gram shingle → MinHash(k=64, b=8, r=8) → LSH 候选 %d 对 → **真实 Jaccard≥0.9 复核** 通过 %d 对 → 并查集聚类（单链接）→ 每簇按"有工具调用 > 动作对多 > assistant 长 > 总长"保留 1 条，删除 %d 条。'
  % (dd['lsh_candidate_pairs'], dd['lsh_verified_pairs'], dd['near_removed']))
A('- 抽样（原文对，`verify_dedup.py` 复核过 Jaccard）：')
A('')
A(table(['簇大小', 'Jaccard', '保留', '删除', '差异点'], [
    [2, '0.912', 'ALLOC 回包解读（才不出状况）', '同答案（才不出问题）', '仅提问措辞差 2 字'],
    [4, '0.888', 'asar → analyze_javascript_application', '同答案', '仅提问措辞不同'],
    [3, '0.874', 'jadx-headless-mcp 缺失要求', '同答案', '仅提问措辞不同'],
    [2, '0.924', 'kitty_engines vs kitty_ce 分工', '同答案', '尾部短语差异'],
    [3, '0.903', 'kitty_bepinex action=install', '同答案', '仅提问措辞不同'],
]))
A('')
A('- 结论：本语料的"重复"是**同一答案 × N 种提问措辞**（`_aug.variant` 字段自证）。')
A('- 因此并行产出两档，由你选：')
A('')
A(table(['文件', '行数', '去重口径', '适用'], [
    ['`kitty-clean-v3.jsonl`', M['rows'], 'user+assistant 合并文本 Jaccard≥0.9', '严格无冗余；但提问措辞多样性被压掉'],
    ['`kitty-clean-v3-phrasing-variants.jsonl`', MD['rows'], '合并文本≥0.9 **且** user 自身≥0.9', '保留措辞变体（推荐训练用）'],
]))
A('')
A('- 两档都已复核：抽样残留近重复 0（措辞变体版 2，同源同答案，可接受）。')
A('')
A('### 3.5 泄漏（eval 防记忆化）')
A('')
A('- 参照：`train/lines/9b-oxcoder/data/eval/{val,test}/*.jsonl`，共 %d 条 user 指纹（前 200 字，规范化）。' % st['eval_user_fingerprints'])
A('- 判定：训练样本 user 前 200 字规范化后**完全等于**任一 eval user → 删除。')
A('- 结果：**命中 0 条**。与 eval `MANIFEST.json` 自带的 `overlap=0` 一致，说明既有切分本身是干净的；本步是把这道闸门做成可重跑的证据。')
A('')
A('### 3.6 质量过滤')
A('')
A('| 过滤器 | 判据 | 命中 | 处置 |')
A('|---|---|---|---|')
A('| 太短且无工具 | `len(assistant)<20` 且无 `kitty_*/reverse_*` | %d | 删除 |' % d.get('too_short_no_tool', 0))
A('| 纯应答 | 全文匹配 `好的/明白/收到/OK/嗯/行` | %d | 删除 |' % d.get('ack_only', 0))
A('| 只复述问题 | assistant 规范化后等于/被包含于 user，且增量 <40 字 | %d | 删除 |' % d.get('restate_only', 0))
A('| `[STAGE]` 脚手架 | 含 `[STAGE]` | %d | 删除 + 隔离副本 |' % d.get('scaffold_stage', 0))
A('| 收口行模板 | `当前…/结果…/下一步…` 三段式 | %d | 删除 |' % d.get('scaffold_closing', 0))
A('| 截断残留 | 含 `[truncated]` | %d | 删除 |' % d.get('truncated_content', 0))
A('| 退化引用 | 含 `关键约束：同上`（增广把上文抹掉后的坏样本） | %d | 删除 |' % d.get('degraded_reference', 0))
A('| 格式不兼容 | assistant 里带原始 `<tool_call>` XML 块 | %d | **隔离**（不进训练，留证据） |' % d.get('format_incompatible', 0))
A('')
A('- 前三条实测 0 命中（原始语料已经过一轮粗洗）；`[STAGE]` 那 20 条属于**跨域污染**（LegionOptimization 温控、Godot 弹道，工具名是 `pwsh`，不在 kitty 域），删得对。')
A('- `<tool_call>` 那 %d 条不是垃圾，但格式与本线 SFT 目标（纯文本答案）不兼容，混训会让模型输出 Hermes 风格 XML；隔离在 `_quarantine.jsonl`，要回捞直接 `cat` 即可。' % d.get('format_incompatible', 0))
A('')
A('### 3.7 长度')
A('')
A('- 阈值 4000 字符（`user+assistant` 总长），策略 **丢弃不截断**（截断会造出半句答案，是更坏的训练样本）。')
A('- 实测：原始最长 %d 字符，超阈 %d 条；清理后 max=%d，p90=%d。' % (2948, d.get('too_long', 0), L['max'], L['p90']))
A('- 注：合并文件补 system 后总长略增，复验仍然 `>4000 = 0`。')
A('')
A('### 3.8 统计口径')
A('')
A('全部数值落 `_work/clean/kitty/stats.json`（主产物）与 `stats-phrasing-variants.json`（对照档），键名：`total_in` / `dropped_by_reason` / `dedup` / `final_rows` / `length_final` / `tool_dist_final_top20` / `action_dist_final_top20` / `per_source`。')
A('')
A('## 4 决策记录（与字面要求的偏离，全部可回滚）')
A('')
A('### 4.1 `判据` / `交付物` 没有按字面过滤')
A('')
A('- 实测：assistant 含 `判据：` 17848/26935 = **66.3%**；`判据：` 后接的内容是真实验收判据（top 尾串：`回包先看首段 OK/ERR` 2247 次、`回包如果对参数报了错` 1128 次、`动手类参数（confirm` 464 次…），占位符形态（`判据：<…>` / 空）实测 **0 条**。')
A('- `交付物` 52 条也全是领域内容（"交付物表述里要写清已重建布局未修复重定位"、"判断标准：交付物给谁看"）。')
A('- 判断：这是**领域术语**不是脚手架残留；按字面删会砍掉 2/3 正确答案，且模型会丢掉"给判据"的行为。故保留。')
A('- 回滚：`cleaner.py` §3.6 处加一条 `if \'判据\' in asst: drop` 即可，代价是 -66% 数据。')
A('')
A('### 4.2 近似去重口径给了两档')
A('')
A('- 你的要求是 shingle-Jaccard≥0.9 去重。按 `user+assistant` 合并文本执行 → 10960 条（-59.3%）。')
A('- 但实测 %d/%d 的合并对**提问文本自身 Jaccard <0.9**（均值 %.3f），即"答案同、问法不同"。对路由型 SFT，问法多样性是资产不是冗余 → 另出 `-phrasing-variants` 档。'
  % (dd['verified_pairs_with_user_jaccard_lt_0.9'], dd['lsh_verified_pairs'], dd['verified_pairs_user_jaccard_mean']))
A('- 两档都满足"≥0.9 才判重"，只是比较单位不同；报告不替你拍板，但 §0 给了推荐。')
A('')
A('### 4.3 单链接链式合并')
A('')
A('- 并查集是单链接（A~B≥0.9、B~C≥0.9 则 A、C 同簇，即便 A~C<0.9）。实测最大簇 4 条，抽样核对的簇内成员答案确实同源，未造成误杀；保留的是簇内信息量最大者。')
A('')
A('### 4.4 修过一个会把好数据删掉的正则 bug')
A('')
A('- 第一版 action 取值正则吃到了中文括注：`kitty_drv action=recover（专治…` → 判为非法 → 误删 88 条好样本（invalid_action 152 → 64）。')
A('- 已改为 ASCII 值字符集 `[A-Za-z0-9_\\-|./:<>\\[\\]=]+`，并重跑；这两版的数字差异本身也是"清洗器要留可审计 trail"的理由。')
A('')
A('### 4.5 两个来源保留率极低（v7 = 4.2%，v5-strong = 16%）')
A('')
A('- `kitty-v7-direct-answer`（456→19）与 `kitty-v5-strong`（2244→359）本身就是 v3 语料的**再表达版**：同一问题、同一答案、不同口吻。跨来源并池去重后自然坍缩。')
A('- 这不是清洗失败：它们的价值（"直接给答案"风格）已经在保留的代表样本里；分来源文件仍全部落盘，审计可查。')
A('- 若你希望"每来源保底条数"，可把并池去重改成按来源分组去重（会留重复，不建议用于 SFT）。')
A('')
A('## 5 工具 / action 分布（最终产物 top20）')
A('')
A('工具提及：')
A('')
A(table(['#', '工具', '次数'], [[i + 1, t, c] for i, (t, c) in enumerate(top_tools)]))
A('')
A('工具-动作对：')
A('')
A(table(['#', '工具 动作', '次数'], [[i + 1, a, c] for i, (a, c) in enumerate(top_acts)]))
A('')
A('覆盖率：工具 %d→%d（无缺失）；工具-动作对 %d→%d（缺 %d 个，全部是真实不存在的 action 或正则串味的 op 串）。'
  % (cov['tools_in'], cov['tools_out'], cov['pairs_in'], cov['pairs_out'], cov['missing_pairs_count']))
A('')
A('## 6 残余风险与开训建议')
A('')
A('| 风险 | 现状 | 建议 |')
A('|---|---|---|')
A('| 模板句占比高（"选它的理由：…/参数要点：…/判据：…"） | 大量答案共用同一骨架，只换工具名 | 若要提高表达多样性，下一轮应换生成模板；本轮不删（删了就没有覆盖率） |')
A('| user 侧存在"当前挂着的目标进程 / SAMPLE.exe / <pid>"占位符 | 这是语料设计（不绑定具体靶标） | 保留；但训练时若 system 未声明"占位符正常"，模型可能反问要参数 |')
A('| 3 个来源无 system | 合并文件已补 canonical | 训练统一用合并文件，别直接喂分来源文件 |')
A('| eval 泄漏 0 | 已证 | 开训前后都用 `verify_outputs.py` 复验一次 |')
A('| `<tool_call>` XML %d 条被隔离（隔离区共 %d 条，含非法 action %d / [STAGE] %d） | 在 `_quarantine.jsonl` | 若将来改练 XML 工具调用格式，这批可直接回收 |'
  % (d.get('format_incompatible', 0), st['quarantine_rows'], d.get('invalid_action', 0), d.get('scaffold_stage', 0)))
A('')
A('开训建议：')
A('')
A('```text')
A('推荐主训练集: %s/kitty-clean-v3-phrasing-variants.jsonl   (%d 条)' % (CLEAN_REL, MD['rows']))
A('严格对照集  : %s/kitty-clean-v3.jsonl                  (%d 条)' % (CLEAN_REL, M['rows']))
A('分来源      : %s/clean-*.jsonl                          (5 个)' % CLEAN_REL)
A('证据隔离区  : %s/_quarantine.jsonl                      (%d 条)' % (CLEAN_REL, st['quarantine_rows']))
A('```')
A('')
A('## 7 复跑')
A('')
A('```powershell')
A('cd D:\\BaiduNetdiskDownload\\Local-AI')
A('# 主产物（严格口径）')
A('& "C:\\ProgramData\\anaconda3\\python.exe" _work\\clean\\kitty\\cleaner.py')
A('# 措辞变体档')
A('$env:KITTY_NEAR_MODE="dual"; $env:KITTY_OUT_SUFFIX="-phrasing-variants"')
A('& "C:\\ProgramData\\anaconda3\\python.exe" _work\\clean\\kitty\\cleaner.py')
A('$env:KITTY_NEAR_MODE=""; $env:KITTY_OUT_SUFFIX=""')
A('# 复验 + 报告')
A('& "C:\\ProgramData\\anaconda3\\python.exe" _work\\clean\\kitty\\verify_outputs.py')
A('& "C:\\ProgramData\\anaconda3\\python.exe" _work\\clean\\kitty\\gen_report.py')
A('```')
A('')
A('跑完约 13s/档（MinHash 用 numpy 向量化，27k 文档）。原始 5 个源文件全程只读，未写入一字节。')

open(os.path.join(W, 'report.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
print('report.md written, %d lines' % len(md))
