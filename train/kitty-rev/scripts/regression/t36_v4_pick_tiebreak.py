#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t36_v4_pick_tiebreak.py -- 选优的次级键不许是 val_loss（F7）。

缺陷现象（F7）
    v4_pick.sh 的次级排序键原本是 `re-subset.val.jsonl` 的 loss。而该集 72 行
    **100% 落在训练集内**（F3）：它衡量的是"背得熟不熟"。re60 的差分噪声 ±3 题，
    三候选极易打平 —— 打平后按"背得最熟"收尾 = **系统性挑出最过拟合的那个 epoch**。
后果
    交付的是过拟合版，而报告里一切正常（有表、有推荐、有理由）。
正确的断言
    ① 排序键里不再出现 val_loss；`--ctx` 默认 4096（不是 512，512 会把 prompt 截成断头）
    ② 假候选 A：re60 打平、val 一高一低（低的在**最后一步**）→ 不许选 val 低的那只
    ③ 假候选 B：re60 打平但配对翻正数有差 → 选配对赢的那只（哪怕步数更晚）
    ④ 缺 re_detail（无法配对）→ 不崩，且报告里点明"配对数为 0，只能靠 re 通过数定胜负"
如果这条 FAIL 说明什么
    次级键又漂回 val_loss，或配对比较被删（打平后又按"背得熟"决定）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(KITTY, "deploy", "cloud", "v4_pick.sh")
PY = sys.executable
NL = chr(10)
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


if not os.path.isfile(SCRIPT):
    print(f"\nFAIL: 缺 {SCRIPT}")
    sys.exit(1)
src = open(SCRIPT, encoding="utf-8").read()

# ---- ① 源码级三条
check("① 排序键不含 val_loss（key() 里没有 val）",
      "val_loss 已弃用" in src and "不参与排序" in src, "")
m = re.search(r"def key\(x\):(.*?)\nrows\.sort\(key=key\)", src, re.S)
# 只看代码行：注释里那句「val_loss 不在键里」是说明，不是排序键（t29 踩过同一坑）
key_code = NL.join(l for l in (m.group(1).splitlines() if m else [])
                   if not l.lstrip().startswith("#"))
check("① key() 代码里不出现 val", bool(m) and "val" not in key_code, key_code[-60:])
check("① 次级键 = 配对翻正数", bool(m) and "wins" in m.group(1), "")
check("① --ctx 默认 4096", "CTX=${CTX:-4096}" in src, "")
check("① 判据行写明 val_loss 已弃用", "val_loss 已弃用" in src, "")

# ---- 抽取脚本里那段真排序代码（不是复制品：每次从磁盘现取）
# 注意 heredoc 可能是 `<<'PY' || die "…"`，所以 <<'PY' 后面允许有别的字符
hm = re.search(r"<<'PY'[^\n]*\n(.*?)\nPY\n", src, re.S)
check("① 能从 v4_pick.sh 抽出排序段（断言测的是真代码）", bool(hm),
      f"len={len(hm.group(1)) if hm else 0}")
if not hm:
    print(f"\nFAIL: {fails}")
    sys.exit(1)
RANK_PY = hm.group(1)

root = tempfile.mkdtemp(prefix="rg-t36-")
try:
    def build(cands, table, passmaps):
        d = os.path.join(root, "pick")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        for name, path in cands.items():
            os.makedirs(path, exist_ok=True)
            with open(os.path.join(path, "adapter_model.safetensors"), "wb") as f:
                f.write(b"\x00" * 16)
            if passmaps.get(name) is not None:
                with open(os.path.join(d, name + ".json"), "w", encoding="utf-8") as f:
                    json.dump({"re_detail": [{"i": i, "pass": bool(v)}
                                             for i, v in passmaps[name].items()]}, f)
        with open(os.path.join(d, "_summary.json"), "w", encoding="utf-8") as f:
            json.dump({"table": table, "best": "tool-says-735"}, f)
        return d

    def run_rank(cands, table, passmaps):
        d = build(cands, table, passmaps)
        md = os.path.join(root, "pick.md")
        cands_s = ",".join(f"{n}:{p}" for n, p in cands.items())
        p = subprocess.run([PY, "-", os.path.join(d, "_summary.json"), cands_s, md,
                            "/base", d],
                           input=RANK_PY, capture_output=True, text=True, encoding="utf-8",
                           errors="replace",
                           env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                           timeout=120)
        txt = (p.stdout or "") + (p.stderr or "")
        best = None
        if os.path.isfile(md):
            for line in open(md, encoding="utf-8"):
                if line.startswith("[PICK] candidate="):
                    best = line.split("=", 1)[1].strip()
        return p.returncode, txt, best

    def pm(passes, n=60):
        return {i: (i in passes) for i in range(n)}

    # ② 打平 + val 一高一低（低的是最后一步）→ 不许选它
    cands = {"245": os.path.join(root, "ck245"), "735": os.path.join(root, "ck735"),
             "final": os.path.join(root, "final")}
    same = pm(set(range(0, 40)))                      # 三个候选逐题完全一致
    table = {n: {"re_pass": 40, "re_total": 60, "kitty_pass": 20, "kitty_total": 23,
                 "val_loss_by_file": {"re-subset.val.jsonl": v}}
             for n, v in (("245", 1.20), ("735", 0.50), ("final", 0.90))}
    rc, txt, best = run_rank(cands, table, {n: same for n in cands})
    check("② 打平场景 → rc=0", rc == 0, f"rc={rc}")
    check("② 不许选 val 最低的 735（过拟合那只是它）", best != "735", f"best={best}")
    check("② 打平后按步数升序（选最早）", best == "245", f"best={best}")

    # ③ 配对有差 → 选配对赢的（哪怕更晚）
    a_pass = set(range(0, 40))
    b_pass = a_pass | {50, 51, 52}                    # 490 比 245 多过 3 题（A fail B pass）
    cands2 = {"245": os.path.join(root, "ck245b"), "490": os.path.join(root, "ck490b")}
    table2 = {n: {"re_pass": 40, "re_total": 60, "kitty_pass": 20, "kitty_total": 23,
                  "val_loss_by_file": {"re-subset.val.jsonl": v}}
              for n, v in (("245", 0.60), ("490", 1.10))}     # val 也故意反过来
    rc, txt, best = run_rank(cands2, table2, {"245": pm(a_pass), "490": pm(b_pass)})
    check("③ 配对有差 → rc=0", rc == 0, f"rc={rc}")
    check("③ 选配对翻正的那只（490，尽管 val 更差、步数更晚）", best == "490", f"best={best}")
    check("③ 打印 wins/losses", "配对翻正数" in txt, "")

    # ④ 缺 re_detail → 不崩 + 点明配对数为 0
    cands3 = {"245": os.path.join(root, "ck245c"), "490": os.path.join(root, "ck490c")}
    table3 = {n: {"re_pass": 40, "re_total": 60, "kitty_pass": 20, "kitty_total": 23}
              for n in cands3}
    rc, txt, best = run_rank(cands3, table3, {})
    check("④ 缺 re_detail → rc=0（不崩）", rc == 0, f"rc={rc}")
    check("④ 报告点明配对数为 0", "配对数为 0" in txt, "")
    check("④ 仍给出推荐（按 re 通过数 → 步数）", best == "245", f"best={best}")

    # ⑤ 反向证明：老键（含 val）在同输入下会选 735
    old_key = sorted([("245", 40, 1.20), ("735", 40, 0.50), ("final", 40, 0.90)],
                     key=lambda x: (-x[1], x[2]))
    check("⑤ 反向：老 val_loss 键会选 735（缺陷成因）", old_key[0][0] == "735",
          f"old-best={old_key[0][0]}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nPASS: 次级键是配对翻正数、val_loss 已出排序键、打平按步数收尾"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
