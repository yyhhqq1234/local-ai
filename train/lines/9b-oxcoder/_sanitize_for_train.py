#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
训练数据净化器：把任意 jsonl 收敛成 datasets 能稳定加载的「纯 messages」格式

为什么需要（2026-11-02 实测）：
  2B v4 训练启动即失败：
    TypeError: Couldn't cast array of type
      struct<gate:string, cat:string, src:string, kind:string>
    to
      {gate:string, cat:string, trigger:string, src:string, pos_kind:string}
  根因：同一文件里 meta 有 4 种结构
    (cat,gate,pos_kind,src,trigger) 13903 · 无 meta 13030 · (kind,src) 3360 · (cat,gate,src) 1881
  datasets 用第一行推断 schema，后续不匹配直接抛 DatasetGenerationError。
  Z-B 的 mix 同样有 4 种组合（_aug/_coverage/meta/裸 messages）。

处方：训练只需要 messages。把 meta / _aug / _coverage 等辅助字段全部剥掉，
     并逐行校验 messages 结构合法。产出 <name>-train.jsonl。

用法：
  python _sanitize_for_train.py <in.jsonl> [out.jsonl]
"""
import io, json, os, sys, collections

ALLOWED_ROLES = {"system", "user", "assistant"}


def sanitize(inp, outp):
    rows, bad = [], collections.Counter()
    with io.open(inp, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                bad["json 解析失败"] += 1
                continue
            msgs = d.get("messages")
            if not isinstance(msgs, list) or not msgs:
                bad["无 messages 或非列表"] += 1
                continue
            ok = True
            clean = []
            for m in msgs:
                if not isinstance(m, dict):
                    bad["消息非对象"] += 1
                    ok = False
                    break
                role = m.get("role")
                content = m.get("content")
                if role not in ALLOWED_ROLES:
                    bad[f"非法 role={role}"] += 1
                    ok = False
                    break
                if not isinstance(content, str) or not content.strip():
                    bad["空/非字符串 content"] += 1
                    ok = False
                    break
                clean.append({"role": role, "content": content})
            if not ok:
                continue
            if clean[-1]["role"] != "assistant":
                bad["末条不是 assistant"] += 1
                continue
            if sum(1 for m in clean if m["role"] == "assistant") != 1:
                bad["assistant 数 != 1"] += 1
                continue
            rows.append({"messages": clean})

    with io.open(outp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows, bad


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    inp = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 else inp.replace(".jsonl", "-train.jsonl")
    if not os.path.exists(inp):
        print(f"[FATAL] 不存在: {inp}")
        return 2
    n_in = sum(1 for l in io.open(inp, encoding="utf-8") if l.strip())
    rows, bad = sanitize(inp, outp)
    print(f"[IN ] {inp}  {n_in} 行")
    print(f"[OUT] {outp}  {len(rows)} 行（丢弃 {n_in - len(rows)}）")
    if bad:
        print("  丢弃原因：", dict(bad))
    # schema 唯一性验证
    keys = collections.Counter(tuple(sorted(r.keys())) for r in rows)
    print(f"  顶层字段组合：{dict(keys)}  ← 必须只有一种")
    return 0 if len(keys) == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
