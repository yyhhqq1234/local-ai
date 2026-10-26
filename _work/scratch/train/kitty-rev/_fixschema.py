# -*- coding: utf-8 -*-
"""修 schema 冲突：nonkitty 的 meta 只保留 kind/cat/src（与其他行一致）"""
p = "tools/gen_v61_nonkitty.py"
s = open(p, encoding="utf-8").read()
old = '''                "meta": {
                    "kind": "text",
                    "src": "v61-nonkitty",
                    "cat": "kb-re",          # 归到 non-kitty 知识类，与 eval 的 real-trajectory 同类
                    "nonkitty_cat": cat,
                    "expect_tool_calls": 0,
                },'''
new = '''                "meta": {
                    # 只保留与其余 1189 行完全一致的三个键：
                    # 多出 nonkitty_cat / expect_tool_calls 会让 load_dataset 推断 schema 时冲突
                    "kind": "text",
                    "src": "v61-nonkitty",
                    "cat": "kb-re",
                    "nonkitty_cat": cat,
                },'''
if old in s:
    s = s.replace(old, new); print("替换 meta 块 OK")
else:
    import re
    s2 = re.sub(r'"expect_tool_calls": 0,\s*\n', '', s)
    print("宽松删除 expect_tool_calls:", "OK" if s2 != s else "未命中")
    s = s2
open(p, "w", encoding="utf-8").write(s)
