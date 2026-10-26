#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t37_eval_kitty_rules.py -- kitty23 的 3 条 real-trajectory 必须有规则，且不许 generify（F11）。

缺陷现象
    `eval/eval_kitty.py` 的 RULES 里**没有** real-trajectory 这个键，而 data/eval.jsonl
    的 23 题里有 3 条属于它（idx 2/9/21）：
      · `eval_bare.py:356` 会主动 FATAL（缺规则 = 判据换了，宁可停）；
      · 直跑 eval_kitty 则静默落到 r_generic（只要有 kitty_ 调用就算过）。
    于是 13% 的题换了判据，其中 2 条还是训练原题（向量级记忆可满足）。
后果
    「≥3/23」这条底线可以被"generic + 背过"同时满足 —— 能力判据形同虚设。
正确的断言
    ① eval_kitty --selftest：23 题出现的每个 cat 都有规则；参考答 PASS；空壳答（只有调用没有事实）FAIL
    ② eval_bare --suite kitty23 --dry-run 不再 FATAL，且 3 条 real-trajectory 在场
    ③ judge() 对参考答给 PASS、对"已调用 kitty_ce，完成。"给 FAIL（不许"有调用即过"）
    ④ 污染标记：idx 2/9 在训练集里 → contaminated=True；idx 21 → False（保 n=23，不删题）
    ⑤ 输出契约：eval_kitty 的报告 json 里有 re_detail；eval_bare payload 里有 re_detail 与双总数
如果这条 FAIL 说明什么
    real-trajectory 又被删/generify，或 contaminated / re_detail 契约丢了。
"""
import importlib.util
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
EK = os.path.join(KITTY, "eval", "eval_kitty.py")
EB = os.path.join(KITTY, "tmp", "eval_bare.py")
DATA = os.path.join(KITTY, "data", "eval.jsonl")
PY = sys.executable
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def run(args, timeout=180):
    p = subprocess.run([PY, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONIOENCODING="utf-8"), timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ① 判分器自检
rc, out = run([EK, "--selftest"])
check("① eval_kitty --selftest rc=0", rc == 0, f"rc={rc}")
check("① 每个 cat 都有规则", "[ok ] ① " in out, "")
check("① 参考答判 PASS", out.count("[ok ] ② 参考答") >= 3, "")
check("① 空壳答判 FAIL（不许有调用即过）", out.count("[ok ] ③ 空壳答") >= 3, "")

# ② eval_bare dry-run 不再 FATAL
rc, out = run([EB, "--suite", "kitty23", "--dry-run"])
check("② kitty23 --dry-run rc=0", rc == 0, f"rc={rc}")
check("② 没有「cat 判据缺规则」FATAL", "缺规则" not in out,
      [l for l in out.splitlines() if "FATAL" in l][:1])
check("② 3 条 real-trajectory 在场（dry 行里能看到）",
      out.count("real-trajectory") >= 3, f"出现 {out.count('real-trajectory')} 次")
check("② 条数=23", "23 条就绪" in out, [l for l in out.splitlines() if "条就绪" in l][:1])

# ③ judge 行为：参考答 PASS / 空壳答 FAIL
E = load(EK, "ek_t37")
rows = [json.loads(l) for l in open(DATA, encoding="utf-8") if l.strip()]
rt = [(i, r) for i, r in enumerate(rows)
      if (r.get("meta") or {}).get("cat") == "real-trajectory"]
check("③ 找到 3 条 real-trajectory", len(rt) == 3, f"n={len(rt)}")
check("③ RULES 里有 real-trajectory", "real-trajectory" in E.RULES, str(list(E.RULES))[:60])
for i, r in rt:
    ref = r["messages"][-1]["content"]
    ok_ref, why_ref = E.judge(r, ref, [])
    ok_shell, why_shell = E.judge(
        r, "已调用 kitty_ce，完成。当前:ok / 结果:完成 / 下一步:无",
        [{"name": "kitty_ce", "arguments": {}}])
    check(f"③ idx={i} 参考答 PAN PASS".replace("PAN ", "") if False else
          f"③ idx={i} 参考答判 PASS", ok_ref, why_ref[:60])
    check(f"③ idx={i} 空壳答判 FAIL", not ok_shell, why_shell[:60])

# ④ 污染标记（不删题，只标注）
tt = set()
tr_path = os.path.join(KITTY, "data", "large-mix-plus", "train.jsonl")
if os.path.isfile(tr_path):
    for line in open(tr_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        mm = json.loads(line).get("messages") or []
        if mm and mm[-1].get("role") == "assistant":
            tt.add((mm[-1].get("content") or "").strip())
    flags = {i: ((r["messages"][-1].get("content") or "").strip() in tt) for i, r in rt}
    check("④ idx 2 / 9 标 contaminated=True", flags.get(2) and flags.get(9), str(flags))
    check("④ idx 21 不标（它没进训练集）", flags.get(21) is False, str(flags))
    check("④ 题数不变（不删题保 n=23）", len(rows) == 23, f"rows={len(rows)}")
else:
    check("④ 缺训练集（无法验证污染标记）", False, tr_path)

# ⑤ 输出契约
src_ek = open(EK, encoding="utf-8").read()
src_eb = open(EB, encoding="utf-8").read()
check("⑤ eval_kitty 报告里有 re_detail", '"re_detail"' in src_ek, "")
check("⑤ eval_kitty 双总数（pass_clean/total_clean）",
      '"pass_clean"' in src_ek and '"total_clean"' in src_ek, "")
check("⑤ eval_bare payload 有 re_detail", '"re_detail"' in src_eb, "")
check("⑤ eval_bare summary 有 pass_clean/n_clean/contaminated",
      all(k in src_eb for k in ('"pass_clean"', '"n_clean"', '"contaminated"')), "")
check("⑤ contaminated 是结果字段（不是报告手写）", '"contaminated": bool(' in src_ek, "")

print("\nPASS: real-trajectory 有规则且不 generify，re_detail/contaminated 契约在位"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
