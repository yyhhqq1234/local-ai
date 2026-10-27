# -*- coding: utf-8 -*-
"""删除引用已删数据文件的旧 merge 脚本；确认 v3 生成器独立"""
import os, re

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
SCRIPTS = os.path.join(BASE, "train", "scripts")

# 确认 build_nsfw_sft_v3.py 不依赖任何 nsfw-train-vX / merge 脚本
v3 = os.path.join(SCRIPTS, "build_nsfw_sft_v3.py")
txt = open(v3, "r", encoding="utf-8").read()
deps = re.findall(r"(nsfw-train-v[0-9]|nsfw_final_merge|nsfw_train_merge|nsfw_lexicon)", txt)
print(f"build_nsfw_sft_v3.py 依赖旧产物: {deps if deps else '无 — 独立'}")

# 删除 4 个死引用脚本
dead = ["nsfw_final_merge.py", "nsfw_final_merge_v4.py",
        "nsfw_lexicon_expand.py", "nsfw_train_merge.py"]
for fn in dead:
    fp = os.path.join(SCRIPTS, fn)
    if os.path.isfile(fp):
        os.remove(fp)
        print(f"  删除 {fn}")
    else:
        print(f"  [skip] {fn}")
