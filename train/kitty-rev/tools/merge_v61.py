# -*- coding: utf-8 -*-
"""V6.1 数据集合并 + dictargs 转换 + 全量校验

输入：
  data/intent3/v6-mix/train.final.jsonl   1189 条（V6 本体 + reviewer-v5b 的 extra-14）
  data/intent3/v6-mix/nonkitty.jsonl        54 条（本次新造「普通任务不调工具」）
输出：
  data/intent3/v6-mix/v61-mix.jsonl             1243 条（原样，arguments 仍是 str）
  data/intent3/v6-mix/v61-mix.dictargs.jsonl    1243 条（arguments 已转 dict，训练用这个）

为什么要两份：
  chat_template 用 tool_call.arguments|items 要 mapping，
  但数据源按 OpenAI 标准存字符串 → 训练前必须转 dict（V6 踩过，训练在渲染阶段崩）
"""
import json, os, hashlib
from collections import Counter

SRC = [
    ("data/intent3/v6-mix/train.final.jsonl", 1189),
    ("data/intent3/v6-mix/nonkitty.jsonl", 54),
]
OUT_RAW = "data/intent3/v6-mix/v61-mix.jsonl"
OUT_DICT = "data/intent3/v6-mix/v61-mix.dictargs.jsonl"


def load_all():
    rows, seen = [], set()
    for path, expect in SRC:
        n = 0
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("id")
            if rid and rid in seen:
                raise SystemExit(f"[FATAL] 重复 id: {rid}（来自 {path}）")
            if rid:
                seen.add(rid)
            rows.append(r)
            n += 1
        print(f"读入 {path}: {n} 条（期望 {expect}）")
        if n != expect:
            print(f"  ⚠ 数量与期望不符，继续但请核对")
    return rows


def to_dict_args(rows):
    """把 tool_calls[].function.arguments 从 JSON 字符串转 dict"""
    fixed = bad = 0
    out = []
    for r in rows:
        r2 = json.loads(json.dumps(r, ensure_ascii=False))  # 深拷贝
        for m in r2.get("messages") or []:
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                a = fn.get("arguments")
                if isinstance(a, str):
                    try:
                        fn["arguments"] = json.loads(a)
                        fixed += 1
                    except Exception:
                        bad += 1
        out.append(r2)
    return out, fixed, bad


def check(rows, tag):
    print(f"\n=== 校验 {tag} ===")
    n_tc = 0
    err = Counter()
    kinds = Counter()
    cats = Counter()
    for r in rows:
        msgs = r.get("messages") or []
        if not msgs:
            err["空 messages"] += 1
            continue
        if msgs[-1].get("role") != "assistant":
            err["末条非 assistant"] += 1
        kinds[(r.get("meta") or {}).get("kind")] += 1
        cats[(r.get("meta") or {}).get("cat")] += 1
        # tool_call 结构
        call_ids = set()
        for m in msgs:
            for tc in (m.get("tool_calls") or []):
                n_tc += 1
                cid = tc.get("id")
                if cid:
                    call_ids.add(cid)
                fn = tc.get("function") or {}
                if not fn.get("name"):
                    err["tool_call 缺 name"] += 1
                a = fn.get("arguments")
                if tag == "dictargs" and not isinstance(a, dict):
                    err["dictargs 版仍有非 dict arguments"] += 1
                if isinstance(a, str):
                    try:
                        json.loads(a)
                    except Exception:
                        err["arguments 非法 JSON"] += 1
        # tool 消息的 tool_call_id 必须能对上
        for m in msgs:
            if m.get("role") == "tool":
                if m.get("tool_call_id") not in call_ids:
                    err["孤儿 tool 消息"] += 1
    print(f"行数 {len(rows)} · tool_call 总数 {n_tc}")
    print("kind 分布:", dict(kinds))
    print("cat  分布:", dict(cats))
    if err:
        print("❌ 异常:", dict(err))
    else:
        print("✅ 结构零异常（末条 assistant / 无孤儿 tool / 无非法 arguments）")
    return err


def main():
    rows = load_all()
    print(f"\n合并后 {len(rows)} 条")

    # 原样写出
    with open(OUT_RAW, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {OUT_RAW}  md5 {hashlib.md5(open(OUT_RAW,'rb').read()).hexdigest()}")

    # dictargs 写出
    rows_d, fixed, bad = to_dict_args(rows)
    with open(OUT_DICT, "w", encoding="utf-8") as f:
        for r in rows_d:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {OUT_DICT}  md5 {hashlib.md5(open(OUT_DICT,'rb').read()).hexdigest()}")
    print(f"arguments 转 dict: fixed={fixed} bad={bad}")

    e1 = check(rows, "raw(str)")
    e2 = check(rows_d, "dictargs")

    # 配比
    print("\n=== 配比 ===")
    nk = sum(1 for r in rows if (r.get("meta") or {}).get("src") == "v61-nonkitty")
    print(f"nonkitty 新样本: {nk} 条 = {nk/len(rows)*100:.1f}%")
    print(f"带 tools 字段的行: {sum(1 for r in rows if r.get('tools'))}")

    ok = (fixed > 0 and bad == 0 and not e2)
    print(f"\n{'✅ 全部通过' if ok else '❌ 有问题，见上'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
