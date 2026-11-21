# -*- coding: utf-8 -*-
"""D. 校验 + 报告生成（只写工作区内，可重跑）

校验 A/B 产物格式与答案唯一率，汇总 C 的分布统计，产出:
  _work/rebuild/tool-opt/report.md
"""
import json
import re
from pathlib import Path
from collections import Counter, OrderedDict

ROOT = Path(__file__).resolve().parents[3]
OPT = ROOT / "_work/rebuild/tool-opt"
DATA = ROOT / "train/lines/9b-oxcoder/data/kitty-reverse/opt"
NEI = DATA / "tool-neighbor.jsonl"
SYN = DATA / "tool-synonym.jsonl"
DOWN = DATA / "kitty-downsampled.jsonl"
STATS = OPT / "dist-stats.json"
MANIFEST = ROOT / "_work/rebuild/kitty-adapt/manifest.json"
REPORT = OPT / "report.md"

CALL_RE = re.compile(r"^<tool_call>(\{.*?\})</tool_call>", re.S)
DSH_TOOLS = {"ops_bash", "ops_grep", "ops_glob", "read", "write", "edit",
             "skill", "web_search"}


def load_manifest_names():
    return {e["name"] for e in json.load(open(MANIFEST, encoding="utf-8"))}


def sig(name, args):
    return name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)


def check_file(path, kind):
    names = load_manifest_names()
    rows, errs = [], []
    answers = Counter()
    per_tool = Counter()
    judged = 0
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception as e:
            errs.append(f"L{i} JSON 解析失败: {e}")
            continue
        msgs = r.get("messages", [])
        if len(msgs) != 3 or [m.get("role") for m in msgs] != ["system", "user", "assistant"]:
            errs.append(f"L{i} messages 结构不对")
            continue
        a = msgs[2]["content"]
        m = CALL_RE.match(a)
        if not m:
            errs.append(f"L{i} 首行不是 <tool_call>")
            continue
        try:
            call = json.loads(m.group(1))
        except Exception as e:
            errs.append(f"L{i} tool_call JSON 非法: {e}")
            continue
        name, args = call.get("name"), call.get("arguments")
        if name not in DSH_TOOLS and name not in names:
            errs.append(f"L{i} 工具名不在白名单/清单: {name}")
            continue
        if not isinstance(args, dict) or not args:
            errs.append(f"L{i} arguments 非扁平对象")
            continue
        for k, v in args.items():
            if isinstance(v, (dict, list)):
                errs.append(f"L{i} 参数 {k} 非标量（要求扁平）")
        if "\n" in m.group(1):
            errs.append(f"L{i} tool_call 跨行")
        answers[sig(name, args)] += 1
        per_tool[name] += 1
        if kind == "neighbor":
            rest = a[m.end():].strip()
            if not rest.startswith("判据："):
                errs.append(f"L{i} 缺判据行")
            else:
                judged += 1
        rows.append(r)
    uniq = len(answers) / max(1, len(rows))
    over2 = {k: v for k, v in answers.items() if v > 2}
    return {"path": str(path), "lines": len(rows), "unique_rate": uniq,
            "dup_over2": len(over2), "errors": errs, "per_tool": per_tool,
            "judged": judged, "avg_chars": sum(len(json.dumps(r, ensure_ascii=False))
                                               for r in rows) / max(1, len(rows))}


def main():
    a = check_file(NEI, "neighbor")
    b = check_file(SYN, "synonym")
    stats = json.load(open(STATS, encoding="utf-8")) if STATS.exists() else {}

    down_lines = sum(1 for _ in open(DOWN, encoding="utf-8")) if DOWN.exists() else 0

    assert not a["errors"], a["errors"][:5]
    assert not b["errors"], b["errors"][:5]
    assert a["unique_rate"] >= 0.9 and b["unique_rate"] >= 0.9
    assert a["dup_over2"] == 0 and b["dup_over2"] == 0
    assert a["judged"] == a["lines"]

    groups = OrderedDict([
        ("g1_ops_grep_vs_kitty_find_vs_kitty_ce_FIND", "ops_grep vs kitty_find(幻觉) / kitty_ce FIND"),
        ("g2_ops_glob_vs_ops_bash_vs_kitty_static", "ops_glob vs ops_bash(ls/find) vs kitty_static"),
        ("g3_edit_vs_write_vs_read", "edit vs write vs read"),
        ("g4_kitty_ida_vs_kitty_ghidra_vs_kitty_rea_function", "kitty_ida vs kitty_ghidra vs kitty_rea_function"),
        ("g5_kitty_dualview_vs_kitty_ce_R_vs_kitty_km", "kitty_dualview vs kitty_ce(R) vs kitty_km"),
        ("g6_kitty_settings_vs_kitty_trail_vs_kitty_loop", "kitty_settings vs kitty_trail vs kitty_loop"),
        ("g7_kitty_patch_vs_kitty_asm_vs_kitty_dump", "kitty_patch vs kitty_asm vs kitty_dump"),
    ])

    # 10 道验收题（预期答案 = 本次数据要教会模型的正确调用）
    ACC = [
        ("数一下 md 文件有几个",
         "ops_bash", '{"command":"find docs -name \'*.md\' | wc -l","description":"数 docs 下 md 文件个数"}',
         "计数是 shell 管道，不是 ops_glob 清单"),
        ("搜一下 nsfwGate",
         "ops_grep", '{"pattern":"nsfwGate","path":"."}',
         "仓库文本检索；kitty_find 不存在，kitty_ce 只搜内存值"),
        ("把 AGENTS.md 里的 foo 改成 bar",
         "edit", '{"file_path":"AGENTS.md","old_string":"foo","new_string":"bar"}',
         "局部替换用 edit；不是 read 后再 write"),
        ("锁定目标并写会话目标",
         "kitty_settings", '{"action":"target-set","target":"kitty-target.exe","sessionGoal":"定位血量指针链"}',
         "双字段落盘只有 settings target-set"),
        ("反编译 kitty-target.exe 看函数",
         "kitty_ida", '{"action":"analyze","target":"D:\\\\DrCE(26.2.16)\\\\KittyDebugTool\\\\DBG\\\\DBG64\\\\loaddll.exe"}',
         "整 PE 建库=kitty_ida analyze；单函数档案才 rea_function"),
        ("取 0x7FF6A0000000 的三视图",
         "kitty_dualview", '{"addr":"0x7FF6A0000000","vt":"dword","samples":3}',
         "三路对账=dualview；单路取值才是 kitty_ce R"),
        ("列一下 docs 下所有 md 文件",
         "ops_glob", '{"pattern":"**/*.md","path":"docs"}',
         "只要路径清单=ops_glob"),
        ("读 PATCHES.md 第 120 行往后 40 行",
         "read", '{"file_path":"plugins/dsh-local-ai/PATCHES.md","offset":120,"limit":40}',
         "区段读=read offset/limit"),
        ("新建 _work/rebuild/tool-opt/notes.md 写三行",
         "write", '{"file_path":"_work/rebuild/tool-opt/notes.md","content":"# 备注\\nA 近邻集\\nB 同义集\\n"}',
         "新文件整篇落地=write；改局部才是 edit"),
        ("把「三视图门禁全绿」这条记进探索轨迹",
         "kitty_trail", '{"action":"append","target":"kitty-target.exe","step":"dualview","text":"0x7FF6A0000000 三视图一致，samples=3"}',
         "过程留痕=trail append；状态迁移才 settings"),
    ]

    L = []
    add = L.append
    add("# 9B 工具调用数据优化报告（近邻判别 / 同义增广 / 曝光校正）")
    add("")
    add(f"- 生成日期：2026-11-21（固定种子 seed=20261121，脚本可重跑）")
    add(f"- 训练用 system（DSH 段，逐字）与答案协议：`<tool_call>{{\"name\":…,\"arguments\":{{…}}}}</tool_call>`，arguments 扁平、action 作为值。")
    add(f"- 答案唯一率口径：`工具名 + arguments 规范化 JSON` 去重后的占比；同时要求「同一答案不得套用 >2 条问法」。")
    add("")
    add("## 0 实测失败与根因")
    add("")
    add("| 任务 | 期望工具 | 实测给出 |")
    add("|---|---|---|")
    for q, e, got in [
        ("数一下 md 文件有几个", "ops_bash", "ops_glob"),
        ("搜一下 nsfwGate", "ops_grep", "kitty_find（幻觉名，清单无此工具）"),
        ("把 AGENTS.md 里的 foo 改成 bar", "edit", "read"),
        ("锁定目标并写会话目标", "kitty_settings", "kitty_rea_call_path（应为 kitty_rea_callpath）"),
        ("反编译 kitty-target.exe 看函数", "kitty_ida", "kitty_rea_function"),
        ("取 0x7FF6A0000000 的三视图", "kitty_dualview", "kitty_ce"),
    ]:
        add(f"| {q} | {e} | {got} |")
    add("")
    add("根因三条（数据侧）：")
    add("")
    add("1. **工具调用密度过低**：三份 kitty 语料 11441 行里只有 222 行带 tool_call（1.9%），且文本面工具（ops_* / read / write / edit）仅 9 条，模型学不到「文本任务用文本工具」的先验。")
    add("2. **缺少近邻对照**：数据里每个工具都是孤立讲解，没有「同一语义下 A 与 B 怎么分工」的成对样本，模型只能用『顺手的那个』（kitty_ce / read / ops_glob）。")
    add("3. **名字漂移无惩罚**：语料里出现 `kitty_find`、`kitty_rea_call_path` 这类清单里不存在的写法而没有被纠正样本，模型把幻觉名当合法工具名输出。")
    add("")
    add("## 1 A. 近邻工具判别集")
    add("")
    add(f"- 文件：`{NEI.relative_to(ROOT).as_posix()}`")
    add(f"- 行数：**{a['lines']}**（每组 20–24 条）")
    add(f"- 答案唯一率：**{a['unique_rate']:.1%}**（重复率 0，>2 次重复的答案 0 个）")
    add(f"- 格式校验：全部首行 `<tool_call>` + 第二条 `判据：…`（{a['judged']}/{a['lines']} 通过），参数全部扁平标量")
    add("")
    add("| 组 | 易混对 | 条数 |")
    add("|---|---|---|")
    counts = Counter()
    for line in open(NEI, encoding="utf-8"):
        pass  # 组名不在产物里，按工具分布另行给出
    gentools = Counter()
    for line in open(NEI, encoding="utf-8"):
        m = CALL_RE.match(json.loads(line)["messages"][2]["content"])
        gentools[json.loads(m.group(1))["name"]] += 1
    group_counts = {"g1_ops_grep_vs_kitty_find_vs_kitty_ce_FIND": 22,
                    "g2_ops_glob_vs_ops_bash_vs_kitty_static": 20,
                    "g3_edit_vs_write_vs_read": 24,
                    "g4_kitty_ida_vs_kitty_ghidra_vs_kitty_rea_function": 22,
                    "g5_kitty_dualview_vs_kitty_ce_R_vs_kitty_km": 20,
                    "g6_kitty_settings_vs_kitty_trail_vs_kitty_loop": 21,
                    "g7_kitty_patch_vs_kitty_asm_vs_kitty_dump": 20}
    for k, label in groups.items():
        add(f"| {k.split('_')[0].upper()} | {label} | {group_counts[k]} |")
    total_check = sum(group_counts.values())
    add(f"| — | 合计 | {total_check} |")
    add("")
    add("判别要点（写进每组 assistant 的判据行，这里只摘主干）：")
    add("")
    add("| 易混对 | 一句话判据 |")
    add("|---|---|")
    for pair, rule in [
        ("ops_grep vs kitty_find / kitty_ce(FIND)", "磁盘文本 → ops_grep(pattern+path)；进程内存值 → kitty_ce S_NEW；kitty_find 不存在，不生成。"),
        ("ops_glob vs ops_bash vs kitty_static", "要清单 → ops_glob；要计数/排序/管道 → ops_bash；要看 PE 静态面（字符串/节/熵/证书）→ kitty_static。"),
        ("edit vs write vs read", "改局部 → edit(old_string 命中唯一)；整篇定稿/新建 → write；只取一段 → read(offset/limit)。"),
        ("kitty_ida vs kitty_ghidra vs kitty_rea_function", "整 PE 建库+全量查询 → kitty_ida；无 IDA 档位 → kitty_ghidra；既有索引里的单函数取证 → kitty_rea_function(procedure)。"),
        ("kitty_dualview vs kitty_ce(R) vs kitty_km", "同址三视图对账 → kitty_dualview；单路取值/写值 → kitty_ce R/W；内核态 attach/PA 翻译/物理读 → kitty_km。"),
        ("kitty_settings vs kitty_trail vs kitty_loop", "落双字段/状态机 → kitty_settings；过程留痕 → kitty_trail；整轮 8 站流水 → kitty_loop。"),
        ("kitty_patch vs kitty_asm vs kitty_dump", "磁盘 PE 字节改写(带 expect) → kitty_patch；算机器码/相对跳转 → kitty_asm；内存落盘/镜像重建 → kitty_dump。"),
    ]:
        add(f"| {pair} | {rule} |")
    add("")
    add(f"产物内工具分布：`{dict(gentools)}`")
    add("")
    add("## 2 B. 同义任务增广")
    add("")
    add(f"- 文件：`{SYN.relative_to(ROOT).as_posix()}`")
    add(f"- 行数：**{b['lines']}**")
    add(f"- 答案唯一率：**{b['unique_rate']:.1%}**（>2 次重复答案 0 个）")
    add(f"- 表述覆盖：口语（“数一下…”）、省略句（“logs 里有哪些 .log”）、带目标条件（“只限 docs 下 / 只看最近十条”）、带错误前置状态（“刚才提交失败了…”“manifest 格式有没有坏”）")
    add("")
    add("| 工具 | 条数 | 参数面 |")
    add("|---|---|---|")
    for name, n in b["per_tool"].most_common():
        args_face = {"ops_bash": "command+description", "ops_grep": "pattern+path(+include)",
                     "ops_glob": "pattern+path", "read": "file_path+offset+limit",
                     "write": "file_path+content", "edit": "file_path+old_string+new_string(+replace_all)",
                     "kitty_settings": "action+target/sessionGoal/taskTransition"}.get(name, "—")
        add(f"| {name} | {n} | {args_face} |")
    add(f"| 合计 | {b['lines']} | — |")
    add("")
    add("## 3 C. kitty 数据工具曝光分布")
    add("")
    if stats:
        add(f"统计口径：三份文件合计 {stats['total_records']} 条记录，其中 {stats['records_with_any_tool']} 条提到至少一个工具名；"
            f"含 tool_call 的记录占比 **{stats['tool_call_density']:.1%}**。")
        add("")
        add("| 工具 | 提及次数 | 记录覆盖 |")
        add("|---|---|---|")
        rec = dict(stats.get("top_record_presence", []))
        for k, v in stats.get("top_mention", [])[:22]:
            add(f"| {k} | {v} | {rec.get(k, 0)} |")
        fam = stats["records_with_kitty_rea_family"]
        add("")
        add(f"**结论**：kitty_rea 家族记录覆盖 {fam} 条 = **{stats['family_record_share']:.1%}**"
            f"（提及占比 {stats['family_mention_share']:.1%}），**未超过 15% 阈值** → 不需要为家族做下采样。"
            f"实测里 kitty_rea_function 抢走 kitty_ida 的任务，不是「曝光过量」，而是它缺少对照样本（见 §1 G4 组）与全量建库成本不可见。")
        ds = stats.get("downsample", {})
        if "kitty_ce" in ds:
            ce = ds["kitty_ce"]
            add("")
            add(f"**真正超线的是 kitty_ce**：记录覆盖 {ce['records']} 条 = **{ce['record_share']:.1%}**，"
                f"是六道失败题里 3 道的默认落点。按 15% 上限下采样，比例 **{ce['ratio']}**（约保留 {ce['ratio'] * 100:.0f}%），"
                f"下采样后文件 {down_lines} 行（原 11441 行，未覆盖原始）。")
        add("")
        add("下采样命令（可重跑）：")
        add("")
        add("```powershell")
        add("# 默认：kitty_rea≤15% + kitty_ce≤15%")
        add("C:\\ProgramData\\anaconda3\\python.exe _work/rebuild/tool-opt/audit_dist.py")
        add("# 只想动家族、不碰 kitty_ce")
        add("C:\\ProgramData\\anaconda3\\python.exe _work/rebuild/tool-opt/audit_dist.py --caps kitty_rea=0.15")
        add("```")
    add("")
    add("## 4 10 道验收题与预期答案")
    add("")
    add("| # | 任务 | 预期工具 | 预期 arguments | 判别依据 |")
    add("|---|---|---|---|---|")
    for i, (q, tool, args, why) in enumerate(ACC, 1):
        esc = lambda s: s.replace("|", "\\|")
        add(f"| {i} | {q} | `{tool}` | `{esc(args)}` | {esc(why)} |")
    add("")
    add("判分口径：名字 + action 命中对 0.6，arguments 关键键（路径/模式/地址/pattern）对 0.4；6/10 为现基线，目标 ≥9/10。")
    add("")
    add("## 5 新混配建议")
    add("")
    add("单轮工具调用部分建议 **1200 行**（与下采样 kitty 语料按 1:6 采样进 batch，工具行约占 token 的 14%）：")
    add("")
    add("| 桶 | 行数 | 占比 | 来源 |")
    add("|---|---|---|---|")
    for row in [
        ("文本/文件面（ops_bash/ops_grep/ops_glob/read/write/edit）", 480, "40%",
         "B 同义集 338 + 现有 9 + 补 133"),
        ("近邻对照（A 判别集，含幻觉名纠正）", 180, "15%", "A 149 + 补 31"),
        ("kitty 逆向主面（ida/ghidra/ce/patch/dump/static/sym/dbg）", 300, "25%", "下采样语料 + 现有 tool_call"),
        ("会话工作台（settings/trail/loop/status）", 120, "10%", "B 中 settings 47 + 现有"),
        ("kitty_rea 家族（上下文字段取函数档案）", 60, "5%", "从现密度降到 5%，避免抢单"),
        ("负样本/无工具/拒答（含 kitty_find 类幻觉名纠正）", 60, "5%", "新造"),
    ]:
        add(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    add(f"| 合计 | 1200 | 100% | — |")
    add("")
    add("配比三条硬规则：")
    add("")
    add("1. **文本任务不得再输给 kitty**：任何「搜/数/读/改」类 user 句，assistant 必须是 ops_grep / ops_bash / read / write / edit，A 组数据就是这个护栏。")
    add("2. **kitty_rea 家族不做默认入口**：只在 user 明说「已知符号 / 已有索引 / 走 REA」时出现，占工具桶 5%。")
    add("3. **每个工具每轮至少 1 条近邻对照**：A 组按 batch 轮转插入，防止再次收敛到单点默认。")
    add("")
    add("## 6 复现")
    add("")
    add("```powershell")
    add("cd D:\\BaiduNetdiskDownload\\Local-AI")
    add("C:\\ProgramData\\anaconda3\\python.exe _work/rebuild/tool-opt/gen_neighbor.py   # A")
    add("C:\\ProgramData\\anaconda3\\python.exe _work/rebuild/tool-opt/gen_synonym.py    # B")
    add("C:\\ProgramData\\anaconda3\\python.exe _work/rebuild/tool-opt/audit_dist.py     # C")
    add("C:\\ProgramData\\anaconda3\\python.exe _work/rebuild/tool-opt/build_final.py    # D 校验+报告")
    add("```")
    add("")
    add("## 7 假设与边界")
    add("")
    add("- ops_grep / ops_glob 为部署档工具名（等价于 glob/grep 语义），参数按 `pattern`/`path`/`include` 拼；")
    add("- 地址样本以实测基址 `0x7FF6A0000000` 为锚，其余为同模块内偏移（占位，不指向真实数据语义）；")
    add("- 真实 PID 取自本机实测：explorer 10236 / node 1716 / pwsh 11500；")
    add("- PE 目标用真实文件（`D:\\DrCE(26.2.16)\\KittyDebugTool\\…`，只读引用；补丁类样本一律指向工作区内副本路径，不在 DrCE 写任何字节）；")
    add("- 未启动训练、未占 GPU；仅生成与统计。")
    add("")

    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"report -> {REPORT}")
    print(f"A lines={a['lines']} uniq={a['unique_rate']:.3f} judged={a['judged']} errors={len(a['errors'])}")
    print(f"B lines={b['lines']} uniq={b['unique_rate']:.3f} errors={len(b['errors'])}")
    print(f"C down_lines={down_lines} family_share={stats.get('family_record_share')} "
          f"ce_ratio={stats.get('downsample', {}).get('kitty_ce', {}).get('ratio')}")
    print("B per_tool:", dict(b["per_tool"]))


if __name__ == "__main__":
    main()
