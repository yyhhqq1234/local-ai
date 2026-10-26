p = r"D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx\run-engine.ps1"
s = open(p, encoding="utf-8").read()
old1 = "    '--draft-tokens', [string]$DraftTokens,\r\n"
old2 = "    '--draft-tokens', [string]$DraftTokens,\n"
n = s.count(old1) + s.count(old2)
s = s.replace(old1, "").replace(old2, "")
open(p, "w", encoding="utf-8").write(s)
print("removed --draft-tokens:", n)
