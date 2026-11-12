p = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\eval\eval_kitty_v6.py"
s = open(p, encoding="utf-8").read()
old = '''            user = row["messages"][0]["content"]'''
new = '''            user = row["messages"][0]["content"]
            # 去缓存：引擎 context cache 按 prompt 命中，同 prompt 会重放同一响应
            # 加一个 HTML 注释形式的轮次标记，语义不变但 prompt 字节不同 → 缓存失效
            if rp > 0:
                user = user + f"\\n<!-- round{rp + 1} -->"'''
n = s.count(old)
print("found =", n)
if n == 1:
    s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
    print("PATCHED")
else:
    print("SKIP: count != 1")
