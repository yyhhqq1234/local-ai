"""坍缩探针：只跑通用题（general 16 条 + trap 9 条），看模型是否在输出门控模板

背景（2026-11-05）：
  v6-c12 评测发现 val-gen01（「概括《百年孤独》叙事结构」）输出的是
  「先给你能写的部分，剩下的等标记…场景：通用室内」——与 prompt 完全无关的门控模板。
  val-gen06（翻译会议时间）同样。说明 LoRA 训过多后 adapter 接管了输出分布，
  base 的通用能力被挤压。

判据（关键）：
  general 组的 prompt 全是普通问题（概括小说 / 翻译 / 街景描写 / 代码…），
  正常模型应 0% 输出拒答模板。**模板化率就是坍缩程度的直接度量。**

用法：
  python _work/probe_collapse.py --adapter "" --out out/probe-base.json          # 基座对照
  python _work/probe_collapse.py --adapter train/lines/9b-oxcoder/out/v5-s1/final --out out/probe-s1.json
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "train", "lines", "_shared", "scripts")
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from nsfw_gate_eval import (REFUSAL_CUES, judge_nsfw, judge_refusal,  # noqa: E402
                            load_dataset_probes, load_terms)
from eval_2a_code import gen, load_model  # noqa: E402

VAL = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "eval", "val", "nsfw-gate.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="", help="留空 = 纯基座（坍缩基准线）")
    ap.add_argument("--val", default=VAL)
    ap.add_argument("--kinds", default="general,trap")
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    kinds = tuple(x.strip() for x in a.kinds.split(",") if x.strip())
    probes = [p for p in load_dataset_probes(a.val) if p.get("kind") in kinds]
    terms = load_terms(strict=True)

    tag = os.path.basename(os.path.dirname(a.adapter.rstrip("/\\"))) or "base"
    if not a.adapter:
        tag = "base"
    print(f"[probe] {tag} · adapter={a.adapter or '(none)'} · 探针 {len(probes)} 条 ({','.join(kinds)}) · max_new={a.max_new}")

    model, tok = load_model(a.adapter or None)

    rows = []
    tpl = 0
    for i, p in enumerate(probes, 1):
        system = p.get("system") or ""
        out = gen(model, tok, system, p["prompt"], max_new=a.max_new)
        refusal = bool(judge_refusal(out))
        nsfw, _, cnt, _ = judge_nsfw(out, terms)
        if refusal:
            tpl += 1
        rows.append({"id": p["id"], "kind": p["kind"], "prompt": p["prompt"][:120],
                     "output": out[:400], "refusal": refusal, "nsfw": nsfw, "hits": cnt})
        flag = "TPL " if refusal else "ok  "
        print(f"[{i:2d}/{len(probes)}] {flag} {p['kind']:<8} {p['id']:<14} {out[:60].replace(chr(10),' ')}")

    n = len(rows)
    gen_rows = [r for r in rows if r["kind"] == "general"]
    trap_rows = [r for r in rows if r["kind"] == "trap"]
    tpl_gen = sum(1 for r in gen_rows if r["refusal"])
    tpl_trap = sum(1 for r in trap_rows if r["refusal"])

    print()
    print("=" * 70)
    print(f"adapter        : {a.adapter or '(none / base)'}")
    print(f"通用题模板化率 : {tpl_gen}/{len(gen_rows)} = {tpl_gen/max(1,len(gen_rows)):.4f}   ← 正常模型应 0")
    print(f"技术题模板化率 : {tpl_trap}/{len(trap_rows)} = {tpl_trap/max(1,len(trap_rows)):.4f}")
    print(f"合计模板化率   : {tpl}/{n} = {tpl/max(1,n):.4f}")
    print("=" * 70)

    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump({"adapter": a.adapter or "(base)", "tag": tag, "n": n,
                   "tpl_gen": tpl_gen, "n_gen": len(gen_rows),
                   "tpl_trap": tpl_trap, "n_trap": len(trap_rows),
                   "tpl_total": tpl, "rows": rows},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[OK] → {a.out}")


if __name__ == "__main__":
    main()
