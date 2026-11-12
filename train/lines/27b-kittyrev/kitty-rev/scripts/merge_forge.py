# -*- coding: utf-8 -*-
"""merge_forge.py —— 把 data/forge/ 四类并入 data/large-mix/train.jsonl
生成 data/large-mix-plus/train.jsonl（不覆盖原文件，不修改 data/large-mix/）

用法：
  python scripts/merge_forge.py --dry-run     # 只算不写，报预测条数与新增分布
  python scripts/merge_forge.py               # 写 data/large-mix-plus/
  python scripts/merge_forge.py --verify      # 写后复核（条数/重复/分布/eval 隔离）

硬约束：
  1) 原文件只读：--src 与 --out 同路径时直接拒绝
  2) 合并去重：full-hash 与 user-hash 双重比对，与既有行重复的 forge 行丢弃并报数
  3) eval 隔离：与 data/eval_re_extended.jsonl 的 full/user hash 冲突即 abort
  4) 输出带 merge-manifest.json：条数 / sha256 / 分布 / 丢弃明细
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
FORGE = os.path.join(DATA, "forge")
SRC = os.path.join(DATA, "large-mix", "train.jsonl")
OUTDIR = os.path.join(DATA, "large-mix-plus")
OUT = os.path.join(OUTDIR, "train.jsonl")
EVAL = os.path.join(DATA, "eval_re_extended.jsonl")

FORGE_FILES = [
    ("re-pe-structure.jsonl", "kb-re"),
    ("re-op-semantics.jsonl", "op-syntax"),
    ("re-decision-chain.jsonl", "action-reverse"),
    ("re-detour-trajectory.jsonl", "real-trajectory"),
]

WS_RE = re.compile(r"[ \t\u3000]+")
NL_RE = re.compile(r"\n{2,}")


def norm(s):
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return NL_RE.sub("\n", WS_RE.sub(" ", s)).strip()


def hh(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def fhash(msgs):
    return hh("\u0001".join(f"{m['role']}\u0002{norm(m['content'])}" for m in msgs))


def uhash(msgs):
    return hh("\u0002".join(norm(m["content"]) for m in msgs if m["role"] == "user"))


def jlines(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for i, l in enumerate(f, 1):
            l = l.strip()
            if not l:
                continue
            out.append((i, json.loads(l)))
    return out


def _rel_or_abs(p):
    """清单里记路径：能在 BASE 下就记相对路径，跨盘（Windows ValueError）记绝对。"""
    try:
        return os.path.relpath(p, BASE).replace("\\", "/")
    except ValueError:
        return os.path.abspath(p).replace("\\", "/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--eval", default=EVAL,
                    help="eval 隔离基线文件（默认 data/eval_re_extended.jsonl）。"
                         "换 eval 集时不传这个参数的话，隔离检查的还是默认文件")
    args = ap.parse_args()

    if os.path.abspath(args.src) == os.path.abspath(args.out):
        print("REFUSE：--src 与 --out 是同一路径，不允许覆盖原文件")
        return 2
    if not os.path.exists(args.src):
        print(f"REFUSE：源文件不存在 {args.src}")
        return 2

    if args.verify:
        # 之前是 verify()：内部读死 SRC/OUT/EVAL，--src/--out 传了也不生效，
        # 用自定义路径跑完再 --verify，检查的是默认路径的文件（静默检查错对象）。
        return verify(args.src, args.out, args.eval)

    src = jlines(args.src)
    print(f"源：{args.src}  {len(src)} 行")

    # 隔离基线缺失时 ev=[] → ev_f/ev_u 为空 → 下面的 ABORT 永远不会触发，
    # 而 manifest 还会记 eval_rows=0 / collisions=0，看起来"干净"。
    if not os.path.exists(args.eval):
        print(f"REFUSE：隔离基线不存在 {args.eval}")
        return 2
    ev = jlines(args.eval)
    if not ev:
        print(f"REFUSE：隔离基线是空的 {args.eval}")
        return 2
    ev_f = {fhash(d["messages"]) for _, d in ev}
    ev_u = {uhash(d["messages"]) for _, d in ev}
    print(f"eval 隔离基线：{len(ev)} 行 / {len(ev_f)} full-hash / {len(ev_u)} user-hash")

    seen_f, seen_u = set(), set()
    for _, d in src:
        seen_f.add(fhash(d["messages"]))
        seen_u.add(uhash(d["messages"]))
    base_n = len(src)

    added, dropped = [], []
    per_cat = {}
    # 隔离冲突计数：旧写法在清单里写死 "collisions": 0，永远不变，读者没法判断
    # 这项检查到底跑没跑过（第 8 例就是这么骗过人的）。现在它是真计数器，
    # 冲突即 return 3，所以写进清单时只可能是 0 —— 但若有人把 ABORT 改成跳过，
    # 这个数会跟着变，字段不再说谎。
    collisions = 0
    for fn, expect_cat in FORGE_FILES:
        p = os.path.join(FORGE, fn)
        if not os.path.exists(p):
            print(f"WARN 缺文件 {p}（跳过）")
            continue
        rows = jlines(p)
        ok = 0
        for ln, d in rows:
            cat = (d.get("meta") or {}).get("cat")
            if cat != expect_cat:
                dropped.append({"file": fn, "line": ln, "why": f"cat 不符 期望{expect_cat} 实得{cat}"})
                continue
            f_, u_ = fhash(d["messages"]), uhash(d["messages"])
            if f_ in ev_f or u_ in ev_u:
                collisions += 1
                print(f"ABORT：{fn}:{ln} 与 eval_re_extended 冲突")
                return 3
            if f_ in seen_f or u_ in seen_u:
                dropped.append({"file": fn, "line": ln, "why": "与既有/已并入行重复"})
                continue
            seen_f.add(f_)
            seen_u.add(u_)
            added.append(d)
            ok += 1
        per_cat[expect_cat] = per_cat.get(expect_cat, 0) + ok
        print(f"  {fn}: {len(rows)} 行 → 并入 {ok}")

    total = base_n + len(added)
    print(f"\n预测：{base_n} + {len(added)} = {total} 行")
    print("新增分布：" + json.dumps(per_cat, ensure_ascii=False))
    if dropped:
        print(f"丢弃 {len(dropped)} 行（前 5）：{json.dumps(dropped[:5], ensure_ascii=False)}")

    if args.dry_run:
        print("\n[dry-run] 未写任何文件")
        return 0

    # 原来写 makedirs(OUTDIR)：--out 指到别的目录时这个目录不会建，
    # 紧接着 open(args.out) 直接 FileNotFoundError（默认路径才能跑通）。
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for _, d in src:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        for d in added:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    blob = open(args.out, "rb").read()
    import collections
    cats = collections.Counter((d.get("meta") or {}).get("cat") for _, d in src)
    for k, v in per_cat.items():
        cats[k] += v
    manifest = {
        # 自定义 --out 落在另一个盘时 os.path.relpath 会抛 ValueError（Windows 跨盘）。
        # 清单只是给人看的，跨盘就用绝对路径，不要让整个合并因为写清单而崩。
        "src": _rel_or_abs(args.src),
        "out": _rel_or_abs(args.out),
        "rows_src": base_n,
        "rows_added": len(added),
        "rows_total": total,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "added_per_cat": per_cat,
        "dropped": dropped,
        "cat_distribution": dict(cats.most_common()),
        "eval_isolation": {"eval_rows": len(ev), "collisions": collisions},
    }
    # 清单跟着实际输出目录走。原来写死 OUTDIR：--out 指到别处时，
    # 数据写在 A、清单写在 B（甚至覆盖 B 里那次真跑的清单）。
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                                 "merge-manifest.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n写出：{args.out}")
    print(f"sha256={manifest['sha256'][:32]}  bytes={len(blob)}")
    return 0


def verify(src_path=None, out_path=None, eval_path=None):
    """路径全部从参数来；不给时才回落到模块默认（供 `--verify` 单独跑）。"""
    src_path = src_path or SRC
    out_path = out_path or OUT
    eval_path = eval_path or EVAL
    for p in (src_path, out_path, eval_path):
        if not os.path.exists(p):
            print(f"REFUSE：缺文件 {p}")
            return 2
    src, out, ev = jlines(src_path), jlines(out_path), jlines(eval_path)
    print(f"原文件 {len(src)} 行（未改动）")
    print(f"合并件 {len(out)} 行")
    ev_f = {fhash(d["messages"]) for _, d in ev}
    ev_u = {uhash(d["messages"]) for _, d in ev}

    def count_dup(rows):
        fs, us, n = set(), set(), 0
        for _, d in rows:
            f_, u_ = fhash(d["messages"]), uhash(d["messages"])
            if f_ in fs or u_ in us:
                n += 1
            fs.add(f_)
            us.add(u_)
        return n

    src_dup = count_dup(src)
    out_dup = count_dup(out)
    print(f"原文件 user-prompt 碰撞：{src_dup}（同问不同答，模板化的 action-reverse 行，非行级重复）")
    print(f"合并件 user-prompt 碰撞：{out_dup}")

    # forge 行自身去重 + 与 eval 冲突
    forge_dup = 0
    evc = 0
    fs, us = set(), set()
    for fn, _ in FORGE_FILES:
        p = os.path.join(FORGE, fn)
        if not os.path.exists(p):
            continue
        for _, d in jlines(p):
            f_, u_ = fhash(d["messages"]), uhash(d["messages"])
            if f_ in fs or u_ in us:
                forge_dup += 1
            fs.add(f_)
            us.add(u_)
            if f_ in ev_f or u_ in ev_u:
                evc += 1
    print(f"forge 行之间重复：{forge_dup}")
    print(f"forge 与 eval 冲突：{evc}")
    print(f"新增重复（合并件 - 原文件）：{out_dup - src_dup}")

    import collections
    c = collections.Counter((d.get("meta") or {}).get("cat") for _, d in out)
    re_cats = ("kb-re", "action-reverse", "op-syntax", "real-trajectory")
    re_n = sum(c.get(k, 0) for k in re_cats)
    print(f"逆向专向合计（kb-re + action-reverse + op-syntax + real-trajectory）= {re_n} "
          f"({re_n / len(out) * 100:.1f}%)")
    for k, v in c.most_common():
        print(f"  {k}: {v}")
    ok = (forge_dup == 0 and evc == 0 and out_dup == src_dup)
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
