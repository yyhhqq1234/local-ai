# -*- coding: utf-8 -*-
"""生成 train/kitty-rev/data/intent3/willing-forge-MANIFEST.json + length-stats.json，并用 schema 校验。"""
import datetime
import json
import re
import sys

import jsonschema

ROOT = "D:/BaiduNetdiskDownload/Local-AI"
D = ROOT + "/train/kitty-rev/data/intent3"
sys.path.insert(0, D)
import dedup  # noqa: E402

REFUSAL_RE = re.compile(
    r"我不能|我无法|无法协助|不能提供|不便提供|抱歉|很遗憾|作为(一个)?\s*AI|as an AI|"
    r"I can(no|')t|I cannot|请注意|合法用途|仅供学习|建议咨询|咨询专业人士"
)


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def group(name, path, kind, target, fields, ufields, notes):
    rows = load(path)
    stats = dedup.length_stats(rows, fields)
    self_report = dedup.self_check(rows, 0.35, fields, ufields)
    hits = 0
    if kind == "sft":
        hits = sum(len(REFUSAL_RE.findall(dedup.text_of(r, fields))) for r in rows)
    return {
        "name": name,
        "path": path.replace(ROOT + "/", ""),
        "kind": kind,
        "count": len(rows),
        "target_count": target,
        "length_distribution": stats,
        "isolation": {
            "verdict": "PASS" if (self_report["full_hash_duplicates"] == 0
                                  and self_report["user_hash_duplicates"] == 0
                                  and self_report["pairs_over_threshold"] == 0) else "FAIL",
            "jaccard_max": self_report["jaccard_max"],
            "pairs_over_threshold": self_report["pairs_over_threshold"],
            "full_hash_duplicates": self_report["full_hash_duplicates"],
            "user_hash_duplicates": self_report["user_hash_duplicates"],
        },
        "refusal_regex_hits": hits,
        "notes": notes,
    }


def main():
    sft = group("re-sft", D + "/re-sft.jsonl", "sft", 120,
                dedup.TEXT_FIELDS, dedup.USER_FIELDS,
                "逆向技术 SFT：静态分诊/壳指纹/固件/转储/协议/许可互操作/移动-引擎/只读动态/符号差分")
    ev = group("overrefusal-40", D + "/overrefusal-40.jsonl", "eval", 40,
               ["prompt"], ["prompt"],
               "双向过度拒答评测：answer 20（防御/取证/合规/学术）+ refuse 20（真实第三方伤害）")

    against = [
        "train/kitty-rev/data/large-mix-plus/train.jsonl",
        "train/kitty-rev/data/eval_re_extended.jsonl",
        "train/kitty-rev/data/intent2/comply-subset.train.jsonl",
        "train/kitty-rev/data/forge2/train.jsonl",
    ]
    cross_map = {
        "train/kitty-rev/data/large-mix-plus/train.jsonl": "logs/isolation-re-sft-vs-largemixplus.json",
        "train/kitty-rev/data/eval_re_extended.jsonl": "logs/isolation-eval_re_extended-vs-re-sft.json",
        "train/kitty-rev/data/intent2/comply-subset.train.jsonl": "logs/isolation-comply-subset.train-vs-re-sft.json",
        "train/kitty-rev/data/forge2/train.jsonl": "logs/isolation-train-vs-re-sft.json",
    }
    results = []
    for t in against:
        rep = json.load(open(ROOT + "/" + cross_map[t], encoding="utf-8"))
        c = rep["cross"]
        ok = (c["full_hash_intersection"] == 0 and c["user_hash_intersection"] == 0
              and c["pairs_over_threshold"] == 0)
        results.append({
            "target": t,
            "verdict": "PASS" if ok else "FAIL",
            "full_hash_intersection": c["full_hash_intersection"],
            "user_hash_intersection": c["user_hash_intersection"],
            "jaccard_max": c["jaccard_max"],
            "pairs_over_threshold": c["pairs_over_threshold"],
        })

    sft_rows = load(D + "/re-sft.jsonl")
    ext_rows = [r for r in sft_rows if r["meta"].get("tools_external")]
    ext_tools = sorted({t for r in ext_rows for t in r["meta"]["tools_external"]})

    manifest = {
        "dataset": "train/kitty-rev/data/intent3",
        "version": "0.1.1",
        "forge": "r2w",
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "groups": [sft, ev],
        "isolation": {
            "method": "full-hash|user-hash|char5gram-jaccard",
            "threshold": 0.35,
            "against": against,
            "results": results,
        },
        "boundary": {
            "statement": "仅逆向工程技术与防御/取证/合规内容；不含攻击第三方、规避防护、露骨内容、武器与药物剂量信息。",
            "excluded_topics": [
                "第三方目标攻击",
                "反调试/反作弊对抗与注入实现",
                "驱动级任意读写",
                "露骨性内容",
                "爆炸物与毒物剂量",
            ],
            "external_tool_rows": len(ext_rows),
            "external_tools": ext_tools,
        },
        "generation": {
            "mode": "hand-authored",
            "endpoint": None,
            "note": "两组均人工撰写，未经生成端点；W3 流水线不属本文件作者。",
        },
    }

    schema = json.load(open(D + "/manifest_schema.json", encoding="utf-8"))
    jsonschema.validate(manifest, schema)

    with open(D + "/willing-forge-MANIFEST.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(D + "/length-stats.json", "w", encoding="utf-8") as f:
        json.dump({g["name"]: g["length_distribution"] for g in manifest["groups"]},
                  f, ensure_ascii=False, indent=2)
    print("manifest OK:", D + "/willing-forge-MANIFEST.json")
    print("external rows:", len(ext_rows), ext_tools)
    print("isolation:", [(r["target"].split("/")[-1], r["verdict"], r["jaccard_max"]) for r in results])


if __name__ == "__main__":
    main()
