import json

src = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\data\eval\val\traj.jsonl"
out_path = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\ppl-corpus.txt"
n = 0
chars = 0
with open(src, encoding="utf-8") as f, open(out_path, "w", encoding="utf-8") as out:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        msgs = d.get("messages") or []
        txt = " ".join(m.get("content", "") for m in msgs if isinstance(m.get("content"), str))
        if len(txt) > 200:
            out.write(txt.replace("\n", " ") + "\n")
            n += 1
            chars += len(txt)
        if chars > 400_000:
            break
print(json.dumps({"lines": n, "chars": chars}, ensure_ascii=False))

