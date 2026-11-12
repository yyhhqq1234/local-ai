# -*- coding: utf-8 -*-
"""一次性：把 check_args 替换成支持 tool_call JSON 的版本

原因：训练集 v3 里有 900 条（3.8%）assistant 是
    <tool_call>{"name":"kitty_ce","arguments":{"action":"selftest"}}</tool_call>
原 check_args 只认 `action=scan` 内联写法，遇到 JSON 会误判 noarg。
"""
import io

P = "train/lines/_shared/scripts/eval_re_generalize.py"
src = io.open(P, encoding="utf-8").read()

start = src.index("def check_args(text, spec):")
end = src.index("def classify(resp, expect, args_spec=None):")
old = src[start:end]

new = '''def check_args(text, spec):
    """检查参数填充（训练集 56.6% 是「文字+带参数」，原来完全不测）

    spec 形如 {"action": ["scan","detect"]} 或 {"op": r"W\\|"}
    ★ op 写「值的正则前缀」，不要加 ^（^ 在正则中间是行首断言，不是值开头）

    ★ 2026-10-28 补：训练集 v3 里有 900 条（3.8%）是标准 tool_call JSON
        <tool_call>{"name":"kitty_ce","arguments":{"action":"selftest"}}</tool_call>
      这种写法用 `action=` 正则完全不匹配 → 会被误判成 noarg。
      三种写法都要认：
        内联      action=scan        / op=R|0x..|dword
        JSON      "action": "scan"   / "op": "R|0x..|dword"
        带引号    action='scan'
    返回 (ok, missing_list)
    """
    if not spec:
        return True, []
    t = text or ""
    missing = []
    acts = spec.get("action")
    if acts:
        ok = False
        for v in acts:
            esc = re.escape(v)
            if re.search(r"action\\s*=\\s*[\\"']?%s" % esc, t):
                ok = True
                break
            if re.search(r'"action"\\s*:\\s*"%s"' % esc, t):
                ok = True
                break
            if re.search(r"'action'\\s*:\\s*'%s'" % esc, t):
                ok = True
                break
        if not ok:
            missing.append("action∈{%s}" % ",".join(acts))
    op = spec.get("op")
    if op:
        # op 的 spec 本身是正则片段（如 W\\|），不能 escape
        if not (re.search(r"op\\s*=\\s*[\\"']?%s" % op, t)
                or re.search(r'"op"\\s*:\\s*"%s' % op, t)
                or re.search(r"'op'\\s*:\\s*'%s" % op, t)):
            missing.append("op~%s" % op)
    return (not missing), missing


'''

src2 = src[:start] + new + src[end:]
io.open(P, "w", encoding="utf-8").write(src2)

# 语法 + 行为自检
import ast
ast.parse(src2)
print("[syntax] OK")

import importlib.util
spec_ = importlib.util.spec_from_file_location("erg", P)
m = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(m)

cases = [
    ("inline  hit ", "kitty_die action=scan target=x", {"action": ["scan", "status"]}, True),
    ("json    hit ", '<tool_call>{"name":"kitty_ce","arguments":{"action":"selftest"}}</tool_call>',
     {"action": ["selftest"]}, True),
    ("json    miss", '<tool_call>{"name":"kitty_ce","arguments":{"action":"batch"}}</tool_call>',
     {"action": ["selftest"]}, False),
    ("quote   hit ", "kitty_die action='status'", {"action": ["scan", "status"]}, True),
    ("op      hit ", "kitty_ce op=R|0x1000|dword", {"op": r"R\\|"}, True),
    ("op json hit ", '<tool_call>{"name":"kitty_ce","arguments":{"op":"R|0x1000|dword"}}</tool_call>',
     {"op": r"R\\|"}, True),
    ("empty spec  ", "whatever", {}, True),
]
bad = 0
for name, txt, sp, want in cases:
    got, miss = m.check_args(txt, sp)
    flag = "OK " if got == want else "FAIL"
    if got != want:
        bad += 1
    print("  [%s] %s -> %s (want %s) miss=%s" % (flag, name, got, want, miss))
print("[selftest] %s" % ("全部通过" if bad == 0 else "%d 项失败" % bad))
