# -*- coding: utf-8 -*-
"""05 汇总 stats.json（report.md 里的数字全部来自这里，避免手抄）。"""
import collections
import json
import os

from common import OUT_DIR, WORK, branch_of, msg_pair, read_jsonl, load_lexicon_terms


def main():
    nsfw_st = json.load(open(os.path.join(WORK, "nsfw-run.json"), encoding="utf-8"))
    dsh_st = json.load(open(os.path.join(WORK, "dsh-run.json"), encoding="utf-8"))
    ver = json.load(open(os.path.join(WORK, "verify.json"), encoding="utf-8"))
    prof = json.load(open(os.path.join(WORK, "00-profile.json"), encoding="utf-8"))

    rows = read_jsonl(os.path.join(OUT_DIR, "nsfw-clean.jsonl"))
    lowq = read_jsonl(os.path.join(OUT_DIR, "nsfw-lowquality.jsonl"))
    paired = read_jsonl(os.path.join(OUT_DIR, "nsfw-clean-paired.jsonl"))
    lex = load_lexicon_terms()

    def expl(t):
        return len({w for w in lex if w in t}) >= 2

    br = collections.Counter(branch_of(r) for r in rows)
    ex = collections.Counter(branch_of(r) for r in rows if expl(r["messages"][-1]["content"]))
    L = collections.defaultdict(list)
    for r in rows:
        L[branch_of(r)].append(len(r["messages"][-1]["content"]))
    lens = {k: {"p50": sorted(v)[len(v) // 2], "p95": sorted(v)[int(len(v) * 0.95)],
                "n": len(v)} for k, v in L.items()}
    total_chars = sum(len(r["messages"][-1]["content"]) for r in rows)

    def pct(n, d):
        return round(100.0 * n / d, 2) if d else 0.0

    stats = {
        "generated_at": "2026-11-21",
        "policy_correction": {
            "what": "萝莉 移出未成年 HARD 词表（外观描述词）；仅在同条出现年龄/学段线索时拦截",
            "old_rule_deleted": nsfw_st["loli_correction"]["present_total"],
            "old_rule_deleted_note": "旧口径下含「萝莉」的记录一律删（present_total）",
            "only_loli_would_die": nsfw_st["loli_correction"]["old_would_drop"],
            "gated_still_deleted": nsfw_st["loli_correction"]["gated_metrics"],
            "restored_after_fix": nsfw_st["loli_correction"]["restored"],
            "restored_note": "仅因「萝莉」判死、修正后被保留（主集+low_quality+成对视图内）",
        },
        "nsfw": {
            "input": nsfw_st["input"],
            "candidates": nsfw_st["input"]["candidates"],
            "drops": nsfw_st["drops"],
            "drops_by_branch": nsfw_st["drop_by_branch"],
            "minor_reason": nsfw_st["minor_reason"],
            "soft_word": nsfw_st["soft_word"],
            "refusal_reason": nsfw_st["refusal_reason"],
            "template_reason": nsfw_st["template_reason"],
            "template_rewritten": nsfw_st["template_rewritten"],
            "final": nsfw_st["final"],
            "final_branch": dict(br),
            "final_branch_explicit": dict(ex),
            "explicit_ratio_pct": pct(sum(ex.values()), len(rows)),
            "explicit_ratio_by_branch_pct": {k: pct(ex[k], br[k]) for k in br},
            "length_by_branch": lens,
            "assistant_len_all": nsfw_st["assistant_len"],
            "user_len": nsfw_st["user_len"],
            "total_assistant_chars": total_chars,
            "avg_assistant_chars": total_chars // max(1, len(rows)),
            "low_quality_rows": len(lowq),
            "paired_users": nsfw_st["paired_users"],
            "paired_rows": len(paired),
            "retention_pct": pct(nsfw_st["final"], nsfw_st["input"]["candidates"]),
        },
        "dsh": {
            "input": dsh_st["input"],
            "after_gate": dsh_st["after_gate"],
            "final": dsh_st["final"],
            "drops": dsh_st["drops"],
            "repairs": dsh_st["repairs"],
            "dedup": dsh_st["dedup"],
            "template_prefix_rows": dsh_st["template_prefix_rows"],
            "near_dup_threshold": dsh_st["near_dup_threshold"],
            "tool_calls_final": dsh_st["tool_calls_final"],
            "retention_pct": pct(dsh_st["final"], dsh_st["input"]),
            "notes": {
                "rebuild_manifest_bytes": dsh_st["rebuild_manifest_bytes"],
                "manifest_tools": dsh_st["manifest_tools"],
                "action_as_key_defect": "旧集把动作名当参数键（如 {\"status\":\"<值>\"}），已按真实 schema 重写",
            },
        },
        "verify": ver,
        "profile_before": prof,
    }
    out = os.path.join(WORK, "stats.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: stats[k] if k != "profile_before" else "…" for k in stats},
                     ensure_ascii=False, indent=1)[:2600])
    print("\nwrote", out)


if __name__ == "__main__":
    main()
