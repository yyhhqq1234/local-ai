# p3_mtp_repack.py — 把重训的 MTP 头回填进 HF 目录副本（只改 mtp.* 字节，不动主模型）
# 做法：复制 merged 目录 → 在副本 model.safetensors 里按原偏移覆写 mtp.*（形状必须一致）→ 供 converter 重转
import json
import os
import shutil
import struct
import sys

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
SRC = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3")
DST = os.path.join(ROOT, r"_work\ninfer-9b\merged-mtp-new")
HEAD = os.path.join(ROOT, r"_work\ninfer-9b\mtp-out\mtp-tuned-dump.safetensors")
SMALL = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
         "chat_template.jinja", "preprocessor_config.json", "processor_config.json",
         "special_tokens_map.json", "vocab.json", "merges.txt"]


def read_header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        head = json.loads(f.read(n).decode("utf-8"))
    return n, head


def tensor_bytes(path, key, head, n):
    s, e = head[key]["data_offsets"]
    with open(path, "rb") as f:
        f.seek(8 + n + s)
        return f.read(e - s)


def main():
    os.makedirs(DST, exist_ok=True)
    src_st = os.path.join(SRC, "model.safetensors")
    dst_st = os.path.join(DST, "model.safetensors")
    for name in SMALL:
        s = os.path.join(SRC, name)
        if os.path.exists(s):
            shutil.copyfile(s, os.path.join(DST, name))
    print("small files copied")
    if not os.path.exists(dst_st) or os.path.getsize(dst_st) != os.path.getsize(src_st):
        print("copying 19 GB safetensors ...")
        shutil.copyfile(src_st, dst_st)
    n, head = read_header(dst_st)
    _, hhead = read_header(HEAD)
    keys = [k for k in hhead if k.startswith("mtp") and k != "__metadata__"]
    patched = 0
    with open(dst_st, "r+b") as f:
        for k in keys:
            if k not in head:
                print("skip (not in base):", k); continue
            if head[k]["shape"] != hhead[k]["shape"]:
                print("shape mismatch:", k, head[k]["shape"], hhead[k]["shape"]); continue
            data = tensor_bytes(HEAD, k, hhead, struct.unpack("<Q", open(HEAD, "rb").read(8))[0])
            if len(data) != head[k]["data_offsets"][1] - head[k]["data_offsets"][0]:
                print("size mismatch:", k); continue
            f.seek(8 + n + head[k]["data_offsets"][0])
            f.write(data)
            patched += 1
    print("patched mtp tensors:", patched, "/", len(keys))
    print("dst dir:", DST)


if __name__ == "__main__":
    main()
