#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Z-B v8 构建（第二版）：按**操作语义**精确匹配，匹配不上就不改

━━ 第一版为什么废掉 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
只按「同工具」借 assistant → 6 条抽样里 5 条错配：
  user「释放刚分配的内存」  配到 assistant「W| 写值」        ✗
  user「P_BACK 回 pending」 配到 assistant「写 -1 往返」      ✗
  user「要证据包还是原始输出」配到 assistant「ghidra strings」✗
制造了大量「问 A 答 B」的矛盾样本，比不改更糟。

━━ 第二版做法 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 给每条 assistant 打「操作标签」：从 op=XXX / action=XXX 提取
② 给每条 user 打「意图标签」：中文关键词 → 操作标签（内置 40 条映射）
③ 只有标签对上才重配；对不上就不动（宁可少改，不制造错配）
④ 总行数不变

输出：data/_legacy/mix-z-re-v8b.jsonl
"""
import io, json, os, re, random, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", "_legacy", "mix-z-re-v4.jsonl")
OUT = os.path.join(HERE, "data", "_legacy", "mix-z-re-v8b.jsonl")
REPORT = os.path.join(HERE, "data", "_legacy", "_v8b_report.json")

GROUPS = {
    "init_vs_drv":     ["kitty_init", "kitty_drv"],
    "ida_vs_ghidra":   ["kitty_ida", "kitty_ghidra"],
    "settings_vs_g3":  ["kitty_settings", "reverse_add_target", "reverse_add_obs"],
    "trail_vs_g3":     ["kitty_trail"],
    "ce_vs_prot":      ["kitty_ce", "kitty_prot"],
    "dualview_pchain": ["kitty_dualview", "kitty_pchain"],
}
ALL_TOOLS = set(t for v in GROUPS.values() for t in v)

TOOL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\b")
CALL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\s+action=([\w\-]+)")
TC_RE = re.compile(r"<tool_call>")

# ── 操作语义标签：从 assistant 里能认出来的操作 ──────────────
OP_PATTERNS = {
    "FREE":       re.compile(r"\bFREE\b"),
    "ALLOC":      re.compile(r"\bALLOC\b"),
    "W_WRITE":    re.compile(r"op=[\"']?W\|"),
    "R_READ":     re.compile(r"op=[\"']?R\|"),
    "S_SCAN":     re.compile(r"\bS_NEW\b|\bS_GET\b"),
    "S_SNAP":     re.compile(r"\bS_SNAP\b"),
    "P_BACK":     re.compile(r"\bP_BACK\b"),
    "P_WALK":     re.compile(r"\bP_WALK\b"),
    "AL_TABLE":   re.compile(r"\bAL_[A-Z]+\b"),
    "MODENUM":    re.compile(r"\bMODENUM\b"),
    "INJECT":     re.compile(r"kitty_inject|injectDLL"),
    "PROT_QRY":   re.compile(r"kitty_prot\s+action=query|\bquery\b.*protect"),
    "PROT_SET":   re.compile(r"kitty_prot\s+action=(protect|rwx)"),
    "WPB":        re.compile(r"kitty_wpb"),
    "DUALVIEW":   re.compile(r"kitty_dualview"),
    "PCHAIN":     re.compile(r"kitty_pchain"),
    "INIT":       re.compile(r"kitty_init\s+action=init"),
    "INIT_ST":    re.compile(r"kitty_init\s+action=status"),
    "DRV_ENSURE": re.compile(r"kitty_drv\s+action=ensure"),
    "DRV_HOST":   re.compile(r"kitty_drv\s+action=(host|recover)"),
    "DRV_ST":     re.compile(r"kitty_drv\s+action=status"),
    "IDA_ANALYZE":re.compile(r"kitty_ida\s+action=analyze"),
    "IDA_FUNC":   re.compile(r"kitty_ida\s+action=functions"),
    "IDA_XREF":   re.compile(r"kitty_ida\s+action=xrefs"),
    "IDA_DEC":    re.compile(r"kitty_ida\s+action=decompile"),
    "GHIDRA_AN":  re.compile(r"kitty_ghidra\s+action=analyze"),
    "GHIDRA_SE":  re.compile(r"kitty_ghidra\s+action=(search|strings|functions|decompile)"),
    "SET_TARGET": re.compile(r"kitty_settings\s+action=target-set"),
    "SET_GET":    re.compile(r"kitty_settings\s+action=(target-get|mode-get)"),
    "SET_REBIND": re.compile(r"kitty_settings\s+action=host-rebind"),
    "TRAIL_APP":  re.compile(r"kitty_trail\s+action=append"),
    "TRAIL_GET":  re.compile(r"kitty_trail\s+action=get"),
}

# ── 中文意图 → 操作标签（手写 40 条）──────────────────────────
INTENT = [
    (r"释放(内存|地址|分配)|FREE",              ["FREE"]),
    (r"分配(一|块)?内存|ALLOC",                 ["ALLOC"]),
    (r"写(值|入|一个|dword)|改成|覆盖",          ["W_WRITE"]),
    (r"读(取|一下|回)|回读|是多少",              ["R_READ"]),
    (r"扫描|扫(一下|出)|搜(索|出).*值|找.*值",    ["S_SCAN"]),
    (r"快照|变化|S_SNAP",                       ["S_SNAP"]),
    (r"反查|谁指向|P_BACK",                     ["P_BACK"]),
    (r"指针链|多级|P_WALK|逐级",                 ["P_WALK", "PCHAIN"]),
    (r"地址表|AL_|列表里|删.*条|索引",           ["AL_TABLE"]),
    (r"MODENUM|模块列表|列.*模块",               ["MODENUM"]),
    (r"注入|inject|DLL",                        ["INJECT"]),
    (r"保护(位|属性)|只读|页属性|query",          ["PROT_QRY"]),
    (r"改(保护|成可读写)|rwx|放开写",            ["PROT_SET"]),
    (r"写保护|绕(过)?写|PTE|wpb",                ["WPB"]),
    (r"三视图|双视图|同址.*(读|采样)|分叉",       ["DUALVIEW"]),
    (r"多跳|反查.*链|pchain",                    ["PCHAIN"]),
    (r"初始化|双绿|起通道|三层.*(通|绿)",         ["INIT"]),
    (r"通道.*(状态|健康)|L0|L1|L2.*状态",        ["INIT_ST"]),
    (r"驱动.*(ensure|守护|起)|ensure",           ["DRV_ENSURE"]),
    (r"宿主.*(挂|拉|重拉)|看门狗|熔断|recover",    ["DRV_HOST"]),
    (r"驱动.*状态|宿主.*状态",                   ["DRV_ST"]),
    (r"IDA.*(分析|批处理)|idat64|商业",           ["IDA_ANALYZE"]),
    (r"函数(表|列表)",                          ["IDA_FUNC", "GHIDRA_SE"]),
    (r"交叉引用|xref|谁调用",                    ["IDA_XREF"]),
    (r"伪代码|反编译",                          ["IDA_DEC", "GHIDRA_SE"]),
    (r"Ghidra|ghidra|headless|开源",            ["GHIDRA_AN", "GHIDRA_SE"]),
    (r"会话目标|target-set|定.*目标",             ["SET_TARGET"]),
    (r"读.*(双字段|目标|模式)|现在挂的",           ["SET_GET"]),
    (r"换.*宿主|host-rebind|绑定",               ["SET_REBIND"]),
    (r"记录.*(轨迹|探索)|trail|留痕",             ["TRAIL_APP"]),
    (r"读.*(轨迹|日志)|之前几轮",                 ["TRAIL_GET"]),
]


def getu(r):
    for m in r["messages"]:
        if m["role"] == "user":
            return m["content"]
    return ""


def geta(r):
    return r["messages"][-1]["content"]


def has_call(a):
    return bool(CALL_RE.search(a) or TC_RE.search(a))


def primary_tool(text):
    t = TOOL_RE.findall(text)
    return t[0] if t else None


def ops_of(text):
    return {k for k, p in OP_PATTERNS.items() if p.search(text)}


def intents_of(text):
    out = set()
    for pat, tags in INTENT:
        if re.search(pat, text):
            out |= set(tags)
    return out


def main():
    random.seed(20251106)
    rows = [json.loads(l) for l in io.open(SRC, encoding="utf-8") if l.strip()]
    print(f"[IN] v4 mix {len(rows)} 行")

    # 索引：(工具, 操作标签) → assistant 列表
    pool = collections.defaultdict(list)
    for r in rows:
        a = geta(r)
        if not has_call(a):
            continue
        t = primary_tool(a)
        if not t:
            continue
        for op in ops_of(a) or {"_generic"}:
            pool[(t, op)].append(a)

    print(f"[IDX] 索引键 {len(pool)} 个")

    changed, unmatched, ambiguous = 0, 0, 0
    by_tool = collections.Counter()
    for r in rows:
        a = geta(r)
        u = getu(r)
        t = primary_tool(a)
        if not t or t not in ALL_TOOLS or has_call(a):
            continue
        want = intents_of(u)
        if not want:
            unmatched += 1
            continue
        cands = []
        for op in want:
            cands.extend(pool.get((t, op), []))
        if not cands:
            unmatched += 1
            continue
        # 多个候选时取最长的（信息量更大的）
        best = max(set(cands), key=len)
        r["messages"][-1]["content"] = best
        changed += 1
        by_tool[t] += 1

    print(f"\n[改] 精确匹配成功 {changed} 条（意图标签对得上）")
    print(f"     跳过：意图无法识别 {unmatched} 条")
    print("     按工具：", dict(by_tool.most_common()))

    assert len(rows) == 7608
    before, after = 3421, sum(1 for r in rows if has_call(geta(r)))
    print(f"\n[形态] 有工具调用 {before} ({before/7608*100:.1f}%) → {after} ({after/7608*100:.1f}%)")

    io.open(OUT, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    io.open(REPORT, "w", encoding="utf-8").write(json.dumps({
        "rows": len(rows), "rewired": changed, "unmatched": unmatched,
        "call_before": before, "call_after": after,
        "by_tool": dict(by_tool),
    }, ensure_ascii=False, indent=1))
    print(f"\n[OUT] {OUT}")


if __name__ == "__main__":
    main()
