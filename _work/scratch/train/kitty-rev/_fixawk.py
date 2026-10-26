import sys
p = r"D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev\deploy\v6_s5_fetch.ps1"
s = open(p, encoding="utf-8-sig").read()
old = r"awk '{print \$1}'"
new = "cut -d' ' -f1"
n = s.count(old)
print("found =", n)
if n:
    s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
    print("REPLACED", n)
else:
    print("NOT FOUND")
# 打印改后的行
for i, line in enumerate(open(p, encoding="utf-8"), 1):
    if "rmd5line" in line:
        print(f"L{i}: {line.strip()}")
