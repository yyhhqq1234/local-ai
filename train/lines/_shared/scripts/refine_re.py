#!/usr/bin/env python
"""refine_re.py — final-re 结构优化（silver 降权 + 短指令处理）

解决的问题（来自评估）：
  ② qc-silver 1156 条（42.7%）短答，把 assistant 中位压到 208
  ③ user <20 字符 924 条（34.1%），训不出「读懂带上下文的复杂求助」

策略：
  A) qc-silver 降权
     · 保留 assistant ≥ 300 字符的 silver（有过程，不是纯结论）
     · assistant < 300 的按 keep_ratio 抽样（默认 0.25）
     · 目标：silver 占比 ≤ 25%

  B) 短指令处理（分两类，区别对待）
     · batch=silver 且 user<20 → 直接丢（silver 已在降权，短指令无上下文价值）
     · 其他 batch 且 user<20 → 补上下文三件套（保留样本，改写 user）
       三件套 = 我手上是什么 + 已经试过什么 + 具体卡在哪
       上下文从 assistant 里提取真实要素（工具名/OP/判据词），不编造

  C) 长样本标记
     assistant > 3000 字符的加 meta.__long=true（训练侧可单独处理，不删）

输出：final-re-refined.jsonl + refine-report.json（含改写样本明细，可回滚）

用法:
  python refine_re.py --in train/data/final-re-dedup.jsonl --out train/data/final-re-refined.jsonl
"""
import argparse
import json
import os
import random
import re

TOOL_RE = re.compile(r'\b(kitty_[a-z0-9_]+|reverse_[a-z_]+)\b')
OP_RE = re.compile(r'\b(PING|OPEN|CUR|MODENUM|MODBASE|S_NEW|S_GET|S_NEXT|S_SNAP|S_CHANGED|S_UNCHANGED|P_BACK|P_WALK|KM_[A-Z]+|DBG_[A-Z_]+|AL_[A-Z_]+|CT_[A-Z]+)\b')

# 短指令场景化改写：不编造内容，只把 assistant 里已有的要素搬到问题里
# 10 种模板轮换（防止改写本身引入新的模板重复）
CTX_TEMPLATES = [
    '我在做一个逆向任务，手上对象是 {obj}。{tried}现在卡在 {point}，帮我理一下。',
    '实测环境：{obj} 已经挂着，前面试过 {tried_short}。现在 {point} 这块不确定，怎么走？',
    '{obj} 的分析做到一半，{point} 这里对不上。我之前的做法是 {tried_short}，哪里有问题？',
    '情况是这样：{obj}，我用 {tried_short} 走了一遍，结果 {point} 不符合预期。下一步该怎么判断？',
    '帮我确认一件事 —— {obj}，{tried}。现在要处理 {point}，按工作台的规矩应该怎么走？',
    '队友交接给我的状态：{obj}，{tried_short} 已经做过，剩下 {point} 没搞定。给我一条能落地的路径。',
    '我在 {obj} 上遇到问题。已知：{tried_short}。卡点：{point}。要把这一步走通需要什么？',
    '实测记录：对象 {obj}，{tried}，但 {point} 的结果和预期不一致。这是为什么，怎么修？',
    '{obj}，前面 {tried_short}，现在到了 {point} 这一步。这里容易出什么错，怎么避？',
    '接手一个半成品：{obj}，{tried_short}。接下来 {point} 该怎么处理才不出问题？',
]


def trim(s, n):
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:n]


def make_context(row):
    """从 assistant 里提取真实要素，拼成上下文三件套"""
    asst = ''.join(m.get('content', '') for m in row['messages'] if m.get('role') == 'assistant')
    usr = ''.join(m.get('content', '') for m in row['messages'] if m.get('role') == 'user')

    tools = TOOL_RE.findall(asst)
    ops = OP_RE.findall(asst)
    obj = ('目标进程 kitty-target.exe' if 'kitty-target' in asst
           else '一个 PE 样本' if ('.exe' in asst or '.dll' in asst)
           else '当前挂着的目标进程')

    # 已试过什么：取 assistant 里出现的第一个命令式工具/OP
    if tools:
        tried = '调过 ' + tools[0]
    elif ops:
        tried = '发过 ' + ops[0]
    else:
        tried = '按常规流程走过一遍'

    # 卡点：优先用原 user 的意图，其次用 assistant 首句
    point = trim(usr, 40) if usr else trim(asst.split('。')[0], 40)
    point = point or '这一步的判据'

    tpl = random.choice(CTX_TEMPLATES)
    new_user = tpl.format(obj=obj, tried=tried + '，', tried_short=tried, point=point)
    return new_user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', default='train/data/final-re-dedup.jsonl')
    ap.add_argument('--out', dest='dst', default='train/data/final-re-refined.jsonl')
    ap.add_argument('--silver-keep', type=float, default=0.25, help='assistant<300 的 silver 保留比例')
    ap.add_argument('--silver-min-asst', type=int, default=300)
    ap.add_argument('--short-user', type=int, default=20)
    ap.add_argument('--long-asst', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1337)
    a = ap.parse_args()
    random.seed(a.seed)

    rows = []
    for line in open(a.src, encoding='utf-8'):
        line = line.strip()
        if line:
            rows.append(json.loads(line))

    out, stats = [], {
        'input': len(rows), 'dropped_silver_short': 0, 'dropped_silver_ratio': 0,
        'kept_silver_long': 0, 'rewritten_user': 0, 'long_flagged': 0,
        'by_batch_after': {},
    }
    rewrites = []

    for r in rows:
        msgs = r['messages']
        batch = (r.get('meta') or {}).get('__batch') or '?'
        asst = ''.join(m.get('content', '') for m in msgs if m.get('role') == 'assistant')
        usr = ''.join(m.get('content', '') for m in msgs if m.get('role') == 'user')

        # A) silver 降权
        if batch == 'qc-silver':
            if len(asst) >= a.silver_min_asst:
                stats['kept_silver_long'] += 1
            else:
                if random.random() > a.silver_keep:
                    stats['dropped_silver_ratio'] += 1
                    continue
                if len(usr) < a.short_user:
                    stats['dropped_silver_short'] += 1
                    continue

        # B) 短指令改写（非 silver）
        if batch != 'qc-silver' and len(usr) < a.short_user:
            new_user = make_context(r)
            if len(new_user) > len(usr) + 10:
                for m in msgs:
                    if m.get('role') == 'user':
                        m['content'] = new_user
                        break
                stats['rewritten_user'] += 1
                if len(rewrites) < 40:
                    rewrites.append({'batch': batch, 'old': usr[:80], 'new': new_user[:160]})

        # C) 长样本标记
        if len(asst) > a.long_asst:
            r.setdefault('meta', {})['__long'] = True
            stats['long_flagged'] += 1

        out.append(r)
        stats['by_batch_after'][batch] = stats['by_batch_after'].get(batch, 0) + 1

    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    with open(a.dst, 'w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    # 统计对比
    def stat(rs):
        u, s = [], []
        for r in rs:
            u.append(len(''.join(m.get('content', '') for m in r['messages'] if m.get('role') == 'user')))
            s.append(len(''.join(m.get('content', '') for m in r['messages'] if m.get('role') == 'assistant')))
        u.sort(); s.sort()
        med = lambda x: x[len(x) // 2] if x else 0
        return {'n': len(rs), 'user_med': med(u), 'user_lt20': sum(1 for x in u if x < 20),
                'user_p95': u[int(len(u) * 0.95)] if u else 0, 'asst_med': med(s)}

    stats['before'] = stat(rows)
    stats['after'] = stat(out)
    stats['rewrite_samples'] = rewrites

    rp = os.path.join(os.path.dirname(os.path.abspath(a.dst)), 'refine-report.json')
    with open(rp, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    b, af = stats['before'], stats['after']
    print(f'[IN ] {b["n"]} 条   user med {b["user_med"]}  <20 {b["user_lt20"]}  asst med {b["asst_med"]}')
    print(f'[OUT] {af["n"]} 条   user med {af["user_med"]}  <20 {af["user_lt20"]}  asst med {af["asst_med"]}')
    print(f'      silver: 保留长答 {stats["kept_silver_long"]} · 按比例删 {stats["dropped_silver_ratio"]} · 删短指令 {stats["dropped_silver_short"]}')
    print(f'      短指令改写 {stats["rewritten_user"]} 条 · 长样本标记 {stats["long_flagged"]} 条')
    print(f'      批次 {stats["by_batch_after"]}')
    print(f'[RPT ] {rp}')


if __name__ == '__main__':
    main()
