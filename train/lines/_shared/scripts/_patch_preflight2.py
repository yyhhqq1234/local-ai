# -*- coding: utf-8 -*-
"""patch_preflight2.py — P1b 改成「按训练脚本里 DATA 指向的文件」比对 sha"""

p = 'train/lines/_shared/scripts/preflight_gen4.py'
s = open(p, encoding='utf-8').read()

old = '''    sc = open(a.script, encoding="utf-8").read() if os.path.isfile(a.script) else ""
    m = re.search(r"EXPECT_SHA=([0-9a-f]{8,64})", sc)
    exp = m.group(1) if m else ""
    # 训练吃的是预渲染 text 集；若同名 -text.jsonl 存在，就比它，否则比原集
    text_path = a.data.replace(".jsonl", "-text.jsonl")
    cmp_path = text_path if os.path.isfile(text_path) else a.data
    got = sha16(cmp_path)
    check("P1b", "sha 与训练脚本一致", got.startswith(exp) and bool(exp),
          f"{os.path.basename(cmp_path)} {got} / 脚本 {exp or '缺失'}")'''

new = '''    sc = open(a.script, encoding="utf-8").read() if os.path.isfile(a.script) else ""
    m = re.search(r"EXPECT_SHA=([0-9a-f]{8,64})", sc)
    exp = m.group(1) if m else ""
    # 训练真正吃的是脚本里 DATA 指向的文件（通常是预渲染的 *-text.jsonl）
    m_d = re.search(r"DATA=\\$\\{DATA:-[^}]*/([^/}]+)\\}", sc)
    train_name = m_d.group(1) if m_d else os.path.basename(a.data)
    cand = [os.path.join(os.path.dirname(a.data), train_name), a.data]
    cmp_path = next((c for c in cand if os.path.isfile(c)), a.data)
    got = sha16(cmp_path)
    check("P1b", "训练脚本 DATA 的 sha 与 EXPECT_SHA 一致",
          got.startswith(exp) and bool(exp),
          f"{os.path.basename(cmp_path)} {got} / 脚本 {exp or '缺失'}")'''

assert old in s, 'P1b anchor missing'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('P1b patched')
