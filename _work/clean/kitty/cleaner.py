# -*- coding: utf-8 -*-
"""
kitty 逆向训练数据清洗器（可重跑）
输入（只读）: train/lines/9b-oxcoder/data/kitty-reverse/{5 个来源}.jsonl
              _work/rebuild/kitty-adapt/manifest.json  （工具真相源，另用 toolbox 源码交叉核对）
              train/lines/9b-oxcoder/data/eval/{val,test}/*.jsonl （泄漏参照，不训练）
输出（独占）: train/lines/9b-oxcoder/data/kitty-reverse/cleaned/clean-<src>.jsonl
              train/lines/9b-oxcoder/data/kitty-reverse/cleaned/kitty-clean-v3.jsonl
              _work/clean/kitty/stats.json
运行: C:\\ProgramData\\anaconda3\\python.exe _work/clean/kitty/cleaner.py
"""
import json, os, re, sys, io, hashlib, unicodedata, collections, time
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC_DIR = os.path.join(ROOT, 'train/lines/9b-oxcoder/data/kitty-reverse')
OUT_DIR = os.path.join(SRC_DIR, 'cleaned')
EVAL_DIR = os.path.join(ROOT, 'train/lines/9b-oxcoder/data/eval')
MANIFEST = os.path.join(ROOT, '_work/rebuild/kitty-adapt/manifest.json')
STATS = os.path.join(ROOT, '_work/clean/kitty/stats.json')

SOURCES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
           'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']

MAX_TOTAL_CHARS = 4000      # 超出即丢弃（不截断，避免半句）
MIN_NEAR_DEDUP_LEN = 80     # 短样本不做 MinHash（避免过合并）
# 近似去重口径：'combined' = 按 user+assistant 合并文本 Jaccard≥0.9（规范默认）
#                 'dual'     = 还要求 user 文本自身 Jaccard≥0.9（保留提问措辞多样性）
NEAR_MODE = os.environ.get('KITTY_NEAR_MODE', 'combined')
OUT_SUFFIX = os.environ.get('KITTY_OUT_SUFFIX', '')   # 仅影响合并文件名与分来源写出

# ---------------------------------------------------------------- manifest
MF = {m['name']: m for m in json.load(open(MANIFEST, encoding='utf-8'))}
NAMES = set(MF)

# 语义等价改写表：仅在“确知等价”时改写，其余一律删除（决策见 report §3）
TOOL_REWRITE = {'kitty_cedump': 'kitty_cpp2il'}       # 引擎转储族笔误
ACTION_REWRITE = {                                     # (tool, 错 action) -> 正 action
    ('kitty_die', 'detect'): 'scan',                   # DIE 唯一功能就是查壳
    ('kitty_frida', 'script'): 'attach',               # script 是参数，注入需 attach/spawn
    ('kitty_dnspy', 'decompile'): 'open',              # dnSpy 打开程序集即反编译
    ('kitty_fmodel', 'extract'): 'export',             # fmodel 导出=export
    ('kitty_unpack', 'extract'): 'collect',            # 收脱壳产物=collect
}

TOOL_TOKEN = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)')
# action/op 值：只吃 ASCII 安全字符（tool action 面全是 ASCII；中文括注会污染取值）
PAIR = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)\s*[`\'"]?\s*(action|op)\s*[=:]\s*[`\'"]?([A-Za-z0-9_\-|./:<>\[\]=]+)')
CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
ACK_ONLY = re.compile(r'^\s*(好的|好|明白了?|收到|了解|ok|okay|嗯+|行)[\s。.!！~]*$', re.I)
SCAFFOLD = re.compile(r'当前\s*[:：].{0,60}结果\s*[:：].{0,60}下一步\s*[:：]')


def norm(s):
    """规范化：NFC、折叠空白、小写（仅比对用）。"""
    s = unicodedata.normalize('NFC', s or '')
    return ' '.join(s.lower().split())


def sanitize(s):
    """去控制字符（保留 \n \t）、统一换行、压掉行尾空白与多余空行。"""
    s = unicodedata.normalize('NFC', s or '')
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    n_ctrl = len(CTRL.findall(s))
    s = CTRL.sub('', s)
    s = '\n'.join(line.rstrip() for line in s.split('\n'))
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s, n_ctrl


def val_of(tool, kind, raw):
    """校验单个 action/op 取值；返回 (ok, normalized_value)。多值 a/b 拆开逐个校验。"""
    meta = MF[tool]
    if raw.startswith('<') or '<' in raw:
        return True, raw            # 占位符 <pid> 之类，不判非法
    parts = [p for p in raw.split('/') if p]
    if not parts:
        return True, raw
    for p in parts:
        if kind == 'action':
            if p not in (meta.get('actions') or []):
                return False, raw
        else:
            ops = meta.get('ops') or []
            if not (('*' in ops) or (p.split('|')[0] in ops) or (p in ops)):
                return False, raw
    return True, raw


def check_and_fix(assistant):
    """工具名 + action 合法性；返回 (新文本, 未知工具集合, 非法 action 列表, 改写数)。"""
    txt = assistant
    unknown = set()
    bad_actions = []
    n_tool_fix = n_act_fix = 0

    for m in TOOL_TOKEN.finditer(txt):
        t = m.group(1)
        if t in NAMES:
            continue
        if t.endswith('_') or t.endswith('*'):       # reverse_add_* / kitty_rea_* 家族写法
            prefix = t.rstrip('_*')
            if any(n.startswith(prefix) for n in NAMES):
                continue
        if t in TOOL_REWRITE and TOOL_REWRITE[t] in NAMES:
            txt = txt.replace(t, TOOL_REWRITE[t])
            n_tool_fix += 1
            continue
        unknown.add(t)

    for m in PAIR.finditer(txt):
        tool, kind, raw = m.group(1), m.group(2), m.group(3)
        if tool not in NAMES:
            continue                                  # 已在 unknown 里单独处置
        ok, _ = val_of(tool, kind, raw)
        if ok:
            continue
        key = (tool, raw.split('/')[0])
        if key in ACTION_REWRITE:
            new = ACTION_REWRITE[key]
            old_snip = raw.replace(key[1], new, 1)
            txt = txt.replace('%s %s=%s' % (tool, kind, raw), '%s %s=%s' % (tool, kind, old_snip), 1)
            txt = txt.replace('%s %s=%s' % (tool, kind, raw), '%s %s=%s' % (tool, kind, old_snip), 1)
            n_act_fix += 1
            continue
        bad_actions.append((tool, kind, raw))

    return txt, unknown, bad_actions, n_tool_fix, n_act_fix


def informative(row):
    """去重时的保留优先级：有工具+action 对 > assistant 长 > 总长更长。"""
    asst = row['asst']
    pairs = len(PAIR.findall(asst))
    return (pairs > 0, pairs, len(asst), len(asst) + len(row['user']))


def shingles(text):
    t = norm(text)
    if len(t) < 5:
        return np.array([hash(t) & 0xFFFFFFFF], dtype=np.uint64) if t else np.zeros(0, dtype=np.uint64)
    return np.fromiter((__import__('zlib').crc32(t[i:i + 5].encode('utf-8')) for i in range(len(t) - 4)),
                       dtype=np.uint64, count=len(t) - 4)


def minhash_signature(sh, A, B, MASK, k):
    if sh.size == 0:
        return np.zeros(k, dtype=np.uint64)
    u = np.unique(sh)
    sig = (u[None, :] * A[:, None] + B[:, None]) & MASK
    return sig.min(axis=1)


def jaccard(a, b):
    if a.size == 0 or b.size == 0:
        return 0.0
    ua, ia = np.unique(a, return_index=True)
    inter = np.intersect1d(ua, np.unique(b), assume_unique=True).size
    union = ua.size + np.unique(b).size - inter
    return inter / union if union else 0.0


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    stats = collections.OrderedDict()
    drops = collections.Counter()
    drop_examples = collections.defaultdict(list)
    rewrites = collections.Counter()
    dup_examples = []

    # ---- 评测集 user 指纹（前 200 字，规范化后）
    eval_users = set()
    for split in ('val', 'test'):
        d = os.path.join(EVAL_DIR, split)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith('.jsonl'):
                continue
            for line in open(os.path.join(d, fn), encoding='utf-8'):
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                for m in (o.get('messages') or []):
                    if m.get('role') == 'user':
                        eval_users.add(norm((m.get('content') or ''))[:200])
    stats['eval_user_fingerprints'] = len(eval_users)

    # ---- 逐来源读取 + 逐条清洗
    per_src = collections.OrderedDict()
    keep = []           # dict(src, idx, user, asst, msgs, raw)
    quarantine = []
    total_in = 0
    ctrl_rows = 0

    for src in SOURCES:
        p = os.path.join(SRC_DIR, src)
        n_in = 0
        n_ok = 0
        for idx, line in enumerate(open(p, encoding='utf-8')):
            line = line.strip()
            if not line:
                continue
            n_in += 1
            total_in += 1
            try:
                o = json.loads(line)
            except Exception:
                drops['bad_json'] += 1
                continue
            msgs = o.get('messages')
            if not isinstance(msgs, list) or not msgs:
                drops['bad_structure'] += 1
                continue
            roles = [m.get('role') for m in msgs if isinstance(m, dict)]
            if not roles or roles[-1] != 'assistant' or any(r not in ('system', 'user', 'assistant') for r in roles):
                drops['bad_structure'] += 1
                if len(drop_examples['bad_structure']) < 3:
                    drop_examples['bad_structure'].append((src, idx, str(roles)[:120]))
                continue

            # --- 清洗内容
            clean_msgs = []
            n_ctrl_this = 0
            for m in msgs:
                c, nc = sanitize(m.get('content') or '')
                n_ctrl_this += nc
                clean_msgs.append({'role': m['role'], 'content': c})
            if n_ctrl_this:
                ctrl_rows += 1

            user = '\n'.join(m['content'] for m in clean_msgs if m['role'] == 'user')
            asst = '\n'.join(m['content'] for m in clean_msgs if m['role'] == 'assistant')
            if not asst:
                drops['empty_assistant'] += 1
                continue

            # --- 工具名 / action 校验（只对 assistant 动手）
            asst2, unknown, bad_act, ntf, naf = check_and_fix(asst)
            rewrites['tool_name_rewritten'] += ntf
            rewrites['action_rewritten'] += naf
            if unknown:
                drops['invalid_tool'] += 1
                if len(drop_examples['invalid_tool']) < 5:
                    drop_examples['invalid_tool'].append((src, idx, sorted(unknown)))
                quarantine.append({'src': src, 'idx': idx, 'reason': 'invalid_tool',
                                   'detail': sorted(unknown), 'messages': clean_msgs})
                continue
            if bad_act:
                drops['invalid_action'] += 1
                if len(drop_examples['invalid_action']) < 8:
                    drop_examples['invalid_action'].append((src, idx, bad_act[:4]))
                quarantine.append({'src': src, 'idx': idx, 'reason': 'invalid_action',
                                   'detail': bad_act[:6], 'messages': clean_msgs})
                continue
            if ntf or naf:
                # 改写落回 messages
                fixed = asst2
                for m in clean_msgs:
                    if m['role'] == 'assistant':
                        m['content'] = fixed
                asst = fixed

            # --- 质量过滤
            has_tool = bool(TOOL_TOKEN.search(asst))
            if len(asst.strip()) < 20 and not has_tool:
                drops['too_short_no_tool'] += 1
                continue
            if ACK_ONLY.match(asst.strip()):
                drops['ack_only'] += 1
                continue
            nu, na = norm(user), norm(asst)
            if nu and na and (na in nu or (len(na) < 200 and nu in na and len(na) - len(nu) < 40)):
                drops['restate_only'] += 1
                continue
            if '[STAGE]' in asst:
                drops['scaffold_stage'] += 1
                quarantine.append({'src': src, 'idx': idx, 'reason': 'scaffold_stage',
                                   'detail': '[STAGE]', 'messages': clean_msgs})
                continue
            if SCAFFOLD.search(asst):
                drops['scaffold_closing'] += 1
                continue
            if '[truncated]' in asst or '[truncated]' in user:
                drops['truncated_content'] += 1
                continue
            if '关键约束：同上' in asst or '关键约束:同上' in asst:
                drops['degraded_reference'] += 1
                continue

            # --- 长度
            total_len = sum(len(m['content']) for m in clean_msgs)
            if total_len > MAX_TOTAL_CHARS:
                drops['too_long'] += 1
                continue

            # --- 泄漏（eval user 前 200 字）
            if norm(user)[:200] in eval_users:
                drops['eval_leak'] += 1
                if len(drop_examples['eval_leak']) < 5:
                    drop_examples['eval_leak'].append((src, idx, user[:80]))
                quarantine.append({'src': src, 'idx': idx, 'reason': 'eval_leak',
                                   'detail': user[:80], 'messages': clean_msgs})
                continue

            # --- 格式不兼容：assistant 里带原始 <tool_call> XML（非本线 SFT 目标格式）
            if '<tool_call>' in asst:
                drops['format_incompatible'] += 1
                quarantine.append({'src': src, 'idx': idx, 'reason': 'format_incompatible',
                                   'detail': 'assistant contains raw <tool_call> block',
                                   'messages': clean_msgs})
                continue

            keep.append({'src': src, 'idx': idx, 'user': user, 'asst': asst,
                         'msgs': clean_msgs, 'raw': o})
            n_ok += 1

        per_src[src] = {'in': n_in, 'after_row_filters': n_ok}

    stats['dedup'] = {}
    n_after_filters = len(keep)

    # ---- 精确重复（跨来源 union 后去重）
    def exact_key(r):
        return hashlib.sha256((norm(r['user']) + '\x00' + norm(r['asst'])).encode('utf-8')).hexdigest()

    groups = collections.OrderedDict()
    for r in keep:
        groups.setdefault(exact_key(r), []).append(r)
    keep2 = []
    exact_removed = 0
    exact_groups = 0
    for k, g in groups.items():
        if len(g) > 1:
            exact_groups += 1
        g.sort(key=informative, reverse=True)
        keep2.append(g[0])
        for loser in g[1:]:
            exact_removed += 1
            if len(dup_examples) < 6:
                dup_examples.append({'pass': 'exact', 'kept_src': g[0]['src'], 'kept_idx': g[0]['idx'],
                                     'dropped_src': loser['src'], 'dropped_idx': loser['idx'],
                                     'user_head': loser['user'][:60]})
    stats['dedup']['exact_removed'] = exact_removed
    stats['dedup']['exact_groups'] = exact_groups

    # ---- 近似重复：MinHash + LSH（字符 5-gram，k=64 = 8 band × 8 row），Jaccard≥0.9 复核
    K, B, R = 64, 8, 8
    rng = np.random.default_rng(20261121)
    A = rng.integers(1, 2 ** 63, size=K, dtype=np.uint64) | np.uint64(1)
    Bv = rng.integers(0, 2 ** 63, size=K, dtype=np.uint64)
    MASK = np.uint64(0xFFFFFFFFFFFFFFFF)

    sh_arr = [shingles(r['user'] + '\n' + r['asst']) for r in keep2]
    sh_user = [shingles(r['user']) for r in keep2]
    near_removed = 0
    buckets = collections.defaultdict(list)
    skipping = 0
    for i, r in enumerate(keep2):
        if len(norm(r['user'] + r['asst'])) < MIN_NEAR_DEDUP_LEN:
            skipping += 1
            continue
        sig = minhash_signature(sh_arr[i], A, Bv, MASK, K)
        for b in range(B):
            buckets[(b, tuple(sig[b * R:(b + 1) * R].tolist()))].append(i)

    pairs = set()
    huge = 0
    for key, ids in buckets.items():
        if len(ids) < 2:
            continue
        if len(ids) > 400:          # 通用模板桶，跳过（记录）
            huge += 1
            continue
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                pairs.add((ids[x], ids[y]))

    parent = list(range(len(keep2)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    verified = 0
    user_jacs = []
    for i, j in pairs:
        if jaccard(sh_arr[i], sh_arr[j]) >= 0.9:
            uj = jaccard(sh_user[i], sh_user[j])
            user_jacs.append(uj)
            if NEAR_MODE == 'dual' and uj < 0.9:
                continue
            union(i, j)
            verified += 1

    clusters = collections.defaultdict(list)
    for i in range(len(keep2)):
        clusters[find(i)].append(i)
    keep3 = []
    for root, ids in clusters.items():
        if len(ids) == 1:
            keep3.append(keep2[ids[0]])
            continue
        ids.sort(key=lambda i: informative(keep2[i]), reverse=True)
        keep3.append(keep2[ids[0]])
        near_removed += len(ids) - 1
        if len(dup_examples) < 12:
            dup_examples.append({'pass': 'near', 'cluster': len(ids),
                                 'kept_src': keep2[ids[0]]['src'], 'kept_idx': keep2[ids[0]]['idx'],
                                 'dropped_src': keep2[ids[1]]['src'], 'dropped_idx': keep2[ids[1]]['idx'],
                                 'user_head': keep2[ids[1]]['user'][:60]})

    stats['dedup'].update({
        'after_exact': len(keep2), 'near_removed': near_removed, 'after_near': len(keep3),
        'near_mode': NEAR_MODE,
        'verified_pairs_with_user_jaccard_lt_0.9': sum(1 for x in user_jacs if x < 0.9),
        'verified_pairs_user_jaccard_mean': round(sum(user_jacs) / len(user_jacs), 3) if user_jacs else None,
        'lsh_params': {'k': K, 'bands': B, 'rows': R, 'shingle': 'char-5gram',
                       'jaccard_threshold': 0.9, 'min_len': MIN_NEAR_DEDUP_LEN},
        'lsh_candidate_pairs': len(pairs), 'lsh_verified_pairs': verified,
        'lsh_skipped_short': skipping, 'lsh_oversize_buckets_skipped': huge,
        'examples': dup_examples,
    })

    # ---- 写 cleaned 分来源文件（保留原始顶层字段，messages 用清洗后内容）
    by_src = collections.defaultdict(list)
    for r in keep3:
        by_src[r['src']].append(r)
    for src in SOURCES:
        rows = by_src.get(src, [])
        if OUT_SUFFIX:
            per_src[src]['out'] = len(rows)
            continue
        out_p = os.path.join(OUT_DIR, 'clean-' + src)
        with open(out_p, 'w', encoding='utf-8') as fh:
            for r in rows:
                o = dict(r['raw'])
                o['messages'] = r['msgs']
                o.setdefault('meta', {})['clean'] = {'src_file': src, 'src_line': r['idx']}
                fh.write(json.dumps(o, ensure_ascii=False) + '\n')
        per_src[src]['out'] = len(rows)

    # ---- 合并 + 统一 system（缺 system 的来源补 canonical，保证训练/推理一致）
    canonical_sys = None
    for r in keep3:
        for m in r['msgs']:
            if m['role'] == 'system' and m['content']:
                canonical_sys = m['content']
                break
        if canonical_sys:
            break
    merged_p = os.path.join(OUT_DIR, 'kitty-clean-v3%s.jsonl' % OUT_SUFFIX)
    n_sys_injected = 0
    with open(merged_p, 'w', encoding='utf-8') as fh:
        for r in sorted(keep3, key=lambda x: (SOURCES.index(x['src']), x['idx'])):
            msgs = list(r['msgs'])
            if not any(m['role'] == 'system' for m in msgs):
                msgs = [{'role': 'system', 'content': canonical_sys}] + msgs
                n_sys_injected += 1
            fh.write(json.dumps({'messages': msgs}, ensure_ascii=False) + '\n')

    # ---- 隔离区（保留证据，不进训练）
    q_p = os.path.join(OUT_DIR, '_quarantine%s.jsonl' % OUT_SUFFIX)
    with open(q_p, 'w', encoding='utf-8') as fh:
        for q in quarantine:
            fh.write(json.dumps(q, ensure_ascii=False) + '\n')

    # ---- 统计面
    def tool_dist(rows):
        c = collections.Counter()
        a = collections.Counter()
        for r in rows:
            for t in TOOL_TOKEN.findall(r['asst']):
                if t in NAMES:
                    c[t] += 1
            for m in PAIR.finditer(r['asst']):
                if m.group(1) in NAMES:
                    a['%s %s=%s' % (m.group(1), m.group(2), m.group(3))] += 1
        return c, a

    dist_all, act_all = tool_dist(keep)
    dist_fin, act_fin = tool_dist(keep3)

    def lens(rows):
        L = [len(r['user']) + len(r['asst']) for r in rows]
        L.sort()
        if not L:
            return {}
        return {'min': L[0], 'p50': L[len(L) // 2], 'p90': L[int(len(L) * .9)], 'max': L[-1],
                'mean': round(sum(L) / len(L), 1)}

    stats.update({
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'inputs': {s: per_src[s]['in'] for s in SOURCES},
        'total_in': total_in,
        'dropped_by_reason': dict(drops),
        'dropped_total': total_in - len(keep3),
        'rewrites': dict(rewrites),
        'per_source': per_src,
        'kept_before_dedup': n_after_filters,
        'final_rows': len(keep3),
        'quarantine_rows': len(quarantine),
        'system_injected_in_merged': n_sys_injected,
        'rows_with_control_chars_fixed': ctrl_rows,
        'length_all': lens(keep),
        'length_final': lens(keep3),
        'length_all_raw_chars': lens([{'user': r['user'], 'asst': r['asst']} for r in keep]),
        'tool_dist_final_top20': dist_fin.most_common(20),
        'tool_dist_all_before_dedup_top20': dist_all.most_common(20),
        'action_dist_final_top20': act_fin.most_common(20),
        'drop_examples': {k: v for k, v in drop_examples.items()},
        'elapsed_s': round(time.time() - t0, 1),
        'outputs': {'dir': os.path.relpath(OUT_DIR, ROOT), 'merged': os.path.basename(merged_p),
                    'quarantine': os.path.basename(q_p)},
    })
    json.dump(stats, open(STATS.replace('.json', OUT_SUFFIX + '.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    print('rows in          :', total_in)
    print('row filters out  :', total_in - n_after_filters, dict(drops))
    print('after exact dedup :', len(keep2), '(-%d)' % exact_removed)
    print('after near dedup  :', len(keep3), '(-%d)' % near_removed)
    print('rewrites          :', dict(rewrites))
    print('quarantine        :', len(quarantine))
    print('elapsed           : %.1fs' % (time.time() - t0))
    print('written ->', OUT_DIR)


if __name__ == '__main__':
    main()
