#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_w3.py —— W3 露骨正文的**生成流水线**（正文由 abliterated base 产出，脚本只负责取样与筛选）

流程
----
  scenes.jsonl ──► 每场景 2 候选 ──► judge_structural 四判据 ──► 全真者入库
                                                     └─ 否则落 rejected（带原因）

安全阀（--probe 5 时强制）
--------------------------
  前 5 条若 ≥2 条被判 refuse（拒答/铺垫正则命中）→ 立即停，rc=3，打印"必须先做权重再投影"。
  这是为了在数据生成阶段就发现"训练把拒答拽回来了"，比训完评测早 6 小时。

用法
----
  # 安全阀（先跑这个）
  python gen_w3.py --scenes data/intent3/w3-scenes.jsonl --base http://127.0.0.1:1234 \
      --model huihui --probe 5 --out data/intent3/w3-probe.jsonl

  # 全量
  python gen_w3.py --scenes ... --base ... --model ... --n 150 \
      --out data/intent3/w3-sft.jsonl --rej data/intent3/w3-rejected.jsonl

判据
----
  · 端点不可达 / 全部候选失败 → rc=2 FATAL（不许静默产出 0 条）
  · 入库条数 < 目标的 80% → rc=4（提示降低门槛或换温度，但不自动降门槛）
  · 每条入库带 judge 结果与 2 候选的择优理由
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import judge_structural as JS  # noqa: E402

REFUSE = [
    "抱歉", "我不能", "无法协助", "不能提供", "作为 AI", "作为AI", "不适合",
    "请注意", "需要说明", "建议咨询", "我不能写", "无法生成", "换个话题",
    "保持尊重", "健康的关系", "如果你愿意，我们可以",
]


def post(base, model, messages, max_tokens=700, temp=0.85, timeout=180):
    body = json.dumps({
        "model": model, "messages": messages, "max_tokens": max_tokens,
        "temperature": temp, "top_p": 0.95,
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    txt = msg.get("content")
    if isinstance(txt, list):
        txt = "".join(p.get("text", "") for p in txt if isinstance(p, dict))
    return (txt or "").strip(), ch.get("finish_reason")


def is_refuse(txt):
    return [w for w in REFUSE if w in txt[:200]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--n", type=int, default=0, help="0=全部场景")
    ap.add_argument("--probe", type=int, default=0, help=">0 时只跑前 N 条并做安全阀")
    ap.add_argument("--cands", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=700)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rej")
    ap.add_argument("--wordlist")
    a = ap.parse_args()

    if a.wordlist:
        JS.set_wordlist(a.wordlist)

    scenes = [json.loads(l) for l in open(a.scenes, encoding="utf-8") if l.strip()]
    if not scenes:
        raise SystemExit("[FATAL] 场景文件 0 行：%s" % a.scenes)
    todo = scenes[:a.probe] if a.probe else (scenes[:a.n] if a.n else scenes)
    print("[gen] 场景 %d 条，本次跑 %d 条，每场景 %d 候选" % (len(scenes), len(todo), a.cands))

    accepted, rejected, refuse_n, fail_n = [], [], 0, 0
    t0 = time.time()

    for i, sc in enumerate(todo, 1):
        cands = []
        for k in range(a.cands):
            try:
                txt, fin = post(a.base, a.model, [{"role": "user", "content": sc["prompt"]}],
                                max_tokens=a.max_tokens, temp=0.85)
            except urllib.error.URLError as e:
                print("[FATAL] 端点不可达：%s（%s）" % (a.base, e))
                return 2
            except Exception as e:
                fail_n += 1
                print("  [warn] %s 候选%d 失败：%s" % (sc["id"], k + 1, e))
                continue
            rf = is_refuse(txt)
            j = JS.judge(txt)
            c = {"text": txt, "finish": fin, "refuse": rf, "judge": j, "chars": len(txt)}
            if rf:
                refuse_n += 1
            cands.append(c)

        if not cands:
            rejected.append({"id": sc["id"], "why": "all_candidates_failed"})
            continue

        # 择优：四判据全真 > score 高 > 长度落在区间 > 不含拒答
        lo, hi = sc.get("len") or [200, 700]

        def rank(c):
            in_len = 1 if lo <= c["chars"] <= hi * 1.3 else 0
            return (0 if c["refuse"] else 1, c["judge"]["score"], in_len, -abs(c["chars"] - (lo + hi) // 2))

        best = sorted(cands, key=rank)[-1]
        hop = {"id": sc["id"], "prompt": sc["prompt"], "response": best["text"],
               "judge": best["judge"], "chars": best["chars"], "finish": best["finish"],
               "cand_n": len(cands), "pov": sc.get("pov"),
               "intensity": sc.get("intensity"), "boundary": sc.get("boundary")}
        if best["refuse"]:
            rejected.append(hop | {"why": "refuse:%s" % best["refuse"][:2]})
        elif best["judge"]["score"] < 1.0:
            rejected.append(hop | {"why": "judge:%s" % best["judge"]["reasons"][:2]})
        else:
            accepted.append(hop)
        print("  [%3d/%3d] %s score=%.2f chars=%3d %s"
              % (i, len(todo), sc["id"], best["judge"]["score"], best["chars"],
                 "ACCEPT" if accepted and accepted[-1]["id"] == sc["id"] else "reject"), flush=True)

    # 自检
    if refuse_n and a.probe and refuse_n >= 2:
        print("\n[SAFETY-VALVE] 试生成 %d 条中 %d 条出现拒答/铺垫 → base 的 abliteration 已被拉回。"
              % (len(todo), refuse_n))
        print("[SAFETY-VALVE] 结论：数据侧无法修复，必须先做权重再投影（强度 0.3-0.5）。rc=3")
        return 3
    if not accepted:
        print("[FATAL] 0 条入库（refuse=%d fail=%d）—— 这不是 0 分，是没产成" % (refuse_n, fail_n))
        return 2

    def dump(path, rows):
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        n = sum(1 for l in open(path, encoding="utf-8") if l.strip())
        if n != len(rows):
            raise SystemExit("[FATAL] %s 回读 %d != %d" % (path, n, len(rows)))
        print("[ok] %s  %d 行" % (path, n))

    dump(a.out, accepted)
    if a.rej:
        dump(a.rej, rejected)

    print("\n[sum] 跑 %d 条｜入库 %d｜拒收 %d｜候选失败 %d｜拒答命中 %d｜%.1f s/条"
          % (len(todo), len(accepted), len(rejected), fail_n, refuse_n,
             (time.time() - t0) / max(1, len(todo))))
    if a.n and len(accepted) < 0.8 * len(todo):
        print("[warn] 入库率 %.0f%% < 80%%：可调 --max-tokens 或换温度重跑，不要手动降判据"
              % (100.0 * len(accepted) / len(todo)))
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
