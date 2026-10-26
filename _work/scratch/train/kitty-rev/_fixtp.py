# -*- coding: utf-8 -*-
p = 'tools/gguf_to_hf.py'
s = open(p, encoding='utf-8').read()
old = '    # MTP 块（blk.64.*）—— 转换时**剔除**，不进 base\n    (r"^blk\\.(\\d+)\\.nextn\\.",                 None),   # None = 丢弃\n'
if old in s:
    s = s.replace(old, '')
    print("删除旧 nextn 规则 OK")
else:
    # 宽松匹配
    import re
    s2 = re.sub(r'[ \t]*# MTP 块[^\n]*\n[ \t]*\(r"\^blk\\\.\(\\d\+\)\\\.nextn\\\.".*?\n', '', s)
    print("宽松删除:", "OK" if s2 != s else "未命中")
    s = s2
anchor = 'RULES = [\n'
insert = ('RULES = [\n'
          '    # ★ MTP 块放最前：blk.64 除 nextn.* 外还有 attn/ffn/norm 共 11 个张量，全属 MTP 头，\n'
          '    #   HF 的 851 keys 里没有 layers.64。顺序极重要，放末尾会被常规规则先匹配掉。\n'
          '    (r"^blk\\.(?:6[4-9]|[7-9]\\d)\\.",           None),\n')
if anchor in s and 'MTP 块放最前' not in s:
    s = s.replace(anchor, insert, 1)
    print("插入 MTP 规则 OK（置于最前）")
open(p,'w',encoding='utf-8').write(s)
