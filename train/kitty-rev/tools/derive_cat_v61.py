# -*- coding: utf-8 -*-
"""给 v61-mix 派生 meta.cat（check_sft 硬要求，缺则 sys.exit(3)）

规则复现自 V6 的派生（chain-op 在远端做的，本地没落盘）：
  kind=trajectory                    → real-trajectory
  kind=direct & tool=kitty_ce        → op-syntax
  kind=direct 其它                    → tool-route
  非 trajectory/direct/text 的 kind    → op-syntax（即 ops-legit 10 条）
  kind=text 且正文含工具/OP 线索        → kb-tool
  kind=text 其余                      → kb-re
  本次新增 src=v61-nonkitty 的 54 条   → kb-re（教学目标是"不调工具"，归非工具知识）

输入  data/intent3/v6-mix/v61-mix.dictargs.jsonl
输出  data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl
"""
import json, re, hashlib
from collections import Counter

SRC = "data/intent3/v6-mix/v61-mix.dictargs.jsonl"
DST = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"

# 工具/OP 线索：kitty_ 工具名、A 通道 OP（全大写 + 下划线/竖线）、LUA| 逃生口
OP_HINT = re.compile(r"kitty_[a-z]|[A-Z]{2,}_[A-Z_]{2,}|LUA\||S_NEW|P_BACK|P_WALK|MODENUM|KM_ATTACH")


def derive(r):
    m = r.get("meta") or {}
    kind = m.get("kind")
    # 本次新增的非 kitty 样本，直接定 kb-re
    if m.get("src") == "v61-nonkitty":
        return "kb-re"
    if kind == "trajectory":
        return "real-trajectory"
    if kind == "direct":
        return "op-syntax" if m.get("tool") == "kitty_ce" else "tool-route"
    if kind == "text":
        body = " ".join((x.get("content") or "") for x in r.get("messages") or [])
        return "kb-tool" if OP_HINT.search(body) else "kb-re"
    # ops-legit 等其余 kind
    return "op-syntax"


rows = []
for line in open(SRC, encoding="utf-8"):
    if not line.strip():
        continue
    r = json.loads(line)
    r.setdefault("meta", {})["cat"] = derive(r)
    rows.append(r)

with open(DST, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

cats = Counter((r["meta"] or {}).get("cat") for r in rows)
kinds = Counter((r["meta"] or {}).get("kind") for r in rows)
print(f"写出 {len(rows)} 条 → {DST}")
print("md5", hashlib.md5(open(DST, "rb").read()).hexdigest())
print("cat  分布:", dict(cats))
print("kind 分布:", dict(kinds))
none_cat = sum(1 for r in rows if not (r.get("meta") or {}).get("cat"))
print(f"meta.cat 为空: {none_cat}")
assert none_cat == 0
assert len(rows) == 1243, f"行数不对: {len(rows)}"
# 与 V6 的派生分布做合理性比对（V6 1175 条：traj 192 / tool-route 423 / op-syntax 10+ / kb-tool 297 / kb-re 253 + text 550）
print("\n与 V6 派生分布对照（V6 是 1175 条口径，本次 1243 条含 extra-14 与 nonkitty-54）:")
print("  real-trajectory 期望 ~196 得到", cats.get("real-trajectory"))
print("  tool-route      期望 ~423 得到", cats.get("tool-route"))
print("  kb-tool         期望 ~297 得到", cats.get("kb-tool"))
print("  kb-re           期望 ~253+54+? 得到", cats.get("kb-re"))
print("  op-syntax       期望 ~10+kitty_ce 得到", cats.get("op-syntax"))
print("\n✅ cat 补齐完成")
