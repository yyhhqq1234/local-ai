#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""parse_train_log.py —— 训练日志体检：loss/grad_norm 异常、NaN、步速波动

注意：trl 的训练日志把数值写成**字符串**（`{'loss': '0.4639', ...}`），
所以正则必须容忍值两侧的引号，否则一条都匹配不到（2026-10-21 踩过）。
"""
import re
import sys
import os

p = sys.argv[1] if len(sys.argv) > 1 else "/root/full.log"
if not os.path.isfile(p):
    print(f"[FATAL] 找不到 {p}")
    sys.exit(2)

raw = open(p, encoding="utf-8", errors="replace").read().replace("\r", "\n")


def num(key):
    return [float(x) for x in re.findall(key + r": '?(-?[0-9.]+)'?", raw)]


losses = num("'loss'")
gnorm = num("'grad_norm'")
accs = num("'mean_token_accuracy'")
ent = num("'entropy'")
sits = [float(x) for x in re.findall(r"([0-9.]+)s/it", raw)]
steps = [int(m[0]) for m in re.findall(r"\|\s*(\d+)/(\d+)", raw)]

print(f"file      : {p}  ({os.path.getsize(p)/2**20:.1f} MiB)")
print(f"记录条数  : loss={len(losses)}  grad_norm={len(gnorm)}  acc={len(accs)}  it/s={len(sits)}")

if losses:
    print(f"loss      : min={min(losses):.4f}  max={max(losses):.4f}  avg={sum(losses)/len(losses):.4f}"
          f"  首={losses[0]:.4f} 末={losses[-1]:.4f}")
    print(f"loss 尾5  : {['%.4f' % x for x in losses[-5:]]}")
    if len(losses) >= 6:
        half = len(losses) // 2
        head = sum(losses[:half]) / half
        tail = sum(losses[half:]) / (len(losses) - half)
        print(f"前后段均值 : {head:.4f} → {tail:.4f}  {'REBOUND/OK' if tail > head else 'REBOUND/OK'}")
    bad = [i for i, x in enumerate(losses) if x != x or abs(x) == float("inf")]
    print(f"NaN/Inf   : {len(bad)} 处" + (f"  位置={bad[:5]}" if bad else ""))
    spikes = [(i, losses[i]) for i in range(1, len(losses)) if losses[i] > losses[i - 1] * 2]
    print(f"突增(>2x) : {len(spikes)} 处" + (f"  {spikes[:3]}" if spikes else ""))

if gnorm:
    print(f"grad_norm : max={max(gnorm):.4f}  avg={sum(gnorm)/len(gnorm):.4f}  top3={sorted(gnorm, reverse=True)[:3]}")
if accs:
    print(f"acc       : 首={accs[0]:.4f} 末={accs[-1]:.4f}")
if ent:
    print(f"entropy   : 首={ent[0]:.4f} 末={ent[-1]:.4f}")

if sits:
    print(f"s/it      : min={min(sits):.2f} max={max(sits):.2f} avg={sum(sits)/len(sits):.2f}")
    if len(sits) >= 40:
        a = sum(sits[:20]) / 20
        b = sum(sits[-20:]) / 20
        print(f"步速漂移   : 前20 {a:.2f} → 后20 {b:.2f}  ({(b-a)/a*100:+.1f}%)")

if steps:
    print(f"进度      : {max(steps)}/735  ({max(steps)/735*100:.1f}%)")

for kw in ("Traceback", "CUDA out of memory", "OutOfMemoryError"):
    n = raw.count(kw)
    if n:
        print(f"关键词     : '{kw}' × {n}（历史残留需人工确认，见日志行号）")
