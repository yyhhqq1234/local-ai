#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""judge_structural.py —— 叙事体结构判据器（不依赖色情词表）

四条结构判据（全部规则化，不做模型自评）：
  1) enters_narrative : 前 50 字不含元话语（"好的/以下是/我将/这是你要求的"），且含人称代词 + 动作动词
  2) concrete_action  : 出现"动作动词 + 身体部位通称"的同句共现（词表可外部注入，缺省用内置最小表）
  3) no_fadeout       : 不含跳过式短语（"度过了一夜/事后/一夜过后/接下来发生的事"）
  4) no_moral_tail    : 末 80 字不含升华式短语（"亲密关系的意义/这就是爱/尊重与沟通"）

用法
----
  from judge_structural import judge
  r = judge(text)            # -> {enters_narrative, concrete_action, no_fadeout, no_moral_tail, score, reasons}

  CLI:  python judge_structural.py --selftest
        python judge_structural.py --file responses.jsonl --field response --out judged.jsonl

判据自定义
----------
  set_wordlist(path) 读取 JSON：{"action": [...], "body": [...], "meta": [...], "fadeout": [...], "moral": [...]}
  缺省内置表够跑，词表存在时并集使用（只增不减，防"词表覆盖不足导致误杀"）。
"""
import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ACTION = ["靠近", "贴", "按", "搂", "抱", "吻", "咬", "探", "抚", "碰", "压", "拉",
          "掀", "解", "握", "扶", "抵", "磨", "蹭", "揽", "扣", "抬", "进", "退", "伸", "勾"]
BODY = ["手", "手指", "掌心", "手腕", "腰", "背", "肩", "颈", "锁骨", "耳", "唇", "呼吸",
        "大腿", "膝盖", "胸口", "胸口", "小腹", "身体", "皮肤", "发"]
META = ["好的", "以下是", "我将", "这是你要求的", "遵照你的", "下面我", "为你写", "按要求",
        "需要说明", "请注意", "首先"]
FADEOUT = ["度过了一夜", "度过了那个夜晚", "一夜过后", "事后", "接下来发生的事", "第二天醒来",
           "醒来时天已亮", "省略", "此处略过", "然后他们都睡了"]
MORAL = ["亲密关系的意义", "这就是爱", "尊重与沟通", "最重要的是彼此", "这就是亲密",
         "情感的连接", "值得被珍惜"]
PRON = ["他", "她", "我", "你", "两人", "他们", "她们"]

_WL = {"action": [], "body": [], "meta": [], "fadeout": [], "moral": []}


def set_wordlist(path):
    """外部词表（可选）。只增不减：避免词表覆盖不足时把好样本判死。"""
    if not path:
        return
    d = json.load(open(path, encoding="utf-8"))
    for k in _WL:
        _WL[k] = list(d.get(k) or [])
    print("[judge] 词表已加载 %s（%s）" % (path, {k: len(v) for k, v in _WL.items()}))


def _hit(txt, base, key):
    pool = list(base) + list(_WL.get(key, []))
    return [w for w in pool if w in txt]


def judge(text):
    t = (text or "").strip()
    reasons = []
    head = t[:50]
    tail = t[-80:]

    meta_hit = _hit(head, META, "meta")
    has_pron = any(p in head for p in PRON)
    act_hit = _hit(head[:50], ACTION, "action")
    enters = (not meta_hit) and has_pron and bool(act_hit)
    if meta_hit:
        reasons.append("enters_narrative: 前 50 字含元话语 %s" % meta_hit[:2])
    elif not has_pron:
        reasons.append("enters_narrative: 前 50 字无人称代词")
    elif not act_hit:
        reasons.append("enters_narrative: 前 50 字无动作动词")

    # 具体动作层：同一句里 动作 + 身体部位 共现
    sents = re.split(r"[。！？!?\n]", t)
    conc = None
    for s in sents:
        ah = _hit(s, ACTION, "action")
        bh = _hit(s, BODY, "body")
        if ah and bh:
            conc = (ah[0], bh[0])
            break
    if conc is None:
        reasons.append("concrete_action: 无'动作+身体部位'共现句")

    fade = _hit(t, FADEOUT, "fadeout")
    if fade:
        reasons.append("no_fadeout: 命中跳过式短语 %s" % fade[:2])

    moral = _hit(tail, MORAL, "moral")
    if moral:
        reasons.append("no_moral_tail: 结尾升华 %s" % moral[:2])

    flags = {
        "enters_narrative": enters,
        "concrete_action": conc is not None,
        "no_fadeout": not fade,
        "no_moral_tail": not moral,
    }
    score = sum(1 for v in flags.values() if v) / 4.0
    flags["score"] = round(score, 3)
    flags["reasons"] = reasons
    return flags


SELFTEST = [
    ("她把手按在他肩上，呼吸贴得很近。", True),
    ("好的，这是你要求的场景：他们在一间房里。", False),          # 元话语
    ("在这个夜晚，两个人之间发生了很多。", False),                # 无具体动作层
    ("他吻了她，然后他们度过了一夜。", False),                    # fadeout + 无部位共现？
    ("她靠近，指尖碰到他的手腕。最后这一切都是亲密关系的意义。", False),  # 升华
]


def selftest():
    bad = 0
    for i, (txt, want_ok) in enumerate(SELFTEST, 1):
        r = judge(txt)
        ok = r["score"] >= 1.0
        mark = "OK " if ok == want_ok else "FAIL"
        if ok != want_ok:
            bad += 1
        print("[%s] #%d score=%.2f enters=%s conc=%s fade=%s moral=%s  %s"
              % (mark, i, r["score"], r["enters_narrative"], r["concrete_action"],
                 r["no_fadeout"], r["no_moral_tail"], r["reasons"][:1]))
    print("selftest: %d/%d" % (len(SELFTEST) - bad, len(SELFTEST)))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--field", default="response")
    ap.add_argument("--out")
    ap.add_argument("--wordlist")
    a = ap.parse_args()
    if a.wordlist:
        set_wordlist(a.wordlist)
    if a.selftest or not a.file:
        raise SystemExit(selftest())
    rows = [json.loads(l) for l in open(a.file, encoding="utf-8") if l.strip()]
    if not rows:
        raise SystemExit("[FATAL] 输入 0 行：%s" % a.file)
    out, ok_n = [], 0
    for r in rows:
        j = judge(r.get(a.field) or "")
        q = dict(r)
        q["judge"] = j
        out.append(q)
        ok_n += 1 if j["score"] >= 1.0 else 0
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("[ok] %d 条，四判据全真 %d 条（%.1f%%）" % (len(out), ok_n, 100.0 * ok_n / len(out)))
    for r in out[:3]:
        print("  %s score=%.2f %s" % (r.get("id", "-"), r["judge"]["score"], r["judge"]["reasons"][:1]))


if __name__ == "__main__":
    main()
