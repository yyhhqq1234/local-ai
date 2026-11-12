#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成 kitty 工具精简索引（供 eval / 部署的 system 附录使用）

为什么需要：
  40 条 RE 评测用的 system 只有 3 句话、**不含任何工具信息**，
  模型被迫靠参数记忆区分 kitty_init↔kitty_drv、kitty_ida↔kitty_ghidra 这类同族工具。
  而实际部署到 DSH 时，58 个工具的完整 JSON schema 是注入的。
  → 评测条件 ≠ 部署条件，评测低估真实能力，且这种低估是不可修复的（信息缺失）。

本脚本从 catalog 生成 58 行索引（工具名 · 一句话功能 · action 列表），
拼到 system 后面即为「部署等价口径」。

输出：train/lines/9b-oxcoder/data/kitty-reverse/_tool-index.txt
"""
import json, io, os

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(HERE, "data", "kitty-tool-catalog.json")
OUT = os.path.join(HERE, "data", "kitty-reverse", "_tool-index.txt")

HEAD = """\
可用工具索引（58 个，按名字排序）。选工具只看这张表，不要凭记忆发明名字：

"""

TAIL = """

选择纪律：
1. 一次只给一个工具调用，拿到回包再决定下一步。
2. 同族工具按上表的功能描述区分，不要凭名字相似度猜。
3. 工具名与 action 必须来自本表；表里没有的名字一律不许出现。
"""


def one_line(name, d):
    desc = " ".join(str(d.get("description") or "").split())
    acts = d.get("actions") or []
    a = ",".join(acts)
    if len(a) > 90:
        a = a[:87] + "…"
    return f"- {name}: {desc} | action: {a}"


def main():
    cat = json.load(io.open(CAT, encoding="utf-8"))
    lines = [one_line(k, v) for k, v in sorted(cat.items())]
    text = HEAD + "\n".join(lines) + TAIL
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(text)
    print(f"[OUT] {OUT}")
    print(f"  工具 {len(lines)} 个 · 索引 {len(text)} 字 ≈ {int(len(text)/1.6)} token")
    print(f"  拼到 system 后 system 总长约 {len(text)+120} 字")


if __name__ == "__main__":
    main()
