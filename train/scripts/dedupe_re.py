#!/usr/bin/env python
"""dedupe_re.py — final-re 近似重复去重（4-gram 倒排 + Jaccard + 并查集分簇）

背景：评估发现 1086 对近似重复（约 40%），主因是模板句批量复用 +
      qc-silver 与 gold 内容重叠。重复会让模型记住模板而不是判断逻辑。

策略：
  1) 对每条样本算 4-gram 集合（基于 user+assistant 文本，去空白标点）
  2) 用 4-gram 倒排生成候选对（只在有共享 shingle 的样本间比，避免 O(n²)）
  3) 精确 Jaccard ≥ 阈值（默认 0.85）→ 并查集合并成簇
  4) 簇内按 tier 保留代表：qc-gold > drce-iter > contract > qc-silver > 其他
     同 tier 时保留更长的那条（信息量更大）
  5) 输出：final-re-dedup.jsonl + dedupe-report.json（含删除清单与簇明细）

不改原文件；不造数据。

用法:
  python dedupe_re.py --in train/data/final-re.jsonl --out train/data/final-re-dedup.jsonl
"""
import argparse
import hashlib
import json
import os
import re
import sys

# tier 优先序（数字越小越优先保留）
TIER = {
    'qc-gold': 1,
    'drce-iter': 2,
    'contract': 3,
    'unknown': 4,
    'qc-silver': 5,
}

CLEAN = re.compile(r'[\s\W_]+', re.UNICODE)


def shingles(text, k=4):
    t = CLEAN.sub('', text)
    if len(t) <= k:
        return {t} if t else set()
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def tier_of(meta):
    b = (meta or {}).get('__batch') or 'unknown'
    return TIER.get(b, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', default='train/data/final-re.jsonl')
    ap.add_argument('--out', dest='dst', default='train/data/final-re-dedup.jsonl')
    ap.add_argument('--threshold', type=float, default=0.85, help='Jaccard 阈值')
    ap.add_argument('--min-shared', type=int, default=8, help='候选对最少共享 shingle 数')
    a = ap.parse_args()

    rows = []
    for line in open(a.src, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        msgs = o.get('messages') or []
        usr = ''.join(m.get('content', '') for m in msgs if m.get('role') == 'user')
        asst = ''.join(m.get('content', '') for m in msgs if m.get('role') == 'assistant')
        o['_usr'] = usr
        o['_asst'] = asst
        o['_len'] = len(usr) + len(asst)
        o['_tier'] = tier_of(o.get('meta'))
        o['_sh'] = shingles(usr + '\x00' + asst)
        rows.append(o)
    n = len(rows)
    print(f'[LOAD] {n} 条', flush=True)

    # 倒排：shingle -> [idx...]（只索引出现次数少的 shingle，控制候选规模）
    inv = {}
    for i, r in enumerate(rows):
        for s in r['_sh']:
            inv.setdefault(s, []).append(i)
    # 过滤过长 posting（模板句会产生超大 posting，先跳过这些 shingle 生成候选）
    CAP = 400
    cand_pairs = set()
    for s, ids in inv.items():
        if len(ids) > CAP:
            continue
        m = len(ids)
        for x in range(m):
            for y in range(x + 1, m):
                cand_pairs.add((ids[x], ids[y]))
    print(f'[CAND] 候选对 {len(cand_pairs)}（倒排 shingle {len(inv)}，跳过超大 posting）', flush=True)

    # 并查集
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    pairs = 0
    for i, j in cand_pairs:
        si, sj = rows[i]['_sh'], rows[j]['_sh']
        if not si or not sj:
            continue
        shared = len(si & sj)
        if shared < a.min_shared:
            continue
        jac = shared / len(si | sj)
        if jac >= a.threshold:
            union(i, j)
            pairs += 1
    print(f'[DUP ] 近似重复对 {pairs}（Jaccard ≥ {a.threshold}）', flush=True)

    # 分簇
    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    dup_clusters = {k: v for k, v in clusters.items() if len(v) > 1}
    keep, dropped = [], []
    for root, members in clusters.items():
        if len(members) == 1:
            keep.append(members[0])
            continue
        # 簇内排序：tier 优先，其次长度降序
        members.sort(key=lambda i: (rows[i]['_tier'], -rows[i]['_len']))
        keep.append(members[0])
        for i in members[1:]:
            dropped.append({
                'idx': i,
                'batch': (rows[i].get('meta') or {}).get('__batch'),
                'kind': (rows[i].get('meta') or {}).get('__kind'),
                'len': rows[i]['_len'],
                'kept_idx': members[0],
                'kept_batch': (rows[members[0]].get('meta') or {}).get('__batch'),
            })

    keep.sort()
    out_rows = []
    for i in keep:
        r = rows[i]
        for k in ('_usr', '_asst', '_len', '_tier', '_sh'):
            r.pop(k, None)
        out_rows.append(r)

    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    with open(a.dst, 'w', encoding='utf-8') as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # 报告
    def stat(rs):
        u = [len((r.get('_usr') if '_usr' in r else ''.join(m.get('content', '') for m in r['messages'] if m.get('role') == 'user'))) for r in rs]
        asst = [len(''.join(m.get('content', '') for m in r['messages'] if m.get('role') == 'assistant')) for r in rs]
        u.sort(); asst.sort()
        med = lambda x: x[len(x) // 2] if x else 0
        return {
            'n': len(rs),
            'user_med': med(u),
            'user_p95': u[int(len(u) * 0.95)] if u else 0,
            'user_lt20': sum(1 for x in u if x < 20),
            'asst_med': med(asst),
            'asst_gt3000': sum(1 for x in asst if x > 3000),
        }

    before = stat(rows)
    after = stat(out_rows)
    by_batch_before, by_batch_after = {}, {}
    for r in rows:
        b = (r.get('meta') or {}).get('__batch') or '?'
        by_batch_before[b] = by_batch_before.get(b, 0) + 1
    for r in out_rows:
        b = (r.get('meta') or {}).get('__batch') or '?'
        by_batch_after[b] = by_batch_after.get(b, 0) + 1

    report = {
        'input': a.src, 'output': a.dst,
        'threshold': a.threshold,
        'before': before, 'after': after,
        'dup_pairs': pairs,
        'clusters_total': len(clusters),
        'clusters_with_dup': len(dup_clusters),
        'dropped': len(dropped),
        'by_batch_before': by_batch_before,
        'by_batch_after': by_batch_after,
        'dropped_detail': dropped[:200],
    }
    rp = os.path.join(os.path.dirname(os.path.abspath(a.dst)), 'dedupe-report.json')
    with open(rp, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f'\n[OUT ] {a.dst}  {len(out_rows)} 条（删 {len(dropped)}）')
    print(f'      user med {before["user_med"]} → {after["user_med"]} | <20 字符 {before["user_lt20"]} → {after["user_lt20"]}')
    print(f'      asst med {before["asst_med"]} → {after["asst_med"]}')
    print(f'      批次 {by_batch_after}')
    print(f'[RPT ] {rp}')


if __name__ == '__main__':
    main()
