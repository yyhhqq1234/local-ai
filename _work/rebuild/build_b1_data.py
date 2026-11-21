# -*- coding: utf-8 -*-
"""B1 数据构建：kitty 逆向工作台 + NSFW（露骨加权）+ 普通对话，三路混配

输出: train/lines/9b-oxcoder/data/b1-combined/train-b1.jsonl
配比（按条数，目标 约 1 : 1 : 1）：
  kitty   train-kitty-v3-clean.jsonl（28.5MB，主力）+ v6-fix + v7-direct-answer
  nsfw    train-2b-gated-v5.jsonl；assistant 含露骨词的样本 ×2 复制（加权）
  general 从 nsfw-gated 的 gate-neg（常规模式问答）抽 + kitty 里的短问答
"""
import io, json, os, random, sys

ROOT = 'D:/BaiduNetdiskDownload/Local-AI'
L9 = ROOT + '/train/lines/9b-oxcoder'
OUT_DIR = L9 + '/data/b1-combined'
OUT = OUT_DIR + '/train-b1.jsonl'
sys.path.insert(0, ROOT + '/train/lines/_shared/scripts')
import nsfw_gate_eval as M
strict = M.load_terms(strict=True)

def read_jsonl(p, limit=None):
    rows = []
    if not os.path.exists(p):
        print('  [miss]', os.path.basename(p))
        return rows
    with io.open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            msgs = o.get('messages')
            if not msgs:
                # 兼容 instruction/output
                if o.get('instruction') and o.get('output'):
                    msgs = [{'role': 'user', 'content': o['instruction']},
                            {'role': 'assistant', 'content': o['output']}]
                else:
                    continue
            if not any(m.get('role') == 'assistant' for m in msgs):
                continue
            rows.append({'messages': msgs})
            if limit and len(rows) >= limit:
                break
    return rows

def nsfw_pick(n_target_each=6000):
    """成对门控集：许可分支（含露骨加权）/ 常规分支（作普通对话）"""
    p = L9 + '/data/nsfw-gated/train-2b-gated-v5.jsonl'
    pos, neg = [], []
    with io.open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            msgs = o.get('messages')
            if not msgs:
                continue
            sysm = next((m.get('content') for m in msgs if m.get('role') == 'system'), '')
            asst = next((m.get('content') for m in msgs if m.get('role') == 'assistant'), '')
            if isinstance(sysm, list):
                sysm = ''.join(x.get('text', '') for x in sysm)
            if isinstance(asst, list):
                asst = ''.join(x.get('text', '') for x in asst)
            is_perm = '许可' in sysm
            explicit = any(w in asst for w in strict)
            row = {'messages': msgs}
            if is_perm:
                pos.append((row, explicit))
            else:
                neg.append(row)
    # 露骨样本加权：先取全部露骨，再按数量补非露骨许可样本
    exp = [r for r, e in pos if e]
    non = [r for r, e in pos if not e]
    random.shuffle(exp); random.shuffle(non)
    picked = exp[:n_target_each // 2] * 2 + non[:n_target_each // 2]
    random.shuffle(picked)
    return picked, neg[:3000], len(exp), len(non)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    random.seed(20261120)
    print('[1/3] kitty 逆向工作台（核心轨迹 + 更新后工具面 v2）')
    kitty = []
    for f, lim in [('train-kitty-v3-clean.jsonl', 6000),
                   ('kitty-v6-fix.jsonl', None),
                   ('kitty-v7-direct-answer.jsonl', None),
                   ('kitty-v5-strong.jsonl', 500)]:
        part = read_jsonl(L9 + '/data/kitty-reverse/' + f, lim)
        print(f'  {f}: {len(part)}')
        kitty += part
    # 更新后的工具面（2026-11-18 版 kitty-toolbox）：加权 ×12，让新 action/参数面占住分布
    adapt = read_jsonl(L9 + '/data/kitty-reverse/kitty-adapt-v2.jsonl')
    print(f'  kitty-adapt-v2.jsonl: {len(adapt)} ×12 = {len(adapt) * 12}')
    kitty += adapt * 12
    random.shuffle(kitty)
    print('[2/3] NSFW（露骨加权 ×2）')
    nsfw, neg, n_exp, n_non = nsfw_pick()
    print(f'  许可分支 {len(nsfw)}（露骨源 {n_exp} / 非露骨源 {n_non}）；常规分支 {len(neg)}')
    print('[3/4] DSH 适配（身份/格式/工具协议/结果续跑/门控）')
    dsh = read_jsonl(L9 + '/data/dsh-adapt/train-dsh.jsonl')
    dsh = dsh * 2   # 1909 → 3818，保证在总分布里占 ~20%
    print(f'  train-dsh.jsonl: 1909 ×2 = {len(dsh)}')
    print('[4/4] 混配')
    n = min(len(kitty), len(nsfw))
    data = kitty[:n] + nsfw[:n] + dsh[:n] + neg[:max(1500, n // 4)]
    random.shuffle(data)
    with io.open(OUT, 'w', encoding='utf-8') as fh:
        for r in data:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    # 统计
    exp_line = 0
    for r in data:
        a = next((m.get('content') for m in r['messages'] if m.get('role') == 'assistant'), '')
        if isinstance(a, list):
            a = ''.join(x.get('text', '') for x in a)
        if any(w in a for w in strict):
            exp_line += 1
    print(f'[out] {OUT}')
    print(f'      rows={len(data)}  露骨 assistant 行={exp_line} ({exp_line/max(1,len(data))*100:.1f}%)  '
          f'kitty={n} nsfw={min(n,len(nsfw))} general={max(1500, n//4)}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
