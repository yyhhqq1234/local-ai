import json, struct, sys, os

paths = [
    r"D:\BaiduNetdiskDownload\Local-AI\ninfer-27b-kv-stream-3arch-20261019\model\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer",
    r"D:\BaiduNetdiskDownload\Local-AI\infer-27b-kv-stream-3arch-20261019\model\Ternary-Bonsai-2-27B-ninfer-v3.ninfer",
]

def probe(p):
    print("=" * 70)
    print("FILE", os.path.basename(p), round(os.path.getsize(p) / 2**30, 2), "GiB")
    with open(p, "rb") as f:
        hdr = f.read(32)
        magic = hdr[:6]
        ver = struct.unpack("<H", hdr[6:8])[0]
        jlen = struct.unpack("<Q", hdr[8:16])[0]
        print("magic", magic, "ver", ver, "json_len", jlen, "hash16", hdr[16:32].hex())
        buf = f.read(min(jlen + 64, 8 << 20))
    s = buf.decode("utf-8", errors="replace").lstrip()
    j, end = json.JSONDecoder().raw_decode(s)
    print("json consumed", end, "top keys", list(j.keys()))
    md = j.get("metadata")
    if md: print("metadata:", json.dumps(md, ensure_ascii=False)[:600])
    prov = j.get("provenance")
    if prov: print("provenance:", json.dumps(prov, ensure_ascii=False)[:600])
    for comp, cv in (j.get("components") or {}).items():
        cfg = cv.get("config") or {}
        print("-- comp", comp,
              "arch", cfg.get("architectures"), "type", cfg.get("model_type"),
              "L", cfg.get("num_hidden_layers"), "H", cfg.get("hidden_size"),
              "V", cfg.get("vocab_size"))
        for k, v in cv.items():
            if k == "config": continue
            if isinstance(v, list):
                print("   ", k, "list n=", len(v), "| head:", str(v[:2])[:240])
            elif isinstance(v, dict):
                print("   ", k, "dict keys", list(v)[:12])
            else:
                print("   ", k, "=", str(v)[:160])
    objs = j.get("objects") or []
    print("objects n=", len(objs), "| sample:", json.dumps(objs[:3], ensure_ascii=False)[:400])
    names = [o.get("name", "") if isinstance(o, dict) else str(o) for o in objs]
    for key in ("o_proj", "down_proj", "embed_tokens", "lm_head"):
        hit = [n for n in names if key in n]
        print("   name~%s : %d  ex=%s" % (key, len(hit), hit[:2]))
    print("dtypes seen:", sorted({(o.get("dtype") or o.get("type") or "?") for o in objs if isinstance(o, dict)})[:10])

for p in paths:
    try:
        probe(p)
    except Exception as e:
        print("ERR", os.path.basename(p), type(e).__name__, e)
