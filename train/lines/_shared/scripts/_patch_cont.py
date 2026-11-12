# -*- coding: utf-8 -*-
"""patch_cont_v2.py —— 一次性修 build_cont_pos.py（写成文件跑，避免 heredoc 传参问题）"""

p = 'train/lines/_shared/scripts/build_cont_pos.py'
s = open(p, encoding='utf-8').read()
orig = len(s)
report = []

# 1) 去掉结构性标记「（上文）」：格式串会自然变成 %s\n\n%s%s
if '（上文）' in s:
    s = s.replace('（上文）', '')
    report.append('removed （上文）')

# 2) 提示语改自然句
if '接着写下去。' in s:
    s = s.replace('接着写下去。', '接着这段写下去。')
    report.append('TAIL_ASK reworded')

# 3) 新增 --max-rep
if '--max-rep' not in s:
    s = s.replace('    a = ap.parse_args()',
                  '    ap.add_argument("--max-rep", type=float, default=0.30,\n'
                  '                    help="assistant 8-gram 重复率上限（C19 复读门禁）")\n'
                  '    a = ap.parse_args()')
    report.append('added --max-rep')

# 4) 逐行复读 / 回声过滤
anchor = ('        if tail[0] in BAD_HEAD:\n'
          '            st["tail_head"] += 1\n'
          '            continue')
if 'tail_repetitive' not in s:
    add = anchor + '''
        flat = re.sub(r"\\s+", "", tail)
        if len(flat) > 60:
            grams = [flat[i:i + 8] for i in range(len(flat) - 7)]
            rep = 1 - len(set(grams)) / len(grams)
            if rep > a.max_rep:
                st["tail_repetitive"] += 1
                continue
            if flat[:20] in re.sub(r"\\s+", "", head)[-80:]:
                st["tail_echo"] += 1
                continue'''
    assert anchor in s, 'anchor missing'
    s = s.replace(anchor, add)
    report.append('added rep/echo filters')

open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('delta bytes:', len(s) - orig)
print('changes:', report)
