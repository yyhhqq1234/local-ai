# -*- coding: utf-8 -*-
"""最终验证 v3：短响应 + 回声 + 低覆盖率文件确认"""
import json, os, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
V3 = os.path.join(BASE, "train", "data", "nsfw-v3.jsonl")
COV = os.path.join(BASE, "train", "data", "nsfw-v3-coverage.json")

# 1) 总条数
n = 0
short = []
echo = 0
cont_n = 0
with open(V3, encoding="utf-8") as f:
    for line in f:
        n += 1
        r = json.loads(line)
        a = r["messages"][-1]["content"]
        if len(a) < 50:
            short.append((r["meta"]["__src"], r["meta"]["win"], len(a)))
        if r["meta"]["stype"] == "cont":
            cont_n += 1
            u = r["messages"][0]["content"]
            tail = u[-100:]
            if tail and tail in a[:200]:
                echo += 1

print(f"[TOTAL] {n} samples")
print(f"[SHORT] {len(short)} (<50 chars)")
if short:
    print(f"  top: {short[:5]}")
print(f"[ECHO ] {echo}/{cont_n} ({echo/max(cont_n,1)*100:.2f}%)")

# 2) 覆盖率报告
with open(COV, encoding="utf-8") as f:
    cov = json.load(f)
print(f"\n[COV  ] files={cov['files_indexed']} samples={cov['samples']}")
print(f"       src_full={cov['src_chars_full']:,} used={cov['used_chars']:,}")
print(f"       coverage_full={cov['coverage_of_full']:.4f}")
print(f"       minor_flag={cov['minor_flag_samples']} ({cov['minor_flag_ratio']*100:.1f}%)")
print(f"       types={cov['sample_types']}")
print(f"       ip_fanfic={cov['ip_fanfic_samples']}")

# 3) 之前低覆盖率的 5 个文件确认
low_files = [
    "mc/VRMMO/NSFW小说/关于在VRMMO中遇到一个非常漂亮的角色.md",
    "mc/VRMMO/NSFW小说/在VRMMO中遇到一个非常漂亮的角色.md",
]
for pf in cov["per_file"]:
    if "VRMMO" in pf["rel"] or "漂亮" in pf["rel"]:
        print(f"\n[LOW  ] {pf['rel'][:60]}")
        print(f"         src={pf['src_chars']:,} used={pf['used_chars']:,} cov={pf['coverage']}")

# 4) 抽 2 条样本看结构
print("\n=== 2 sample previews ===")
with open(V3, encoding="utf-8") as f:
    for i in range(2):
        r = json.loads(next(f))
        print(f"  [{r['meta']['stype']}] user={r['messages'][0]['content'][:80]}...")
        print(f"           assistant={r['messages'][-1]['content'][:60]}... ({len(r['messages'][-1]['content'])} chars)")
