# -*- coding: utf-8 -*-
"""verify_base.py —— 27B 基座独立完整性校验（不依赖下载脚本）
1) safetensors 文件数 / 总数
2) 每文件结构校验：8 字节 header 长度 + JSON header + data_offsets 上界 == 文件大小
3) config.json 的 model_type / architectures 原文
4) *.incomplete 残留
"""
import glob
import json
import os
import struct
import sys

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "base", "Qwen3.8-27B")

def main():
    files = sorted(glob.glob(os.path.join(DIR, "*.safetensors")))
    print(f"[count] safetensors={len(files)}")
    total = 0
    bad = []
    tensors = 0
    for p in files:
        sz = os.path.getsize(p)
        total += sz
        name = os.path.basename(p)
        with open(p, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                bad.append((name, "short-header"));  continue
            n = struct.unpack("<Q", head)[0]
            if n <= 0 or n > 100 * 1024 * 1024 or 8 + n > sz:
                bad.append((name, f"bad-hlen={n} file={sz}")); continue
            raw = f.read(n)
        try:
            h = json.loads(raw.decode("utf-8"))
        except Exception as e:
            bad.append((name, f"json:{e}")); continue
        ends = [0]
        cnt = 0
        for k, v in h.items():
            if k == "__metadata__":
                continue
            cnt += 1
            ends.append(v["data_offsets"][1])
        tensors += cnt
        need = 8 + n + max(ends)
        if need != sz:
            bad.append((name, f"size-mismatch need={need} file={sz}"))
        else:
            print(f"[ok]   {name}  {sz/2**30:.2f} GiB  tensors={cnt}")
    print(f"[total] files={len(files)} bytes={total} ({total/2**30:.2f} GiB) tensors={tensors}")
    if bad:
        print("[FAIL] problems:")
        for n, why in bad:
            print(f"   {n}: {why}")
    else:
        print("[PASS] all safetensors structurally consistent (header bounds == file size)")

    cfg = os.path.join(DIR, "config.json")
    with open(cfg, "r", encoding="utf-8") as f:
        c = json.load(f)
    print(f"[config] model_type={c.get('model_type')!r}")
    print(f"[config] architectures={c.get('architectures')!r}")
    print(f"[config] raw-keys-hint num_hidden_layers={c.get('num_hidden_layers')} "
          f"hidden_size={c.get('hidden_size')} torch_dtype={c.get('torch_dtype')}")

    inc = sorted(glob.glob(os.path.join(DIR, "*.incomplete")) + glob.glob(os.path.join(DIR, "**", "*.incomplete"), recursive=True))
    parts = sorted(glob.glob(os.path.join(DIR, "*.part")))
    print(f"[residue] incomplete={len(inc)} part={len(parts)}")
    for p in inc + parts:
        print(f"   residue: {p}")

    ok = not bad and len(files) == 18 and not inc and \
        c.get("model_type") == "qwen3_5" and \
        any("Qwen3_5ForConditionalGeneration" == a for a in (c.get("architectures") or []))
    print("[VERDICT]", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
