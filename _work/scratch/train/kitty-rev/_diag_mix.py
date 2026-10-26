# -*- coding: utf-8 -*-
"""诊断 v5-mix 训练数据里的工具调用形态：是文本命令还是结构化 tool_calls"""
import json, re, collections
p="data/intent3/v5-mix/train.jsonl"
rows=[json.loads(l) for l in open(p,encoding="utf-8") if l.strip()]
print("rows:", len(rows))

has_tools_field = sum(1 for r in rows if "tools" in r)
print("带顶层 tools 字段的行:", has_tools_field)

role_sets = collections.Counter()
for r in rows:
    rs = tuple(sorted({m.get("role") for m in r.get("messages",[])}))
    role_sets[rs]+=1
print("role 组合分布:", dict(role_sets))

# assistant 文本里出现的 kitty 工具名
TOOL = re.compile(r"\bkitty_[a-z0-9_]+")
cnt = collections.Counter()
lines_with_tool = 0
lines_total = 0
for r in rows:
    for m in r.get("messages",[]):
        if m.get("role")!="assistant": continue
        c = m.get("content") or ""
        lines_total += 1
        names = TOOL.findall(c)
        if names: lines_with_tool += 1
        for n in names: cnt[n]+=1
print(f"\nassistant 消息 {lines_total} 条，其中含 kitty_* 工具名 {lines_with_tool} 条 ({lines_with_tool/max(1,lines_total)*100:.1f}%)")
print(f"不同工具名 {len(cnt)} 个，Top 25:")
for n,c in cnt.most_common(25):
    print(f"  {n:<32} {c}")
print("\n判分器关心的三个工具是否出现：")
for t in ("kitty_jadx","kitty_rea_trace","kitty_ops","kitty_x64dbg","kitty_ida"):
    print(f"  {t:<20} {cnt.get(t,0)}")
