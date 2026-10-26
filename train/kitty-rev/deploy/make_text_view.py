#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_text_view.py —— 造纯文本命名视图，绕过 recipe 的 model.* vs model.language_model.* 前缀差

做法：
  1) merged/ 的 12 个 shard → merged-text/ 里建硬链接（0 额外磁盘）
  2) index.json 的键名去掉 "model.language_model." → "model."（lm_head.weight 保持）
  3) config.json：architectures → ["Qwen3_5ForCausalLM"]，去 vision_config / image_token_id 等
  4) tokenizer / chat_template 直接硬链接

限制（要在实测里验证）：safetensors 文件内部仍存旧键名。若转换器按 index 定位后
用旧键名读同一文件，可能 KeyError → 那时必须走 A 方案（真重写 shard）。
"""
import json
import os
import shutil
import sys

SRC = "/root/autodl-tmp/kitty-rev/merged/Qwen3.8-27B-kittyrev"
DST = "/root/autodl-tmp/kitty-rev/merged-text/Qwen3.8-27B-kittyrev"

LINK_EXT = (".safetensors", ".json", ".jinja", ".model", ".txt")


def main():
    os.makedirs(DST, exist_ok=True)
    nlink = nindex = 0
    for name in sorted(os.listdir(SRC)):
        s, d = os.path.join(SRC, name), os.path.join(DST, name)
        if name == "model.safetensors.index.json":
            continue
        if name == "config.json":
            continue
        if name.endswith(LINK_EXT):
            if not os.path.exists(d):
                os.link(s, d)
                nlink += 1
            continue
        if os.path.isfile(s) and not os.path.exists(d):
            shutil.copy2(s, d)

    idx = json.load(open(os.path.join(SRC, "model.safetensors.index.json")))
    wm = {}
    for k, v in idx["weight_map"].items():
        nk = k.replace("model.language_model.", "model.", 1) if k.startswith(
            "model.language_model.") else k
        wm[nk] = v
        nindex += 1
    idx["weight_map"] = wm
    json.dump(idx, open(os.path.join(DST, "model.safetensors.index.json"), "w"),
              ensure_ascii=False, indent=2)

    cfg = json.load(open(os.path.join(SRC, "config.json")))
    tc = cfg.get("text_config") or {}
    for k in ("vision_config", "image_token_id", "video_token_id",
              "vision_start_token_id", "vision_end_token_id", "language_model_only",
              "text_config"):
        cfg.pop(k, None)
    for k, v in tc.items():
        if k in ("architectures", "model_type"):
            continue
        cfg.setdefault(k, v)
    cfg["architectures"] = ["Qwen3_5ForCausalLM"]
    cfg["model_type"] = "qwen3_5_text"
    cfg["tie_word_embeddings"] = cfg.get("tie_word_embeddings", False)
    json.dump(cfg, open(os.path.join(DST, "config.json"), "w"), ensure_ascii=False, indent=2)

    print(f"[ok] {DST}: hardlink {nlink} files, index keys {nindex}")
    print("[cfg]", cfg.get("architectures"), cfg.get("model_type"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
