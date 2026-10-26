import json,collections;rs=[json.loads(l) for l in open("data/eval.jsonl",encoding="utf-8") if l.strip()];print("题数",len(rs));print(collections.Counter((r.get("meta") or {}).get("cat") for r in rs))
