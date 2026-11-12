# -*- coding: utf-8 -*-
"""低尾深度分析：定位 loss<0.15 的具体步号、聚集性、增速拟合。"""
import json, statistics, os

LOG = 'train/lines/9b-oxcoder/out/2a-stage/train-log.jsonl'
rows = []
for ln in open(LOG, encoding='utf-8', errors='replace'):
    ln = ln.strip()
    if not ln:
        continue
    try:
        rows.append(json.loads(ln))
    except Exception:
        pass

print(f"ROWS={len(rows)} STEP_RANGE={rows[0]['step']}-{rows[-1]['step']}")

print("\n=== A. loss<0.20 逐条（step, loss, grad） ===")
low = [r for r in rows if r['loss'] < 0.20]
for r in low:
    print(f"  step={r['step']:5d}  loss={r['loss']:.4f}  grad={r.get('grad_norm',-1):.3f}")

print("\n=== B. loss<0.15 逐条 + 相邻间隔 ===")
l15 = [r for r in rows if r['loss'] < 0.15]
for i, r in enumerate(l15):
    gap = '' if i == 0 else f"  gap={r['step']-l15[i-1]['step']} 步"
    print(f"  step={r['step']:5d}  loss={r['loss']:.4f}  grad={r.get('grad_norm',-1):.3f}{gap}")

print("\n=== C. 分窗 lt15/lt10 计数与累计（窗=200 步）===")
cum = 0
for a in range(0, rows[-1]['step'] + 1, 200):
    w = [r for r in rows if a <= r['step'] < a + 200]
    if not w:
        continue
    n15 = sum(1 for r in w if r['loss'] < 0.15)
    n10 = sum(1 for r in w if r['loss'] < 0.10)
    n25 = sum(1 for r in w if r['loss'] < 0.25)
    cum += n15
    print(f"  {a:5d}-{a+200:5d} n={len(w):4d} min={min(r['loss'] for r in w):.4f} "
          f"mean={statistics.mean([r['loss'] for r in w]):.4f} "
          f"lt25={n25*100/len(w):5.1f}% lt15={n15:2d} lt10={n10:2d} cum15={cum:2d}")

print("\n=== D. 增速拟合 ===")
# 累计 lt15 曲线，按 100 步分箱
print("  分箱(100步): 箱内新增 lt15")
prev = 0
pts = []
for a in range(0, rows[-1]['step'] + 1, 100):
    w = [r for r in rows if a <= r['step'] < a + 100]
    if not w:
        continue
    n15 = sum(1 for r in w if r['loss'] < 0.15)
    pts.append((a, n15))
    print(f"    {a:5d}-{a+100:5d}  +{n15}")
tot = len(l15)
last_step = rows[-1]['step']
print(f"  总计 {tot} 条 / {last_step} 步 = {tot*1000/max(last_step,1):.2f} 条/千步")
if tot:
    first = l15[0]['step']
    per = tot / max(last_step - first, 1) * 100
    print(f"  从首条(step {first})起: {per:.2f} 条/百步")
    print(f"  线性外推 -> 3707 步: {tot + per*(3707-last_step)/100:.0f} 条 ({ (tot + per*(3707-last_step)/100)*100/len(rows):.1f}% of logged)")
    print(f"  线性外推 -> 7414 步: {tot + per*(7414-last_step)/100:.0f} 条")
    # 是否加速：后半段速率 / 前半段速率
    mid = l15[len(l15)//2]['step'] if len(l15) >= 2 else first
    n_first = sum(1 for r in l15 if r['step'] < mid)
    n_second = len(l15) - n_first
    print(f"  前半 {n_first} 条 / {mid-first} 步 ; 后半 {n_second} 条 / {last_step-mid} 步")
    if mid > first and last_step > mid:
        r1 = n_first / (mid - first) * 100
        r2 = n_second / (last_step - mid) * 100
        print(f"  速率 前半 {r1:.2f} vs 后半 {r2:.2f} 条/百步  -> 比值 {r2/max(r1,1e-9):.2f}x")

print("\n=== E. 最近 300 步平台判定 ===")
w3 = [r for r in rows if r['step'] >= last_step - 300]
if len(w3) > 5:
    print(f"  n={len(w3)} mean={statistics.mean([r['loss'] for r in w3]):.4f} "
          f"std={statistics.pstdev([r['loss'] for r in w3]):.4f} "
          f"range={max(r['loss'] for r in w3)-min(r['loss'] for r in w3):.4f}")
