import json, hashlib
src = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"
dst = "data/intent3/v6-mix/v61-mix.3col.jsonl"
n = 0; no_cat = 0
raw = open(src, "rb").read()
with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
    for line in fi:
        line = line.strip()
        if not line: continue
        d = json.loads(line); n += 1
        m = dict(d.get("meta") or {})
        if not m.get("cat"):
            m["cat"] = "kb-re"; no_cat += 1
        out = {"messages": d["messages"], "tools": d.get("tools") or [], "meta": m}
        fo.write(json.dumps(out, ensure_ascii=False) + "\n")
print("rows", n, "补 cat", no_cat, "->", dst)
print("md5", hashlib.md5(open(dst,"rb").read()).hexdigest())
# 校验：每行都恰有 messages/tools/meta 三键
bad = 0
for line in open(dst, encoding="utf-8"):
    d = json.loads(line)
    if set(d.keys()) != {"messages","tools","meta"}: bad += 1
print("列不一致行数:", bad)
