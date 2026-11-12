import json

d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", encoding="utf-8"))

out = []
out.append("=== state terms ===")
for k in d["state"]["terms"]:
    info = d["state"]["terms"][k]
    cr = f" [cross: {info['cross_ref']}]" if "cross_ref" in info else ""
    out.append(f"  {k}{cr}")

out.append("\n=== descriptor terms ===")
for k in d["descriptor"]["terms"]:
    info = d["descriptor"]["terms"][k]
    cr = f" [cross: {info['cross_ref']}]" if "cross_ref" in info else ""
    out.append(f"  {k}{cr}")

out.append("\n=== personality terms ===")
for k in d["personality"]["terms"]:
    info = d["personality"]["terms"][k]
    cr = f" [cross: {info['cross_ref']}]" if "cross_ref" in info else ""
    out.append(f"  {k}{cr}")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\check_v6b.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
