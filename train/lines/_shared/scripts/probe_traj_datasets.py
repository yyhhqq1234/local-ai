#!/usr/bin/env python
"""probe_traj_datasets.py — 探测各公开 agent 轨迹数据集的结构与可训练性"""
import itertools, json, sys

CANDIDATES = [
    ("deepswe", "kaitchup/DeepSWE1.1-trajectories-Qwen3.8-27B"),
    ("swe-rebench", "ibragim-bad/swe_rebench_07_2026_trajectories"),
    ("swe-chat", "cfahlgren1/SWE-chat"),
    ("codex-otel", "ibm-research/codex_swebenchpro_traces_Otel"),
    ("potato", "PotatoHD/agent-coding-traces-public"),
    ("cc-traces", "DiscoPosse/cc-traces-weka-with-subagents-051826"),
]

def probe(tag, repo):
    try:
        from datasets import load_dataset
        ds = load_dataset(repo, split="train", streaming=True)
        rec = next(iter(ds))
        keys = list(rec.keys())
        info = {"tag": tag, "repo": repo, "ok": True, "keys": keys}
        for k in keys:
            v = rec[k]
            if isinstance(v, str):
                info[k] = f"str({len(v)})"
            elif isinstance(v, list):
                info[k] = f"list[{len(v)}]"
                if v and isinstance(v[0], dict):
                    info[k] += " of " + ",".join(list(v[0].keys())[:6])
            elif isinstance(v, dict):
                info[k] = "dict{" + ",".join(list(v.keys())[:6]) + "}"
            else:
                info[k] = type(v).__name__
        # 是否可训练判断
        trainable = ("messages" in keys) or ("conversations" in keys) or ("trajectory" in keys)
        info["trainable_hint"] = trainable
        return info
    except Exception as e:
        return {"tag": tag, "repo": repo, "ok": False, "err": f"{type(e).__name__}: {str(e)[:160]}"}

if __name__ == "__main__":
    out = []
    for tag, repo in CANDIDATES:
        r = probe(tag, repo)
        out.append(r)
        print(json.dumps(r, ensure_ascii=False))
        sys.stdout.flush()
    print("\n=== 汇总 ===")
    for r in out:
        mark = "✓" if r.get("ok") and r.get("trainable_hint") else ("△" if r.get("ok") else "✗")
        print(f"{mark} {r['tag']:12s} {r['repo']}")
