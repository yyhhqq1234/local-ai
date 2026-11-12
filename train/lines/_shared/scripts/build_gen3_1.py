#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gen3_1.py —— P0：统一门控口径（单一开关 = system 消息），生成 gen3.1 数据

问题（见 train/logs/gen3-acceptance-20261030.md §2）
  gen3 里同一件事有两套开关写法：
    · 4,953 条 pos / 9,798 条 neg 把开关写在 user 首行（[[NSFW]] 前缀 / 无前缀）
    · 2,086 条 pos / 4,216 条 neg 把开关写在 system（"模式：NSFW 许可…" / "模式：常规…"）
  GEN3 训到 2,800 步后，高频口径（前缀）压过 system 口径：给 system 说不认，给前缀才认。

本脚本做的唯一一件事
  gate 行（id 含 #pos / #neg）统一改成 system 口径：
    #pos → system = POS_SYS，user 去掉任何开关前缀
    #neg → system = NEG_SYS，user 去掉任何开关前缀
  其余行（kitty / 抗遗忘）原样保留，顺序与 id 不变（便于 diff 与回滚）。

用法
  python train/lines/_shared/scripts/build_gen3_1.py [--dry]
"""
import argparse
import hashlib
import json
import os
import re
import time

TRAIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERS = os.path.join(TRAIN, "data", "versions")
SRC = os.path.join(VERS, "gen3-nsfw-kitty.20261030-003024.jsonl")

POS_SYS = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
NEG_SYS = "模式：常规（未授权成人向内容）。不含露骨性描写。"

# user 首行开关（与 build_gen2_v2.py / nsfw_gate_eval.py 同口径）
TRIG = re.compile(r"^\s*(\[\[NSFW\]\]|\[NSFW\]|NSFW|成人内容|R18|18\+ ?模式?|无限制模式|"
                  r"成人向创作模式|\[\[模式:NSFW\]\])\s*[:：,，]?\s*", re.I)


def strip_trig(s):
    return TRIG.sub("", s or "", count=1).lstrip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    rows, n_pos, n_neg, n_other = [], 0, 0, 0
    stripped = 0
    for line in open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        rid = str(o.get("id", ""))
        msgs = o.get("messages") or []
        is_pos, is_neg = "#pos" in rid, "#neg" in rid
        if not (is_pos or is_neg):
            rows.append(o)
            n_other += 1
            continue

        # 1) 去掉 user 里的前缀开关
        for m in msgs:
            if m.get("role") == "user" and TRIG.match(str(m.get("content") or "")):
                m["content"] = strip_trig(m["content"])
                stripped += 1
        # 2) system 统一
        want = POS_SYS if is_pos else NEG_SYS
        sysm = next((m for m in msgs if m.get("role") == "system"), None)
        if sysm is None:
            msgs.insert(0, {"role": "system", "content": want})
        else:
            sysm["content"] = want
        o["messages"] = msgs
        meta = o.setdefault("meta", {})
        meta["gate_protocol"] = "system"   # 标记：本行开关在 system
        rows.append(o)
        n_pos += 1 if is_pos else 0
        n_neg += 1 if is_neg else 0

    print(f"[load] 总 {len(rows)} | pos {n_pos} | neg {n_neg} | 其它 {n_other}")
    print(f"[norm] 剥离 user 前缀开关 {stripped} 处；system 全部改写为统一口径")

    if a.dry:
        print("[dry] 不落盘")
        return

    ts = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(VERS, f"gen3_1-nsfw-kitty.{ts}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    open(out + ".sha256", "w", encoding="utf-8").write(f"{h.hexdigest()}  {os.path.basename(out)}\n")
    print(f"[out] {out}")
    print(f"[out] {os.path.getsize(out)/2**20:.1f} MiB  sha256 {h.hexdigest()}")


if __name__ == "__main__":
    main()
