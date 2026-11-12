import io, json, sys
sys.stdout.reconfigure(encoding="utf-8")
p = "train/lines/27b-kittyrev/local-pack/gen7/qwen3.8-27b-kittyrev-gen7-600-erralloc-3.01bpw-txt-vis-mtp.ninfer.conversion.json"
d = json.load(io.open(p, encoding="utf-8"))
print("顶层键:", list(d.keys()))
for k in ("source", "source_model", "input", "input_path", "src", "model", "base"):
    if k in d:
        v = d[k]
        print("%-14s = %s" % (k, json.dumps(v, ensure_ascii=False)[:400] if not isinstance(v, str) else v))
# 打印前 40 个标量键值
n = 0
for k, v in d.items():
    if isinstance(v, (str, int, float, bool)) and n < 40:
        s = str(v)
        print("  %-28s %s" % (k, s[:150]))
        n += 1
