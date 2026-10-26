# -*- coding: utf-8 -*-
"""校验 re-sft.jsonl 中每条命令的 工具名+动作 是否都在 contracts/tools.json 内。"""
import json
import re

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
contract = json.load(open(ROOT + r"\train\kitty-rev\contracts\tools.json", encoding="utf-8"))
tools = {t["name"]: set(t.get("actions") or []) for t in contract["tools"]}
# DSH 侧无 action 参数的工具（动作即工具本身）
NO_ACTION = {
    "kitty_ce", "kitty_pchain", "kitty_rea_binary", "kitty_rea_function", "kitty_rea_javascript",
    "kitty_rea_trace", "kitty_rea_android", "kitty_rea_compare", "kitty_rea_method",
    "kitty_rea_callpath", "kitty_rea_recover_js", "kitty_ops", "kitty_status",
    "kitty_selftest", "kitty_settings", "kitty_variants", "kitty_loop", "kitty_loop_status",
    "kitty_dualview", "kitty_acescan", "kitty_drv", "kitty_drvio", "kitty_init",
    "kitty_km", "kitty_wpb", "kitty_trail", "kitty_idamcp", "kitty_rea",
    "reverse_add_target", "reverse_add_intent", "reverse_add_obs", "reverse_add_patch",
    "reverse_add_asset", "reverse_submit", "kitty_dump", "kitty_engines",
}
# 合同外工具**显式白名单**（不是忽略列表）：
# kitty 工具箱没有 minidump 解析与 squashfs 读取能力，转储加载用 cdb、
# 超级块校验用 unsquashfs 是技术正确性的必要选择；每条已在 meta.tools_external 标注，
# 数量由 build_re_sft.py 断言（当前 11 行：10×cdb + 1×unsquashfs）。
# 注意：x64dbg 的 `dd rsp, L20` 是调试器命令，不是 Unix dd，不应误判为外部工具。
EXTERNAL_WHITELIST = {
    "cdb": "minidump 解析（contracts 无转储工具）",
    "unsquashfs": "squashfs 超级块校验（contracts 无文件系统工具）",
}
LINE_RE = re.compile(r"^((?:kitty|reverse)_[a-z0-9_]+)\s*(.*)$")

bad = []
seen = 0
ext_seen = {}
for line in open(ROOT + r"\train\kitty-rev\data\intent3\re-sft.jsonl", encoding="utf-8"):
    row = json.loads(line)
    for raw in row["response"].splitlines():
        ln = raw.strip()
        if not ln or ln.startswith(("判据", "收敛")):
            continue
        em = re.match(r"^(cdb|unsquashfs)\b", ln)
        if em:
            name = em.group(1)
            ext_seen[name] = ext_seen.get(name, 0) + 1
            if name not in EXTERNAL_WHITELIST:
                bad.append((row["id"], name, "external-not-whitelisted"))
            continue
        m = LINE_RE.match(ln)
        if not m:
            continue
        seen += 1
        name, rest = m.group(1), m.group(2).strip()
        if name not in tools:
            bad.append((row["id"], name, "unknown-tool"))
            continue
        acts = tools[name]
        am = re.search(r"\baction=([A-Za-z_]+)", rest)
        if am and acts and acts != {"*"}:
            if am.group(1) not in acts:
                bad.append((row["id"], f"{name} action={am.group(1)}", "bad-action"))
        elif not am and acts and acts != {"*"} and name not in NO_ACTION:
            first = rest.split()[0] if rest else ""
            if first not in acts:
                bad.append((row["id"], f"{name} <{first}>", "missing-action"))

print(f"扫描命令行 {seen} 条；外部工具命令行 {sum(ext_seen.values())} 条 {ext_seen}")
print("白名单：" + "; ".join(f"{k}（{v}）" for k, v in EXTERNAL_WHITELIST.items()))
if bad:
    print(f"FAIL {len(bad)}:")
    for b in bad:
        print(" -", b)
else:
    print("OK 全部工具名与动作均在合同内")
