#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Z-B v5 定向增强数据构造（目标：工具选择准确率 75% → ≥90%）

诊断依据 train/lines/9b-oxcoder/out/eval-re-zbv4.json 的 10 条非命中：
  G08 expect kitty_init      got kitty_drv             → 同族混选（通道初始化 vs 驱动守护）
  G13 expect kitty_ce        got kitty_prot            → 同族混选（写值 vs 改保护）+ 漏工具前缀
  G17 expect kitty_ida       got kitty_ghidra          → 同族混选（商业 IDA vs 开源 Ghidra）
  G24 expect kitty_settings  got reverse_add_target    → 跨族混选（会话真相源 vs G3 图谱写）
  G36 expect kitty_trail     got reverse_add_obs       → 跨族混选（探索日志 vs G3 finding）
  G09 expect kitty_dualview  got 4 个工具              → 多工具堆叠，判定取首个即错

三类病根：
  P1 同族/跨族混选 —— 功能相近的工具，模型挑了语义更宽的那个
  P2 漏工具前缀   —— 只给裸 OP（W|0x...）不写 kitty_ce op=
  P3 多工具堆叠   —— 一次罗列 4 个工具，而不是只给该给的那一个

处方：每组混淆对 × 多句式 × 判别线索，全部只用 catalog 里真实存在的工具/action。
输出：data/kitty-reverse/kitty-v5-contrast.jsonl
"""
import json, os, re, sys, itertools, random

HERE = os.path.dirname(os.path.abspath(__file__))
CAT_PATH = os.path.join(HERE, "data", "kitty-tool-catalog.json")
OUT = os.path.join(HERE, "data", "kitty-reverse", "kitty-v5-contrast.jsonl")
SEED = 20251102
random.seed(SEED)

CAT = json.load(open(CAT_PATH, encoding="utf-8"))

# ── 校验工具/动作真实存在（防编造） ──────────────────────────────
def chk(tool, act):
    assert tool in CAT, f"工具不存在: {tool}"
    assert act in CAT[tool]["actions"], f"{tool} 无 action={act}（可用 {CAT[tool]['actions']}）"

# ── 6 组混淆对 ─────────────────────────────────────────────────
# 每组：intents（用户话术）× 正确 (tool, act) × 易混 (tool, act) × 判别句
PAIRS = [
    # ① G08 init vs drv
    dict(
        tag="init_vs_drv",
        intents=[
            "通道起不来，帮我做一键双绿初始化",
            "把 L0/L1/L2 三层跑通，宿主先行再来双驱验真",
            "开一轮 init，把辅助驱、宿主、主驱、CE 心跳全部拉起来",
            "我要 DBVM 前置的完整初始化，不要只修驱动",
            "重新初始化整条通道，从辅助驱开始全量重建",
            "冷启动环境，先跑一次标准 init 流程",
            "三层状态全红，做一次完整初始化而不是单点修复",
            "我要 status 和 init 都走一遍，确认能不能起",
        ],
        tool="kitty_init", act="init",
        why="这是通道初始化：辅助驱 → 宿主 → 主驱 START → 验真 → Use DBVM → 拉 CE 心跳，一次把三层拉通。",
        confuse="kitty_drv",
        why_not=("kitty_drv 的 action 只有 ensure / status / recover / host / storm，"
                 "管的是「驱动与宿主进程的存活与自愈」，不做一键双绿初始化。"
                 "要「起整条通道」用 init；要「修驱动 / 重拉宿主 / 复位熔断」才用 drv。"),
        crit="回包给出 L0/L1/L2 三层状态，全绿即通道就绪；某层 RED 先读该层 err 再决定是否 reload。",
    ),
    # ② G17 ida vs ghidra
    dict(
        tag="ida_vs_ghidra",
        intents=[
            "用商业 IDA 跑一次批处理分析，产物落盘",
            "idat64 走 -A -S 脚本，把函数表和字符串导出来",
            "机器上有 IDA Pro，用它做静态分析",
            "用 IDA 反编译指定函数，要伪代码",
            "跑 IDA 的 analyze，出 functions / strings / xrefs 四件套",
            "静态面走商业反编译器，不要开源的",
            "用 Pro 档工具分析这个 exe，要 decompile 结果",
            "把目标丢给 IDA 批处理，导出入口点与导入表",
        ],
        tool="kitty_ida", act="analyze",
        why="这是商业 IDA 路线（idat64 -A -S + 导出脚本 → JSON 落盘），工具面是 kitty_ida。",
        confuse="kitty_ghidra",
        why_not=("kitty_ghidra 是开源 headless 路线（analyzeHeadless + DumpStage3），"
                 "本机装了 IDA Pro 时不要退到 ghidra —— 两条路的产物目录与后续 offset 口径不同。"
                 "只有明确说「没装 IDA / 用开源方案」时才走 ghidra。"),
        crit="看产物目录是否生成四件套（functions/strings/xrefs/entries），任一为空说明脚本没跑通。",
    ),
    # ③ G24 settings vs reverse_add_*
    dict(
        tag="settings_vs_reverse_add",
        intents=[
            "把当前会话的目标显式定下来",
            "切一下会话目标，再锁模式",
            "读一下现在挂的双字段是什么",
            "会话真相源在哪，把 target 和 mode 设好",
            "退出任务态回到待命，模式改 standby",
            "领取一下上一个会话的目标继承",
            "把宿主绑定改一下，别动目标和模式",
            "看下当前 trail 里记了什么",
        ],
        tool="kitty_settings", act="target-set",
        why=("这是会话真相源动作（target-set / mode-set / target-get / trail-get / host-rebind），"
             "工具面是 kitty_settings —— 双字段、模式锁、trail、宿主绑定都归它。"),
        confuse="reverse_add_target",
        why_not=("reverse_add_target 是 G3 图谱写入口（新建 target 记录、落库里），"
                 "它改的是「逆向图谱数据」，不是「会话运行态」。"
                 "要改会话目标/模式/绑定 → kitty_settings；要往图谱里落记录 → reverse_add_*。"),
        crit="回包带上 current 的 sessionGoal / targetProcess / mode；改完再 target-get 回读确认。",
    ),
    # ④ G36 trail vs reverse_add_obs
    dict(
        tag="trail_vs_reverse_add_obs",
        intents=[
            "把这一步的探索记录记下来",
            "在轨迹里追一条：地址反查命中 3 个",
            "读一下这个目标的探索日志",
            "记一条 R 验证的结果到 trail",
            "把刚才 P_BACK 的回包摘要写进日志道",
            "看下之前几轮都做了什么",
            "给这次定位过程追加一条记录",
            "把这轮的判据结论记到探索日志里",
        ],
        tool="kitty_trail", act="append",
        why="这是 agent 探索日志道（append 写 / get 读），工具面是 kitty_trail。",
        confuse="reverse_add_obs",
        why_not=("reverse_add_obs 是 G3 图谱里的 observation/finding 记录（要 reproSteps、进图库），"
                 "不是探索轨迹。过程性记录写 trail；结论性 finding 才进 reverse_add_obs。"),
        crit="append 回包给出行号；get 能按目标过滤读回刚才那条。",
    ),
    # ⑤ G13 ce W| vs prot
    dict(
        tag="ce_write_vs_prot",
        intents=[
            "把 0x7FF6DADB2450 这个地址的值改成 500",
            "写一个 dword 进去，地址我给了",
            "改内存里的血量字段",
            "把该地址的 dword 覆盖成 999",
            "直接写值，别动保护位",
            "往 0x7FF6DADB2450 写 0x1F4",
            "内存写入一个 int32，地址已知",
            "把那个地址的数值换成我要的",
        ],
        tool="kitty_ce", act="op",
        why=('写内存值走 kitty_ce 的 op 通道，格式 op="W|<addr>|<vt>|<val>"，这是值写入。'),
        confuse="kitty_prot",
        why_not=("kitty_prot 管的是保护位与内存页属性（protect / query / rwx / alloc / free），"
                 "它不写业务值。写值用 ce 的 W|；只有回 ERR|write-fail 或页面只读时，"
                 "才先用 prot action=query 看保护、必要时 prot action=protect 改保护，再回来写。"),
        crit='写完立刻 R|同一地址回读，值一致才算闭环；不一致先查是否被写保护或已换出。',
    ),
    # ⑥ G09 dualview 单工具
    dict(
        tag="dualview_single",
        intents=[
            "三视图比对一下，看 R 和 KM_R 有没有分叉",
            "同址取用户态和内核态两份读，判定是否被挂",
            "跑一次双视图门禁",
            "对 0xADDR 做三视图采样，连续 3 次",
            "看这个地址在三个视图下是否一致",
            "做一次视图分叉检测，落到证据文件",
            "内核面与用户面读数对不对得上",
            "同址三读，给我证据行",
        ],
        tool="kitty_dualview", act="dualview",
        why="三视图门禁是一个独立工具：同址取 R / KM_R / KM_PR 三份读数并落证据行。",
        confuse="kitty_ce+kitty_km+kitty_prot",
        why_not=("不要拆成 kitty_ce + kitty_km + kitty_prot 三连 —— 那样拿到的是三次独立读数，"
                 "没有同址同时采样的语义，也落不了证据。三视图就只用 kitty_dualview 一个工具，"
                 "它内部会把三条路径都走完。"),
        crit="回包给三份 hex + 来源标记；三份不一致即视图分叉，直接作为证据行写入 logs/anti-ace-*.jsonl。",
    ),
]

# ── 句式（覆盖不同用户表达，含口语/碎片句） ────────────────────
PHRASES = [
    "{i}",
    "{i}。直接给调用，别反问。",
    "任务：{i}。选对工具、给全参数。",
    "{i} —— 我要一条能落地的调用。",
    "帮我{i}，按工作台规范来。",
    "{i}？给工具和判据。",
]

# ── P2 漏前缀专项：裸 OP 的纠正 ────────────────────────────────
BARE_FIX = [
    ("W|0x7FF6DADB2450|dword|500", 'kitty_ce op="W|0x7FF6DADB2450|dword|500"'),
    ("R|0x7FF6DADB2450|dword", 'kitty_ce op="R|0x7FF6DADB2450|dword"'),
    ("S_NEW|dword|500|0x10000|0x20000", 'kitty_ce op="S_NEW|dword|500|0x10000|0x20000"'),
    ("MODENUM", 'kitty_ce op="MODENUM"'),
    ("P_BACK|0xADDR|0x10000|0x20000", 'kitty_ce op="P_BACK|0xADDR|0x10000|0x20000"'),
]
BARE_Q = [
    "内存写应该发什么？就一条。",
    "读这个地址的 dword，给我能直接发的那一行。",
    "按地址扫 500 这个值，起止我给了，给我一条指令。",
    "列一下模块，我要能直接发的。",
    "反查这个地址，扫窗我给了，给一条指令。",
]

# ── P3 单一工具纪律 ────────────────────────────────────────────
DISCIPLINE_Q = [
    "这个任务你打算调几个工具？先给我最关键的那一个调用。",
    "别罗列备选，直接给我该用的那一个工具和参数。",
    "一次只发一个调用，先做最该做的那步。",
    "把你准备用的工具收敛成一条，多余的不要写。",
    "先给第一个动作，后面的看回包再说。",
]


def asst(tool, act, why, confuse, why_not, crit, extra_call=None):
    """统一 assistant 骨架：单一工具 + 选它理由 + 易混点 + 判据"""
    line1 = f"{tool} action={act}"
    if tool == "kitty_ce" and act == "op":
        line1 = '{tool} action=op op="W|0x7FF6DADB2450|dword|500"'.format(tool=tool)
    s = [line1, "", f"选它的理由：{why}", f"易混点：{confuse} —— {why_not}", f"判据：{crit}"]
    if extra_call:
        s.append(f"备注：{extra_call}")
    s.append("一次只给这一个调用，不罗列备选工具。")
    return "\n".join(s)


def main():
    rows = []
    # ① 6 组混淆对
    for p in PAIRS:
        chk(p["tool"], p["act"])
        c_tool, c_act = (p["confuse"].split("+")[0], p["act"]) if "+" not in p["confuse"] else (None, None)
        for i, raw in enumerate(p["intents"]):
            for ph in PHRASES:
                q = ph.format(i=raw)
                a = asst(p["tool"], p["act"], p["why"], p["confuse"], p["why_not"], p["crit"])
                rows.append({"messages": [{"role": "user", "content": q},
                                          {"role": "assistant", "content": a}],
                             "meta": {"src": "zbv5-contrast", "pair": p["tag"],
                                      "tool": p["tool"], "action": p["act"]}})
    n1 = len(rows)

    # ② P2 裸 OP → 带前缀
    n2 = 0
    for (bare, fixed), q in zip(BARE_FIX, BARE_Q):
        a = (f"{fixed}\n\n"
             f"为什么必须带工具名：裸 OP（{bare}）不是工具调用，harness 收不到；"
             f"kitty_ce 的通道是 action=op / action=batch，OP 要放进 op= 里。\n"
             f"判据：回包首行 OK/ERR；BATCH 用 action=batch ops=[...]，一次投递多条。\n"
             f"一次只给这一个调用，不罗列备选工具。")
        for qq in (q, q + "（只要一行，不要解释）", q + "。给完整可发的形式。"):
            rows.append({"messages": [{"role": "user", "content": qq},
                                      {"role": "assistant", "content": a}],
                         "meta": {"src": "zbv5-bare-op", "bare": bare}})
            n2 += 1

    # ③ P3 单一工具纪律
    n3 = 0
    for q in DISCIPLINE_Q:
        a = ("一次只发一个调用。先做最该做的那一步，拿到回包再决定下一步。\n\n"
             "为什么：罗列多个工具会让执行层同时挂多条通道，回包互相干扰，也定位不了哪一步失败。"
             "多步任务的正确形态是「调用 → 看回包 → 再决定下一步」，不是预先铺开整套计划。\n"
             "判据：每条调用都能对应到一个具体判据；没有判据的调用就是纯猜测，不要发。\n"
             "一次只给这一个调用，不罗列备选工具。")
        for qq in (q, q + " 例：内存写。", q + " 例：三视图比对。"):
            rows.append({"messages": [{"role": "user", "content": qq},
                                      {"role": "assistant", "content": a}],
                         "meta": {"src": "zbv5-discipline"}})
            n3 += 1

    # ── 去重 ──
    seen, out = set(), []
    for r in rows:
        k = r["messages"][0]["content"] + "\x00" + r["messages"][1]["content"]
        if k in seen:
            continue
        seen.add(k)
        out.append(r)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[OUT] {OUT}")
    print(f"  混淆对 {n1} · 裸OP纠正 {n2} · 单一工具纪律 {n3} → 去重后 {len(out)}")
    from collections import Counter
    c = Counter(r["meta"]["src"] for r in out)
    print("  分布：", dict(c))
    c2 = Counter(r["meta"].get("pair", "-") for r in out)
    print("  混淆对明细：", dict(c2))


if __name__ == "__main__":
    main()
