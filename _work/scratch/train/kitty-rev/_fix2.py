p = "tools/gen_v61_nonkitty.py"
s = open(p, encoding="utf-8").read()
s = s.replace('                    "nonkitty_cat": cat,\n', '')
s = s.replace('                "meta": {\n                    # 只保留与其余 1189 行完全一致的三个键：\n                    # 多出 nonkitty_cat / expect_tool_calls 会让 load_dataset 推断 schema 时冲突\n                    "kind": "text",\n                    "src": "v61-nonkitty",\n                    "cat": "kb-re",\n                },',
              '                "meta": {\n                    # 只保留与其余 1189 行完全一致的键（kind/src/cat）\n                    # 任何多出的键（nonkitty_cat / expect_tool_calls）都会让 load_dataset 推断 schema 冲突\n                    "kind": "text",\n                    "src": "v61-nonkitty",\n                    "cat": "kb-re",\n                },')
open(p,"w",encoding="utf-8").write(s)
print("改完")
