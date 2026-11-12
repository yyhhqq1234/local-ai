# -*- coding: utf-8 -*-
"""一次性：把 eval_cases_2a.py 的 must_mention 全部改成「ask 里真实出现的标识符」

原因：手写的 must_mention 混进了专业术语（eager_load / blacklist / Xmx 等），
     这些词在 ask 里没出现，模型无从得知 → 自检 85 项不合规。
     must_mention 的正确定义是「ask 里给出的、回答必须抓住的技术对象」。
"""
import ast
import io
import re

P = "eval_cases_2a.py"
src = io.open(P, encoding="utf-8").read()

# 1) 取出 CASES（dict() 调用不是字面量，literal_eval 不适用 → 去尾自检段后 exec）
src_body = src.split("# 自检：id 唯一")[0]
_ns = {}
exec(compile(src_body, P, "exec"), _ns)
cases = _ns["CASES"]
assert cases, "解析不到 CASES"

STOP = {
    "the", "and", "for", "but", "not", "with", "this", "that", "from", "have",
    "should", "when", "only", "into", "then", "than", "its", "you", "can",
    "过程中", "一下", "什么", "怎么", "说明", "给出", "并给", "找出", "改成",
}


def extract_must(ask):
    """从 ask 提取技术对象：反引号内容优先，其次大写/带符号标识符"""
    out = []
    # ① 反引号内（最可靠：明确的技术对象）
    for x in re.findall(r"`([^`]+)`", ask):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    # ② 大写标识符 / 带下划线点号的英文名（错误码、枚举、文件名）
    for x in re.findall(r"\b([A-Za-z_][A-Za-z0-9_.\-]{2,})\b", ask):
        if x.lower() in STOP or x in out:
            continue
        if re.search(r"[A-Z_\.\-]", x):      # 含大写/下划线/点/连字符
            out.append(x)
    return out[:6]


changed = 0
for c in cases:
    new = extract_must(c["ask"])
    if new != c["must_mention"]:
        changed += 1
    c["must_mention"] = new

# 2) 重新生成源码
head = src[: src.index("CASES = [")]
tail_after = src[src.rindex("]\n"):]      # 自检段
# 去掉旧自检段，重写
tail_after = tail_after[tail_after.index("# 自检"):] if "# 自检" in tail_after else ""

lines = [head.rstrip() + "\n\nCASES = [\n"]
cur_lv = None
for c in cases:
    if c["level"] != cur_lv:
        cur_lv = c["level"]
        label = {"L1": "L1 直白：单点 bug，位置已给出",
                 "L2": "L2 间接：只说现象，要先定位",
                 "L3": "L3 抽象：需要判断取舍"}.get(cur_lv, cur_lv)
        lines.append("    # ══════════ %s ══════════\n" % label)
    mm = ", ".join(
        '"%s"' % x.replace("\\", "\\\\").replace('"', '\\"')
        for x in c["must_mention"])
    lines.append('    dict(id="%s", level="%s",\n' % (c["id"], c["level"]))
    lines.append('         ask="%s",\n' % c["ask"].replace('"', '\\"'))
    lines.append("         must_mention=[%s],\n" % mm)
    lines.append('         note="%s"),\n' % c["note"])
lines.append("]\n\n")

lines.append('''# 自检：id 唯一 / must_mention 都在 ask 里出现 / 三档齐全
_ids = [c["id"] for c in CASES]
assert len(_ids) == len(set(_ids)), "id 重复"
_lv = {}
for c in CASES:
    _lv[c["level"]] = _lv.get(c["level"], 0) + 1
    assert c["must_mention"], "%s 的 must_mention 为空" % c["id"]
    for m in c["must_mention"]:
        assert m.lower() in c["ask"].lower(), \\
            "%s 的 must_mention %r 没在 ask 里出现" % (c["id"], m)
assert set(_lv) == {"L1", "L2", "L3"}, "三档不全: %s" % _lv
''')

io.open(P, "w", encoding="utf-8").write("".join(lines))
print("[write] %s，must_mention 改动 %d 条" % (P, changed))

# 3) 立刻验证
import importlib.util
spec = importlib.util.spec_from_file_location("ec2a", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
import collections
print("[verify] CASES=%d  level=%s" % (len(m.CASES), dict(collections.Counter(c["level"] for c in m.CASES))))
print("[verify] must_mention 总 %d，平均 %.1f/条"
      % (sum(len(c["must_mention"]) for c in m.CASES),
         sum(len(c["must_mention"]) for c in m.CASES) / len(m.CASES)))
for c in m.CASES[:3]:
    print("  %s  %s" % (c["id"], c["must_mention"]))
print("[self-check] 全部通过")
