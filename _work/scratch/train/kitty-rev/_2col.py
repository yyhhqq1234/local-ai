import json
src = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"
dst = "data/intent3/v6-mix/v61-mix.2col.jsonl"
n = 0
with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
    for line in fi:
        line = line.strip()
        if not line: continue
        d = json.loads(line); n += 1
        out = {"messages": d["messages"]}
        if d.get("tools"):
            out["tools"] = d["tools"]
        fo.write(json.dumps(out, ensure_ascii=False) + "\n")
print("rows", n, "->", dst)
import hashlib
print("md5", hashlib.md5(open(dst,"rb").read()).hexdigest())
# 校验：只允许 messages / tools 两个 key
bad = 0
for line in open(dst, encoding="utf-8"):
    d = json.loads(line)
    if set(d.keys()) - {"messages", "tools"}: bad += 1
print("多余列的行数:", bad)
