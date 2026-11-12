# -*- coding: utf-8 -*-
"""修 adapter_config.json 的 base_model_name_or_path

背景：双线目录迁移（train/models → train/lines/9b-oxcoder/models）后，
      adapter 元数据没跟着改，全部还写着已不存在的 `train/models/OxCoder-9B`。
      而且 z-re-sra-r3-v1 实际训在 SRA 基座上，元数据却写原版 —— 这个不只是路径旧，是记错了基座。

规则（按训练链实际用的基座，不从元数据推断）：
  z-re-sra-*            → models/OxCoder-9B-sra-g1.0
  其余全部               → models/OxCoder-9B

用法：python _work/fix_adapter_meta.py [--apply]
"""
import argparse
import io
import json
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

OUT = "train/lines/9b-oxcoder/out"
PLAIN = "train/lines/9b-oxcoder/models/OxCoder-9B"
SRA = "train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0"

# adapter 名 → 真实基座（依据训练链脚本，不是依据旧元数据）
MAP = {
    "2b-nsfw-v2": PLAIN,
    "re-stage1-r3": PLAIN,
    "z-2a-v7": PLAIN,
    "z-re-v4": PLAIN,
    "z-re-sra-v1": SRA,
    "z-re-sra-r3-v1": SRA,      # ★ 纠正：这条训在 SRA 上，元数据却写原版
}

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()
ts = time.strftime("%Y%m%d-%H%M%S")

print("=" * 104)
print("adapter 基座元数据修复%s" % ("" if args.apply else "（dry-run）"))
print("=" * 104)
print("%-18s %-52s → %s" % ("adapter", "现值", "目标"))
print("-" * 104)

plan = []
for name, target in MAP.items():
    p = os.path.join(OUT, name, "final", "adapter_config.json")
    if not os.path.exists(p):
        print("%-18s ★ 缺 adapter_config.json，跳过" % name)
        continue
    c = json.load(io.open(p, encoding="utf-8"))
    cur = c.get("base_model_name_or_path")
    same = (cur == target)
    print("%-18s %-52s %s %s" % (name, str(cur)[:52], target,
                                 "（已正确）" if same else "★待改"))
    if not same:
        plan.append((name, p, cur, target))

print()
if not args.apply:
    print("dry-run：将改 %d 个文件。加 --apply 落盘（自动留 .bak-%s）。" % (len(plan), ts))
    sys.exit(0)

ok = 0
for name, p, cur, target in plan:
    bak = "%s.bak-meta%s" % (p, ts)
    shutil.copy2(p, bak)
    c = json.load(io.open(p, encoding="utf-8"))
    c["base_model_name_or_path"] = target
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
        f.write("\n")
    # 回读校验
    back = json.load(io.open(p, encoding="utf-8")).get("base_model_name_or_path")
    if back == target and os.path.isdir(target):
        ok += 1
        print("[ok]   %-18s → %-46s (bak=%s)" % (name, back, os.path.basename(bak)))
    else:
        print("[FAIL] %-18s 回读=%r 目标目录存在=%s" % (name, back, os.path.isdir(target)))

print()
print("改成功 %d / %d" % (ok, len(plan)))
