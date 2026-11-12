# -*- coding: utf-8 -*-
"""patch_preflight.py — 让 preflight 与版本无关（gen4/gen5/... 通吃）"""

p = 'train/lines/_shared/scripts/preflight_gen4.py'
s = open(p, encoding='utf-8').read()
rep = []

# P1b：按「预渲染 text 集的 sha」比对（训练真正吃的是 text 文件）
old_p1b = '''    got = sha16(a.data)
    sc = open(a.script, encoding="utf-8").read() if os.path.isfile(a.script) else ""
    m = re.search(r"EXPECT_SHA=([0-9a-f]{8,64})", sc)
    exp = m.group(1) if m else ""
    check("P1b", "sha 与训练脚本一致", got.startswith(exp) and bool(exp),
          f"本地 {got} / 脚本 {exp or '缺失'}")'''
new_p1b = '''    sc = open(a.script, encoding="utf-8").read() if os.path.isfile(a.script) else ""
    m = re.search(r"EXPECT_SHA=([0-9a-f]{8,64})", sc)
    exp = m.group(1) if m else ""
    # 训练吃的是预渲染 text 集；若同名 -text.jsonl 存在，就比它，否则比原集
    text_path = a.data.replace(".jsonl", "-text.jsonl")
    cmp_path = text_path if os.path.isfile(text_path) else a.data
    got = sha16(cmp_path)
    check("P1b", "sha 与训练脚本一致", got.startswith(exp) and bool(exp),
          f"{os.path.basename(cmp_path)} {got} / 脚本 {exp or '缺失'}")'''
if old_p1b in s:
    s = s.replace(old_p1b, new_p1b)
    rep.append('P1b')

# P6：从脚本里解析 DATA/INIT/OUT，不写死 gen4 名字
old_p6 = '''    need = {"gen4-nsfw-kitty.jsonl": "DATA", "checkpoint-600": "INIT", "out/gen4": "OUT"}
    miss = [k for k in need if k not in sc]
    check("P6", "训练脚本 DATA/INIT/OUT/EXPECT_SHA 就位",
          not miss and "EXPECT_SHA=" in sc,
          f"缺 {miss}" if miss else "DATA/INIT/OUT/EXPECT_SHA 均有")'''
new_p6 = '''    keys = ("DATA=", "INIT=", "OUT=", "EXPECT_SHA=")
    miss = [k for k in keys if k not in sc]
    m_d = re.search(r"DATA=\\$\\{DATA:-\\$KDIR/data/gen2/([^}]+)\\}", sc) or \\
          re.search(r"DATA=\\$\\{DATA:-[^}]*/([^/}]+)\\}", sc)
    data_name = m_d.group(1) if m_d else "?"
    check("P6", "训练脚本 DATA/INIT/OUT/EXPECT_SHA 就位",
          not miss and data_name != "?",
          f"DATA={data_name}" + ("" if not miss else f" 缺 {miss}"))'''
if old_p6 in s:
    s = s.replace(old_p6, new_p6)
    rep.append('P6')

open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched:', rep)
