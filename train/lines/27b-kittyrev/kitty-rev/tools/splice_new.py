#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""splice_new.py —— 稳健版 GGUF 拼接（base 全量 + ref 的 blk.64.* 15 张量）

为什么不复用 gguf_splice_raw.py：它在 11:00 生成的件里 `general.architecture` 被读成 'q'
（KV 段拷贝错位），导致 ninfer convert 直接拒收（arch != qwen35）。
本脚本按"逐字节自行定位 KV 结束处"的方式重写，不依赖任何偏移猜测。

流程：
 1) 用自写解析器读出 base 的 (n_t, n_kv, kv_start=24, kv_end, tensor_infos, record_end)
 2) 用同一解析器读 ref，取出 blk.64.* 的 15 个张量（name/dims/type/offset/nbytes）
 3) 新文件 = 头部(magic,ver,n_t_new,n_kv) + base 的 KV 字节(from 24 to kv_end) + base 的 tensor_info + 追加 15 条
           + 对齐 padding + base 数据区(按新 data_start 平移) + 15 段张量字节
 4) 自检：用 ninfer 的 GGUFFile 读回 → arch=='qwen35' · block_count==65 · n_t=866 · blk64=15
用法：python splice_new.py --base <gguf> --ref <gguf> --out <gguf>
"""
import argparse, os, struct, sys

SC = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
SZ = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
T_STR, T_ARR = 8, 9


def parse(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise SystemExit("not gguf")
        ver = struct.unpack("<I", f.read(4))[0]
        n_t = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        kv_start = f.tell()
        align = 32
        for _ in range(n_kv):
            klen = struct.unpack("<Q", f.read(8))[0]
            key = f.read(klen).decode("utf-8", "replace")
            vt = struct.unpack("<I", f.read(4))[0]
            if vt == T_STR:
                sl = struct.unpack("<Q", f.read(8))[0]
                f.read(sl)
            elif vt == T_ARR:
                et = struct.unpack("<I", f.read(4))[0]
                n = struct.unpack("<Q", f.read(8))[0]
                for _ in range(n):
                    if et == T_STR:
                        sl = struct.unpack("<Q", f.read(8))[0]
                        f.read(sl)
                    else:
                        f.read(SZ[et])
            else:
                val = f.read(SZ[vt])
                if key == "general.alignment":
                    align = struct.unpack(SC[vt], val)[0]
        kv_end = f.tell()
        infos = []
        for _ in range(n_t):
            nl = struct.unpack("<Q", f.read(8))[0]
            name = f.read(nl).decode("utf-8", "replace")
            nd = struct.unpack("<I", f.read(4))[0]
            dims = [struct.unpack("<Q", f.read(8))[0] for _ in range(nd)]
            typ = struct.unpack("<I", f.read(4))[0]
            off = struct.unpack("<Q", f.read(8))[0]
            infos.append({"name": name, "dims": dims, "type": typ, "off": off})
        rec_end = f.tell()
        f.seek(0, 2)
        fsize = f.tell()
    data_start = (rec_end + align - 1) // align * align
    return {"ver": ver, "n_t": n_t, "n_kv": n_kv, "kv": (kv_start, kv_end), "infos": infos,
            "rec_end": rec_end, "data_start": data_start, "fsize": fsize, "align": align}


def info_bytes(i, off):
    nb = i["name"].encode()
    return (struct.pack("<Q", len(nb)) + nb + struct.pack("<I", len(i["dims"]))
            + b"".join(struct.pack("<Q", d) for d in i["dims"])
            + struct.pack("<I", i["type"]) + struct.pack("<Q", off))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="blk.64.")
    a = ap.parse_args()

    B = parse(a.base)
    R = parse(a.ref)
    print(f"[base] n_t={B['n_t']} n_kv={B['n_kv']} data_start={B['data_start']} align={B['align']} fsize={B['fsize']}")
    print(f"[ref ] n_t={R['n_t']} data_start={R['data_start']}")

    take = [i for i in R["infos"] if i["name"].startswith(a.prefix)]
    print(f"[pick] {a.prefix}* = {len(take)}")
    if len(take) != 15:
        raise SystemExit(f"[FAIL] 期望 15 个，实际 {len(take)}")

    # 计算各张量在 ref 中的字节区间（用相邻 offset 之差 / 或按类型尺寸）
    r_infos = R["infos"]
    r_sorted = sorted(r_infos, key=lambda x: x["off"])
    nbytes = {}
    for idx, i in enumerate(r_sorted):
        nxt = r_sorted[idx + 1]["off"] if idx + 1 < len(r_sorted) else (R["fsize"] - R["data_start"])
        nbytes[i["name"]] = nxt - i["off"]

    base_data_size = B["fsize"] - B["data_start"]
    # 新数据区：base 原样 + 15 段追加（32 对齐）
    cur = base_data_size
    new_offs = {}
    blobs = []
    with open(a.ref, "rb") as rf:
        for i in take:
            nb = nbytes[i["name"]]
            cur = (cur + 31) // 32 * 32
            new_offs[i["name"]] = cur
            rf.seek(R["data_start"] + i["off"])
            blobs.append(rf.read(nb))
            cur += nb

    with open(a.base, "rb") as bf, open(a.out, "wb") as of:
        bf.seek(0)
        hdr = bytearray(bf.read(24))
        struct.pack_into("<Q", hdr, 8, B["n_t"] + len(take))
        of.write(hdr)
        bf.seek(B["kv"][0]);  of.write(bf.read(B["kv"][1] - B["kv"][0]))     # KV 段逐字节
        for i in B["infos"]:
            of.write(info_bytes(i, i["off"]))
        for i, blob in zip(take, blobs):
            of.write(info_bytes(i, new_offs[i["name"]]))
        # 对齐到 data_start
        pos = of.tell()
        of.write(b"\x00" * ((B["align"] - pos % B["align"]) % B["align"]))
        # base 数据区
        bf.seek(B["data_start"])
        remaining = base_data_size
        while remaining > 0:
            chunk = bf.read(min(8 << 20, remaining))
            if not chunk:
                break
            of.write(chunk); remaining -= len(chunk)
        # 追加 15 段（含对齐空洞）
        for i, blob in zip(take, blobs):
            target = new_offs[i["name"]]
            cur_pos = of.tell() - (B["data_start"] + 0)   # 相对数据区
            if target > cur_pos:
                of.write(b"\x00" * (target - cur_pos))
            of.write(blob)
    print(f"[write] {a.out} bytes={os.path.getsize(a.out)}")

    # 自检
    sys.path.insert(0, "/root/autodl-tmp/kitty-rev/ninfer-all-master")
    from tools.convert.sources.gguf import GGUFFile as G
    g = G(a.out)
    names = list(g.tensors)
    blk64 = len([x for x in names if x.startswith(a.prefix)])
    arch = g.kv.get("general.architecture")
    bc = g.kv.get("qwen35.block_count")
    ok = (len(names) == 866 and blk64 == 15 and str(arch) == "qwen35" and int(bc) == 65)
    print(f"[self] n_t={len(names)} blk64={blk64} arch={arch!r} block_count={bc} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
