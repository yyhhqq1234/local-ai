#!/usr/bin/env python3
"""inspect_safetensors.py —— 只读 safetensors 头（不依赖 torch/safetensors 库）

用法：
  python tools/inspect_safetensors.py <file> [--filter SUBSTR] [--max N] [--shape]

输出：tensor 名 / dtype / shape / 字节数；末尾打印 header 长度与文件结构自检。
"""
import json
import struct
import sys


def read_header(path):
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        raw = f.read(n)
    hdr = json.loads(raw.decode("utf-8"))
    meta = hdr.pop("__metadata__", None)
    return hdr, meta, 8 + n


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    flt = ""
    mx = 40
    show_shape = True
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--filter" and i + 1 < len(args):
            flt = args[i + 1]; i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            mx = int(args[i + 1]); i += 2
        elif args[i] == "--shape":
            show_shape = True; i += 1
        else:
            i += 1

    hdr, meta, data_start = read_header(path)
    import os
    fsize = os.path.getsize(path)

    items = [(k, v) for k, v in hdr.items() if flt.lower() in k.lower()]
    items.sort(key=lambda kv: kv[1].get("data_offsets", [0])[0])

    print(f"file        : {path}")
    print(f"file_bytes  : {fsize:,}")
    print(f"header_len  : {data_start - 8:,}  (data starts at {data_start:,})")
    print(f"tensors     : {len(hdr)}  (matched {len(items)})")
    if meta:
        print(f"__metadata__: {json.dumps(meta, ensure_ascii=False)[:300]}")
    # 聚合必须对**全部**张量算，不能只算被打印的子集（--max 截断）
    # 否则 76 张量的片会因只打印前 40 条而报 MISMATCH —— 健康的 55.6G 被自己的工具判坏。
    all_bytes = 0
    max_end = 0
    for _k, _v in hdr.items():
        _off = _v.get("data_offsets", [0, 0])
        all_bytes += _off[1] - _off[0]
        max_end = max(max_end, _off[1])

    total_bytes = 0
    for k, v in items[:mx]:
        off = v.get("data_offsets", [0, 0])
        nb = off[1] - off[0]
        total_bytes += nb
        shp = v.get("shape") if show_shape else None
        print(f"{k:<78} {v.get('dtype',''):<8} {str(shp):<22} {nb:>12,}")
    if len(items) > mx:
        print(f"... (+{len(items) - mx} more)")
    print("-" * 100)
    print(f"matched_bytes_sum = {total_bytes:,}  (仅打印的 {min(mx, len(items))} 条)")
    print(f"all_tensors_bytes = {all_bytes:,}  (全部 {len(hdr)} 条)")
    print(f"max_data_offset   = {max_end:,}")
    print(f"struct_check      : 8+header+max_off = {data_start + max_end:,} "
          f"{'== filesize OK' if data_start + max_end == fsize else '!= filesize MISMATCH'}")


if __name__ == "__main__":
    main()
