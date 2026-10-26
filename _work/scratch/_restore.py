p = r"D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx\run-engine.ps1"
s = open(p, encoding="utf-8-sig").read()
n = s.count("'--context-cache-policy', 'off',")
if n:
    s = s.replace("'--context-cache-policy', 'off',", "'--context-cache-policy', 'rolling',")
    open(p, "w", encoding="utf-8").write(s)
    print("RESTORED", n)
else:
    print("nothing to restore")
for i, line in enumerate(open(p, encoding="utf-8"), 1):
    if "context-cache-policy" in line: print(f"L{i}: {line.strip()}")
