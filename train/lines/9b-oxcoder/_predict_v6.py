#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
深度分析：用「训练覆盖率」预测训练结果

方法（不是拍脑袋）：
  对 40 条 RE 评测用例，计算每条 case 的 ask 与训练集里「含 expect 工具」样本的最大相似度，
  再把相似度与实际结果（v4 / v5 已知）做关联 —— 验证相似度是否真能预测对错。
  若能预测，就用同一把尺子预测 v6。

同理对 85 条门控用例做覆盖度分析。

输出：train/logs/predict-2b-v6.md + 控制台
"""
import io, json, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_shared", "scripts"))
from eval_cases_re import CASES          # noqa: E402

TRAIN_V6 = os.path.join(HERE, "data", "_legacy", "mix-z-re-v6-train.jsonl")
EVAL_V5 = os.path.join(HERE, "out", "eval-re-zbv5.json")
GATE_TRAIN = os.path.join(HERE, "data", "nsfw-gated", "train-2b-gated-v4-train.jsonl")
GATE_VAL = os.path.join(HERE, "data", "eval", "val", "nsfw-gate.jsonl")
OUT = os.path.join(HERE, "..", "..", "logs", "predict-2b-v6.md")


def grams(s, k=2):
    s = re.sub(r"[\s\u3000]+", "", s or "")
    return set(s[i:i + k] for i in range(max(0, len(s) - k + 1)))


def jac(a, b):
    A, B = grams(a), grams(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def load_jsonl(p):
    out = []
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def main():
    train = load_jsonl(TRAIN_V6)
    print(f"[IN] v6 训练集 {len(train)} 行")

    # 建立「工具 → 样本 user 列表」
    tool_users = collections.defaultdict(list)
    TOOL_RE = re.compile(r"\bkitty_[a-z_]+")
    for r in train:
        a = r["messages"][-1]["content"]
        u = r["messages"][0]["content"]
        for t in set(TOOL_RE.findall(a)):
            tool_users[t].append(u)
    print(f"[IN] 覆盖工具 {len(tool_users)} 个")

    # 已知实测结果
    v5 = {}
    if os.path.exists(EVAL_V5):
        d = json.load(io.open(EVAL_V5, encoding="utf-8"))
        for res in d["results"]:
            if res["label"] == "zbv5":
                for c in res["detail"]:
                    v5[c["id"]] = c["got"] == c["expect"] if c.get("expect") else False

    rows = []
    for c in CASES:
        exp = set(c["expect"])
        asks = c["ask"]
        # 该 case 的 expect 工具在训练集里的样本
        cand = []
        for t in exp:
            cand.extend(tool_users.get(t, []))
        sims = sorted((jac(asks, u) for u in cand), reverse=True)
        best = sims[0] if sims else 0.0
        p90 = sims[min(len(sims) - 1, max(0, len(sims) // 10))] if sims else 0.0
        n_cov = len(cand)
        rows.append(dict(id=c["id"], level=c["level"], expect=sorted(exp),
                         n_cov=n_cov, best=round(best, 3), p90=round(p90, 3),
                         v5_ok=v5.get(c["id"]), ask=asks[:70]))

    # ── 验证：相似度能否预测 v5 结果 ──
    known = [r for r in rows if r["v5_ok"] is not None]
    hit = [r for r in known if r["v5_ok"]]
    miss = [r for r in known if not r["v5_ok"]]
    avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else 0
    print("\n" + "=" * 76)
    print("一、验证：训练覆盖率 vs v5 实际结果")
    print("=" * 76)
    print(f"  v5 答对 {len(hit)} 条 · 平均 best_sim = {avg([r['best'] for r in hit])}")
    print(f"  v5 答错 {len(miss)} 条 · 平均 best_sim = {avg([r['best'] for r in miss])}")
    print(f"  区分度（对-错 差）= {round(avg([r['best'] for r in hit]) - avg([r['best'] for r in miss]), 3)}")

    # 分档
    print("\n  按 best_sim 分档看命中率：")
    for lo, hi in [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.01)]:
        band = [r for r in known if lo <= r["best"] < hi]
        if band:
            ok = sum(1 for r in band if r["v5_ok"])
            print(f"    sim [{lo:.2f},{hi:.2f})  n={len(band):2d}  命中 {ok:2d} ({ok/len(band)*100:.0f}%)")

    # ── 未覆盖 / 低覆盖 case（v6 的预测风险点） ──
    print("\n" + "=" * 76)
    print("二、v6 的风险点（训练覆盖不足的 case）")
    print("=" * 76)
    risky = sorted(rows, key=lambda r: (r["best"], r["n_cov"]))[:15]
    print(f"  {'id':<5}{'lvl':<4}{'n_cov':>6}{'best':>7}  {'v5':<6} expect / ask")
    for r in risky:
        v = "✓" if r["v5_ok"] else ("✗" if r["v5_ok"] is False else "?")
        print(f"  {r['id']:<5}{r['level']:<4}{r['n_cov']:>6}{r['best']:>7}  {v:<6} "
              f"{','.join(t.replace('kitty_','') for t in r['expect'])} | {r['ask'][:44]}")

    # ── 预测 v6 ──
    print("\n" + "=" * 76)
    print("三、v6 结果预测")
    print("=" * 76)
    # 用分档命中率做加权预测
    def predict(r):
        if r["v5_ok"]:
            return 1.0 if r["best"] >= 0.10 else 0.85
        # v5 答错的，v6 修了纪律与多步链（对 L3 有帮助）
        base = 0.25 if r["best"] < 0.05 else (0.35 if r["best"] < 0.10 else 0.45)
        if r["level"] == "L3":
            base += 0.15      # v6 的多步链专项
        return min(0.75, base)
    exp_hit = sum(predict(r) for r in rows)
    print(f"  期望命中 ≈ {exp_hit:.1f} / 40  →  acc ≈ {exp_hit/40*100:.1f}%")
    print(f"  分档预测：L1 "
          f"{sum(predict(r) for r in rows if r['level']=='L1'):.1f}/12 · "
          f"L2 {sum(predict(r) for r in rows if r['level']=='L2'):.1f}/12 · "
          f"L3 {sum(predict(r) for r in rows if r['level']=='L3'):.1f}/16")
    print(f"  达标线 36/40（90%）  →  {'预计达标' if exp_hit >= 36 else '预计不达标，差 %.1f 条' % (36-exp_hit)}")

    # ── 门控覆盖分析 ──
    print("\n" + "=" * 76)
    print("四、门控 85 条的训练覆盖")
    print("=" * 76)
    gtrain = load_jsonl(GATE_TRAIN)
    # 按 system 分桶
    def sys_of(r):
        for m in r["messages"]:
            if m["role"] == "system":
                return m["content"][:24]
        return "(none)"
    buckets = collections.Counter(sys_of(r) for r in gtrain)
    print("  训练集 system 分布：")
    for k, v in buckets.most_common():
        print(f"    {v:6d}  {k}")

    gval = load_jsonl(GATE_VAL)
    kinds = collections.Counter(r["meta"].get("kind") for r in gval)
    print("\n  评测集 kind 分布：", dict(kinds))

    # 对 general/trap 类，找训练集里 system=常规 且 assistant 不含拒写模板的样本数
    REFUSAL = re.compile(r"(常规模式生效中|不展开露骨情节|需显式开关|要成人向请开启)")
    normal_ok = sum(1 for r in gtrain
                    if sys_of(r).startswith("模式：常规")
                    and not REFUSAL.search(r["messages"][-1]["content"]))
    normal_ref = sum(1 for r in gtrain
                     if sys_of(r).startswith("模式：常规")
                     and REFUSAL.search(r["messages"][-1]["content"]))
    print(f"\n  system=常规 下：正常回答 {normal_ok} 条 · 拒写 {normal_ref} 条 "
          f"→ 比例 1 : {normal_ref/max(1,normal_ok):.1f}")
    ev_need_normal = kinds.get("gate-general", 0) + kinds.get("gate-trap", 0)
    ev_need_refusal = kinds.get("gate-off", 0)
    print(f"  评测要求：正常答 {ev_need_normal} 条 vs 拒写 {ev_need_refusal} 条 "
          f"→ 比例 1 : {ev_need_refusal/max(1,ev_need_normal):.2f}")
    print(f"\n  比例错配：训练 1:{normal_ref/max(1,normal_ok):.1f} vs 评测 1:{ev_need_refusal/max(1,ev_need_normal):.2f}")
    print(f"  → 训练集把「常规=拒写」的信号放大了约 "
          f"{(normal_ref/max(1,normal_ok))/(ev_need_refusal/max(1,ev_need_normal)):.1f} 倍")

    # 写报告
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("# 深度分析：用当前数据训练的预测结果\n\n")
        f.write(f"## 一、相似度能否预测对错（用 v5 实测校准）\n\n")
        f.write(f"- v5 答对 {len(hit)} 条 平均 best_sim **{avg([r['best'] for r in hit])}**\n")
        f.write(f"- v5 答错 {len(miss)} 条 平均 best_sim **{avg([r['best'] for r in miss])}**\n")
        f.write(f"- 区分度 **{round(avg([r['best'] for r in hit]) - avg([r['best'] for r in miss]), 3)}**\n\n")
        f.write(f"## 二、v6 预测\n\n")
        f.write(f"- 期望命中 **{exp_hit:.1f}/40 = {exp_hit/40*100:.1f}%**\n")
        f.write(f"- 达标线 36/40 → {'预计达标' if exp_hit >= 36 else '预计不达标'}\n\n")
        f.write("## 三、门控比例错配\n\n")
        f.write(f"- 训练 system=常规：正常 {normal_ok} : 拒写 {normal_ref} = 1:{normal_ref/max(1,normal_ok):.1f}\n")
        f.write(f"- 评测要求：正常 {ev_need_normal} : 拒写 {ev_need_refusal} = 1:{ev_need_refusal/max(1,ev_need_normal):.2f}\n")
        f.write(f"- 放大倍数 **{(normal_ref/max(1,normal_ok))/(ev_need_refusal/max(1,ev_need_normal)):.1f}×**\n")
    print(f"\n[OUT] {OUT}")


if __name__ == "__main__":
    main()
