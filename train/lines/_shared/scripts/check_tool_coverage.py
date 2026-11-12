"""工具覆盖核查 —— 修正版（兼容 kitty_ 与 reverse_ 双前缀）

原临时脚本只用 `kitty_[a-z0-9_]+`，把 6 个 reverse_* 工具误判为 0 覆盖。
本脚本同时支持两种前缀，并对粘连做最长前缀归一。

用法：
  python check_tool_coverage.py train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl
  python check_tool_coverage.py <文件> --low 50
"""
import argparse
import collections
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(TRAIN_ROOT, "data", "kitty-reverse", "kitty-contracts", "tools.json")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from toolname import extract as _extract   # noqa: E402


def load_tools():
    with open(CONTRACT, encoding="utf-8") as f:
        return {t["name"] for t in json.load(f) if isinstance(t, dict) and t.get("name")}


def norm(raw_set, tools):
    out = set()
    for tok in raw_set:
        if tok in tools:
            out.add(tok)
            continue
        pref = [k for k in tools if tok.startswith(k)]
        out.add(max(pref, key=len) if pref else tok)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--low", type=int, default=50, help="低于此值算低覆盖")
    args = ap.parse_args()

    tools = load_tools()
    print("工具总数 = %d（kitty_ 前缀 %d + reverse_ 前缀 %d）"
          % (len(tools),
             sum(1 for t in tools if t.startswith("kitty_")),
             sum(1 for t in tools if t.startswith("reverse_"))))
    print()

    for path in args.files:
        if not os.path.isfile(path):
            print("[SKIP] %s 不存在" % path)
            continue
        cnt = collections.Counter()
        n = 0
        fake = collections.Counter()
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                n += 1
                o = json.loads(line)
                a = next((m["content"] for m in o.get("messages") or []
                          if m.get("role") == "assistant"), "")
                hit, fk = _extract(a, tools)
                for t in hit:
                    cnt[t] += 1
                for t in fk:
                    fake[t] += 1
        zero = [t for t in tools if cnt.get(t, 0) == 0]
        low = [t for t in tools if 0 < cnt.get(t, 0) < args.low]
        print("=" * 74)
        print("%s" % path)
        print("  样本 %d | 覆盖 %d/%d | 0 覆盖 %d | <%d 覆盖 %d | 编造类 %d"
              % (n, len(cnt), len(tools), len(zero), args.low, len(low), len(fake)))
        if zero:
            print("  0 覆盖：" + ", ".join(sorted(zero)))
        if fake:
            print("  非白名单（前 10）：" + ", ".join(k for k, _ in fake.most_common(10)))
        print()


if __name__ == "__main__":
    main()
