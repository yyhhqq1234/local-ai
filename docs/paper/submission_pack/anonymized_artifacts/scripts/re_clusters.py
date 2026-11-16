# -*- coding: utf-8 -*-
"""kitty 64 工具的硬负例簇 + 候选集构造（共享模块）

⚠ 与 train/lines/_shared/scripts/eval_re_deploy.py 内的 CLUSTERS 必须保持一致
   （那份是脚本内嵌版，已跑通不动；这份供其它脚本 import）

用途：
  build_system(base_sys, expect, k, seed, extra)  →  「原 system + 候选工具清单」
  供 stability_probe.py 之类需要复用同一采样逻辑的脚本使用。
"""
import io
import json
import os
import random

L9B = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "..")
L9B = "train/lines/9b-oxcoder"
TOOLS = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")

CLUSTERS = [
    ["kitty_ce", "kitty_dump", "kitty_prot", "kitty_km", "kitty_wpb", "kitty_pchain"],
    ["kitty_ghidra", "kitty_ida", "kitty_idamcp", "kitty_sym", "kitty_patch", "kitty_asm"],
    ["kitty_rea", "kitty_rea_binary", "kitty_rea_function", "kitty_rea_trace",
     "kitty_rea_android", "kitty_rea_compare", "kitty_rea_method", "kitty_rea_callpath",
     "kitty_rea_recover_js", "kitty_rea_javascript"],
    ["kitty_assetrip", "kitty_engines", "kitty_gdre", "kitty_cpp2il", "kitty_il2cppdumper",
     "kitty_fmodel", "kitty_unpack", "kitty_dnspy", "kitty_lua"],
    ["kitty_jadx", "kitty_apktool", "kitty_apkscan", "kitty_unpack"],
    ["kitty_dbg", "kitty_x64dbg", "kitty_dualview", "kitty_acescan", "kitty_variants", "kitty_selftest"],
    ["kitty_drv", "kitty_drvio", "kitty_init", "kitty_status"],
    ["kitty_trail", "kitty_settings", "kitty_loop", "kitty_loop_status",
     "reverse_add_target", "reverse_add_intent", "reverse_add_obs",
     "reverse_add_patch", "reverse_add_asset", "reverse_submit"],
    ["kitty_inject", "kitty_frida", "kitty_uedump", "kitty_ue4ss", "kitty_bepinex", "kitty_uexplorer"],
    ["kitty_net", "kitty_proto"],
    ["kitty_ops", "kitty_status", "kitty_selftest"],
]

_RAW = json.load(io.open(TOOLS, encoding="utf-8"))
TMAP = {t["name"]: t for t in _RAW}
ALL = sorted(TMAP)


def fmt_tool(name):
    t = TMAP[name]
    acts = ",".join(t.get("actions") or [])
    desc = (t.get("description") or "").strip().replace("\n", " ")
    if len(desc) > 60:
        desc = desc[:60] + "…"
    return "- %s: %s%s" % (name, desc, ("  actions=[%s]" % acts) if acts else "")


def build_system(base_sys, expect, k, seed=7, extra=0):
    """返回 (system 文本, 实际候选数)。k >= 64 时给全部工具。"""
    rng = random.Random(seed)
    chosen = [n for n in (expect or []) if n in TMAP]
    hard = []
    for n in chosen:
        for cl in CLUSTERS:
            if n in cl:
                hard.extend(cl)
    if not chosen:
        hard = list(CLUSTERS[rng.randrange(len(CLUSTERS))])

    def uniq(seq):
        out, seen = [], set(chosen)
        for x in seq:
            if x in TMAP and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    hard, rest = uniq(hard), uniq(ALL)
    rng.shuffle(hard)
    rng.shuffle(rest)
    cands = chosen + hard[:max(0, k - len(chosen))]
    if len(cands) < k:
        cands += rest[:k - len(cands)]
    if extra:
        pool = [x for x in ALL if x not in cands]
        rng.shuffle(pool)
        cands += pool[:extra]
    rng.shuffle(cands)
    head = "当前会话可用工具（只能从下列工具中选）：\n" + "\n".join(fmt_tool(c) for c in cands)
    return ((base_sys + "\n\n" + head) if base_sys else head), len(cands)
