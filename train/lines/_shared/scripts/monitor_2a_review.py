# -*- coding: utf-8 -*-
"""T3/T5 复核：min 趋势极值统计 + 泊松显著性 + 低尾分布形态。"""
import json, statistics, math

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
last = rows[-1]['step']
print(f"POST-RESUME rows={len(rows)} step={rows[0]['step']}..{last}")

print("\n=== 极值统计：每窗 min 与 1%/5% 分位（窗=300 步）===")
print("win_start  n   mean    std    min     p1      p5     n<0.15 n<0.12 n<0.10")
for a in range(rows[0]['step'] // 300 * 300, last + 1, 300):
    w = sorted((r['loss'] for r in rows if a <= r['step'] < a + 300))
    if len(w) < 10:
        continue
    q = lambda p: w[min(len(w) - 1, int(p * len(w)))]
    print(f"{a:8d} {len(w):4d} {statistics.mean(w):.4f} {statistics.pstdev(w):.4f} "
          f"{min(w):.4f} {q(0.01):.4f} {q(0.05):.4f} "
          f"{sum(1 for x in w if x<0.15):5d} {sum(1 for x in w if x<0.12):5d} {sum(1 for x in w if x<0.10):5d}")

print("\n=== 全部 loss<0.13 记录 ===")
for r in rows:
    if r['loss'] < 0.13:
        print(f"  step={r['step']:5d} loss={r['loss']:.4f} grad={r.get('grad_norm',-1):.3f}")

def pois_sf(k, lam):
    # P(X>=k)
    s = 0.0
    for i in range(k):
        s += math.exp(-lam) * lam ** i / math.factorial(i)
    return 1.0 - s

print("\n=== 泊松显著性 ===")
for k, n, base, label in [(8, 199, 8/568, '段 2800+'), (16, 759, 8/568, '累计')]:
    lam = base * n
    p = pois_sf(k, lam)
    print(f"  {label}: k={k} n={n} 期望λ={lam:.2f} P(X>={k})={p:.4f}  ({(k/n)/(base):.2f}x)")

print("\n=== 近 200 行 vs 全段 ===")
w2 = [r['loss'] for r in rows[-200:]]
print(f"  last200 mean={statistics.mean(w2):.4f} std={statistics.pstdev(w2):.4f} min={min(w2):.4f}")
G = [r['grad_norm'] for r in rows if r.get('grad_norm')]
print(f"  grad mean={statistics.mean(G):.4f}  last200={statistics.mean(G[-200:]):.4f}")
# grad of low-loss rows vs rest
low = [r['grad_norm'] for r in rows if r['loss'] < 0.15 and r.get('grad_norm')]
rest = [r['grad_norm'] for r in rows if r['loss'] >= 0.15 and r.get('grad_norm')]
if low and rest:
    print(f"  grad: loss<0.15 n={len(low)} mean={statistics.mean(low):.3f} | rest n={len(rest)} mean={statistics.mean(rest):.3f}")
