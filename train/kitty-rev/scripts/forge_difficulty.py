# -*- coding: utf-8 -*-
"""forge 难度分层（旁路产出，不改 JSONL —— 保住 deliver-prep 已记录的 sha16）

为什么做旁路而不是 meta.difficulty：
  data/forge/*.jsonl 已经进过 make_subsets 并被记录 sha16=b50113b880fdec35 / 1f4c02245ded7fcc，
  训练前再改 JSONL 会让这两条哈希失效，强制下游重跑 act-cache 步骤。
  难度是「可选的采样权重」，不该为此让主链路返工。
  → 落成 data/forge/forge-difficulty.json，按 user-hash 关联；采样侧想用就 join，不想用就当不存在。

评分是结构化的三因子（可复算、可审计），不是主观打标：
  F1 跨视图/跨域验证  —— 出现内核路由 / 物理读 / PTE 直写 / 双视图门禁
  F2 多步编排           —— 决策链段数 ≥4，或绕路往返数 ≥4
  F3 含失败-纠正记录     —— 出现 ERR|/失败/不对/改走 等纠错标记
  score 0-1 = easy · 2 = medium · 3 = hard
"""
import json
import os
import re
import collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORGE = os.path.join(BASE, "data", "forge")
OUT = os.path.join(FORGE, "forge-difficulty.json")

FILES = ["re-pe-structure.jsonl", "re-op-semantics.jsonl",
         "re-decision-chain.jsonl", "re-detour-trajectory.jsonl"]

F1 = re.compile(r"kitty_km|KM_R|KM_W|KM_PA|KM_PR|kitty_dualview|kitty_wpb|kitty_acescan|"
                r"物理读|PTE")
# 多步编排：不锚定某一种编号格式（第一版只认 [1]/1) 导致 kb-re 全被误判 easy）。
# 改为「结构化步骤标记的种类数」——三种文风都能覆盖：
#   编号步 [1] / 1) / 1、   · 流程骨架 triage/static/dynamic   · 判据/退出/收敛
F2_NUM = re.compile(r"^(?:\[[1-9]\]|[1-9]\)|[1-9]、)", re.M)
F2_DETOUR = re.compile(r"往返\s*[1-9]")
F2_MARKERS = ["triage", "static", "dynamic", "判据", "退出", "收敛", "回读", "验证", "复验"]
F3 = re.compile(r"ERR\||失败|不对|改走|回滚|纠正|推翻|作废|绕")


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def user_hash(msgs):
    import hashlib
    us = [norm(m["content"]) for m in msgs if m["role"] == "user"]
    return hashlib.sha256("\u0002".join(us).encode("utf-8")).hexdigest()


def score(asst):
    f1 = 1 if F1.search(asst) else 0
    n_num = len(F2_NUM.findall(asst))
    n_detour = len(set(F2_DETOUR.findall(asst)))
    n_mark = sum(1 for m in F2_MARKERS if m in asst)
    # 多步：编号步 ≥3，或绕路往返 ≥4，或结构化标记种类 ≥3
    f2 = 1 if (n_num >= 3 or n_detour >= 4 or n_mark >= 3) else 0
    f3 = 1 if F3.search(asst) else 0
    s = f1 + f2 + f3
    return s, ("easy" if s <= 1 else "medium" if s == 2 else "hard"), {
        "F1_cross_view": f1, "F2_multi_step": f2, "F3_correction": f3,
        "numbered_steps": n_num, "detour_rounds": n_detour, "marker_kinds": n_mark}


def main():
    rows = {}
    per_cat = collections.defaultdict(collections.Counter)
    for fn in FILES:
        p = os.path.join(FORGE, fn)
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                asst = "".join(m["content"] for m in r["messages"] if m["role"] == "assistant")
                s, band, factors = score(asst)
                uh = user_hash(r["messages"])
                cat = (r["meta"] or {}).get("cat")
                rows[uh] = {"cat": cat, "score": s, "band": band, "factors": factors,
                            "asst_chars": len(asst)}
                per_cat[cat][band] += 1

    out = {
        "generated_by": "scripts/forge_difficulty.py",
        "applies_to": [f"data/forge/{f}" for f in FILES],
        "join_key": "sha256(normalized user content)  —— 与 make_subsets.content_hash 不同键，仅作采样侧关联",
        "why_sidecar": "不改 JSONL：forge-subset 的 sha16 已被下游记录，改正文会迫使 act-cache 重跑",
        "rule": {
            "F1_cross_view": "命中 kitty_km/KM_*/kitty_dualview/kitty_wpb/物理读/PTE → +1",
            "F2_multi_step": "编号步数 ≥3（[1]/1)/1、 三种写法都算），或绕路「往返N」个数 ≥4，"
                             "或结构化标记种类 ≥3（triage/static/dynamic/判据/退出/收敛/回读/验证/复验）→ +1",
            "F3_correction": "命中 ERR|/失败/不对/改走/回滚/纠正/推翻/作废/绕 → +1",
            "band": "score 0-1=easy · 2=medium · 3=hard",
            "known_bias": "分层结果与类别高度相关（kb-re/op-syntax 几乎全 easy，"
                          "real-trajectory 集中 medium+hard）—— 因为三因子里的 F1/F3 "
                          "本质是「是否含跨视图取证 / 是否含失败纠正」，而那正是绕路类的定义特征。"
                          "因此本分层实质上接近「类别标签的另一种写法」。",
        },
        "recommendation": {
            "for_training_sampling": "不建议 —— 按 hard 加权等于变相提高 real-trajectory 类权重，"
                                     "而类权重已由 --data-mix 的 forge:4 统一给出；再加一层会过拟合绕路文风",
            "for_eval": "建议 —— 用 band 在 val 集上分组看 loss/准确率，"
                        "能回答「模型是不是只学会了一轮成型、学不会纠错」这个真问题",
            "cost": "0（旁路文件，不改 JSONL、不改 sha16、不需要改 sampler）",
        },
        "counts": {c: dict(sorted(v.items())) for c, v in sorted(per_cat.items())},
        "total": len(rows),
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {OUT}  rows={len(rows)}")
    for c, v in sorted(per_cat.items()):
        tot = sum(v.values())
        print(f"  {c:16s} " + "  ".join(f"{b}={v[b]}({v[b]/tot*100:.0f}%)"
                                        for b in ("easy", "medium", "hard")))


if __name__ == "__main__":
    main()
