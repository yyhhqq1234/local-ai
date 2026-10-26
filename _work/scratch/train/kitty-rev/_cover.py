# -*- coding: utf-8 -*-
"""查 v6 训练数据对现在仅剩的三道 FAIL 题的覆盖：
   题8 error-recovery / 题10 real-trajectory / 题22 real-trajectory"""
import json, re
rows = [json.loads(l) for l in open("data/intent3/v6-mix/train.final.jsonl", encoding="utf-8") if l.strip()]
print(f"总 {len(rows)} 条")

# ① error-recovery：轨迹里有没有 ERR| 回包（模型能从错误中学到纠错）
err_rows = []
for r in rows:
    for m in r["messages"]:
        if m.get("role") == "tool" and "ERR|" in (m.get("content") or ""):
            err_rows.append(r); break
print(f"\n① 含 ERR| 错误回包的样本: {len(err_rows)} 条")
# 细分错误类型
kinds = {}
for r in err_rows:
    for m in r["messages"]:
        if m.get("role") == "tool":
            c = m.get("content") or ""
            if "ERR|" in c:
                k = c.split("|")[1][:20] if "|" in c else c[:20]
                kinds[k] = kinds.get(k, 0) + 1
for k, v in sorted(kinds.items(), key=lambda x: -x[1])[:10]:
    print(f"   {k:<28} {v}")

# ② 多步轨迹：assistant 消息数（=轮数）
multi = [r for r in rows if sum(1 for m in r["messages"] if m.get("role")=="assistant") >= 3]
print(f"\n② ≥3 步的多轮轨迹: {len(multi)} 条")

# ③ 题10/22 的特征：普通电脑任务纯文本（不该调工具）
text_no_tool = [r for r in rows if (r.get("meta") or {}).get("kind") == "text"
                and not any(m.get("tool_calls") for m in r["messages"])]
print(f"\n③ text 类且无 tool_call（示范「不调工具」）: {len(text_no_tool)} 条")
# 其中有多少是「普通电脑任务」而非 kitty/NSFW
kitty_kw = re.compile("kitty|逆向|PE|APK|内存|调试|脱壳|固件|IDB|x64dbg")
ordinary = 0
for r in text_no_tool:
    u = next((m.get("content") or "" for m in r["messages"] if m.get("role")=="user"), "")
    if not kitty_kw.search(u): ordinary += 1
print(f"   其中不含 kitty/逆向关键词的「普通任务」: {ordinary} 条")

# ④ 抽样看 3 条 error-recovery 的形态
print("\n④ error-recovery 样本抽样（前 2 条，只看结构不看内容）:")
for r in err_rows[:2]:
    roles = [(m.get("role"), "ERR" if "ERR|" in (m.get("content") or "") else "") for m in r["messages"]]
    print("   ", roles)
