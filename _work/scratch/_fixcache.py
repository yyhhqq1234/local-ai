p = r"D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx\run-engine.ps1"
s = open(p, encoding="utf-8-sig").read()
old = "'--context-cache-policy', 'rolling',"
new = "'--context-cache-policy', 'off',"
n = s.count(old)
print("found =", n)
if n:
    s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
    print("REPLACED", n)
else:
    import re
    s2 = re.sub(r"(--context-cache-policy'\s*,\s*)'rolling'", r"\1'off'", s)
    print("regex:", "OK" if s2 != s else "FAIL")
    if s2 != s:
        open(p, "w", encoding="utf-8").write(s2)
for i, line in enumerate(open(p, encoding="utf-8"), 1):
    if "context-cache-policy" in line:
        print(f"L{i}: {line.strip()}")
