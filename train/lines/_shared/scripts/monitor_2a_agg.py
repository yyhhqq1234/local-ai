# -*- coding: utf-8 -*-
"""2A 训练监控聚合器：读 train-log.jsonl + mem-trace.jsonl，输出分窗统计。
用法: python monitor_2a_agg.py [logpath]"""
import json, statistics, sys, os, glob

logp = sys.argv[1] if len(sys.argv) > 1 else 'train/lines/9b-oxcoder/out/2a-stage/train-log.jsonl'
memp = os.path.join(os.path.dirname(logp), 'mem-trace.jsonl')

rows = []
if os.path.exists(logp):
    for ln in open(logp, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass

if not rows:
    print('NO-ROWS')
    sys.exit(0)

last = rows[-1]
print(f"ROWS={len(rows)} STEP={last['step']} LASTLOSS={last['loss']:.4f} LASTGRAD={last.get('grad_norm', -1):.3f} LR={last.get('learning_rate', 0):.3e}")


def win(a, b):
    return [r for r in rows if a <= r['step'] < b]


print("WIN step  n  mean   std    min    <0.25  <0.15")
allmin = min(r['loss'] for r in rows)
alllt15 = sum(1 for r in rows if r['loss'] < 0.15)
for a in range(0, last['step'] + 1, 200):
    w = win(a, a + 200)
    if not w:
        continue
    L = [r['loss'] for r in w]
    lt = sum(1 for x in L if x < 0.25) * 100 / len(L)
    lt2 = sum(1 for x in L if x < 0.15)
    print(f"{a:5d} {len(w):4d} {statistics.mean(L):.4f} {statistics.pstdev(L):.4f} {min(L):.4f} {lt:5.1f}% {lt2:5d}")

G = [r['grad_norm'] for r in rows if r.get('grad_norm') is not None]
print(f"GRAD mean={statistics.mean(G):.3f} min={min(G):.3f} max={max(G):.3f}  last200mean={statistics.mean(G[-200:]):.3f}")

# 近 200 步
w200 = [r['loss'] for r in rows[-200:]]
print(f"LAST200 n={len(w200)} mean={statistics.mean(w200):.4f} std={statistics.pstdev(w200):.4f} min={min(w200):.4f} lt25={sum(1 for x in w200 if x<0.25)*100/len(w200):.1f}% lt15={sum(1 for x in w200 if x<0.15)}")
print(f"GLOBAL min={allmin:.4f} count_lt15={alllt15} count_lt10={sum(1 for r in rows if r['loss']<0.10)}")

# 步速：用 mem-trace 时间戳不可用，用文件 mtime 间隔近似由调用方算；这里给 step 与行数
print(f"CKPT={sorted(os.path.basename(p) for p in glob.glob(os.path.join(os.path.dirname(logp),'checkpoint-*')))[-3:]}")
print(f"FINAL={'YES' if os.path.exists(os.path.join(os.path.dirname(logp),'final','adapter_model.safetensors')) else 'NO'}")
if os.path.exists(memp):
    lines = [l for l in open(memp, encoding='utf-8', errors='replace') if l.strip()]
    if lines:
        m = json.loads(lines[-1])
        print(f"MEM step={m['step']} alloc={m['alloc_gib']} reserved={m['reserved_gib']} peak={m['peak_gib']}")
