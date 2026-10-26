p = r"D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx\run-engine.ps1"
import shutil, os
bak = p + ".bak-spec"
if not os.path.exists(bak):
    shutil.copy2(p, bak)
s = open(p, encoding="utf-8-sig").read()
old = "    '--spec', 'mtp',\r\n"
old2 = "    '--spec', 'mtp',\n"
n = s.count(old) + s.count(old2)
s = s.replace(old, "").replace(old2, "")
open(p, "w", encoding="utf-8").write(s)
print("removed --spec mtp:", n)
for i, line in enumerate(open(p, encoding="utf-8"), 1):
    if "spec" in line and "--" in line:
        print(f"L{i}: {line.strip()}")
