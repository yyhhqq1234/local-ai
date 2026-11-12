import io

P = r"D:\BaiduNetdiskDownload\Local-AI\AGENTS.md"
BT = chr(96)

s = io.open(P, encoding="utf-8").read()
lines = s.split("\n")
out = []
i = 0
n = len(lines)
while i < n:
    l = lines[i]
    if l.startswith(BT + "README.md" + BT + "（总览）"):
        out.append(BT + "README.md" + BT + "（总览）· " + BT + "docs/architecture.md" + BT + "（架构 / 适配器 / 优化日志）·")
        out.append(BT + "docs/training.md" + BT + "（后训练）· " + BT + "docs/operations.md" + BT + "（运维与联动）· " + BT + "docs/plans.md" + BT + "（两条线计划）·")
        out.append(BT + "plugins/dsh-local-ai/PATCHES.md" + BT)
        # 跳过原来的后续两行
        i += 3
        continue
    out.append(l)
    i += 1

io.open(P, "w", encoding="utf-8").write("\n".join(out))
print("index block rewritten")
