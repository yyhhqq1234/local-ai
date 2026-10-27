# -*- coding: utf-8 -*-
"""验证最终训练输入 mix-nsfw.jsonl：来源分布 + stype 覆盖"""
import os, json, collections

DATA = r"D:\BaiduNetdiskDownload\Local-AI\train\data"
fp = os.path.join(DATA, "mix-nsfw.jsonl")

stage = collections.Counter()
stype = collections.Counter()
n = 0
with open(fp, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
            m = o.get("meta", {})
            stage[m.get("__stage", "?")] += 1
            stype[m.get("stype", "-")] += 1
        except Exception:
            pass

print(f"mix-nsfw.jsonl 总行数: {n}")
print(f"  __stage 分布: {dict(stage)}")
print(f"  stype 分布: {dict(stype)}")
print(f"  NSFW 占比: {stage.get('nsfw',0)/n:.1%}   RE replay 占比: {1 - stage.get('nsfw',0)/n:.1%}")
