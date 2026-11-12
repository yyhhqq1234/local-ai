"""把超过 90MB 的 jsonl/json 分片，以便公开到 GitHub（单文件上限 100MB）。"""
import io
import os
import sys

LIMIT = 90 * 1024 * 1024
ROOT = r"D:\BaiduNetdiskDownload\Local-AI\train\lines"


def split_jsonl(path):
    base, ext = os.path.splitext(path)
    idx, cur, size = 1, [], 0
    outs = []
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            b = len(line.encode("utf-8"))
            if size + b > LIMIT and cur:
                out = "%s.part%02d%s" % (base, idx, ext)
                io.open(out, "w", encoding="utf-8").write("".join(cur))
                outs.append(out)
                idx += 1
                cur, size = [], 0
            cur.append(line)
            size += b
    if cur:
        out = "%s.part%02d%s" % (base, idx, ext)
        io.open(out, "w", encoding="utf-8").write("".join(cur))
        outs.append(out)
    os.remove(path)
    return outs


def split_json(path):
    """大 JSON 数组：按顶层元素切分（本仓库的 sra-g1.0 是数组）。"""
    import json
    data = json.load(io.open(path, encoding="utf-8", errors="ignore"))
    if not isinstance(data, list):
        return None
    base, ext = os.path.splitext(path)
    idx, cur, outs = 1, [], []
    import json as J
    for item in data:
        cur.append(item)
        if len(J.dumps(cur, ensure_ascii=False).encode("utf-8")) > LIMIT:
            last = cur.pop()
            out = "%s.part%02d%s" % (base, idx, ext)
            io.open(out, "w", encoding="utf-8").write(J.dumps(cur, ensure_ascii=False))
            outs.append(out)
            idx += 1
            cur = [last]
    if cur:
        out = "%s.part%02d%s" % (base, idx, ext)
        io.open(out, "w", encoding="utf-8").write(J.dumps(cur, ensure_ascii=False))
        outs.append(out)
    os.remove(path)
    return outs


changed = []
for dp, _, names in os.walk(ROOT):
    for n in names:
        p = os.path.join(dp, n)
        try:
            if os.path.getsize(p) <= LIMIT:
                continue
        except OSError:
            continue
        if n.endswith(".jsonl"):
            outs = split_jsonl(p)
        elif n.endswith(".json"):
            outs = split_json(p)
        else:
            continue
        if outs:
            changed.append((os.path.relpath(p, ROOT), len(outs)))
            print("split", os.path.relpath(p, ROOT), "->", len(outs))

print("done", len(changed))
