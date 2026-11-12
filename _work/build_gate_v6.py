"""方案 A：清洗 v5 → v6 —— 许可组只保留「本身通过 55 词严格判据」的样本

背景（2026-11-05 实测）：
  v5 许可组 19,068 条里只有 59.73% 能过 judge_nsfw（hits≥2），
  35.75% 的回复 hits=0（文学化暗示 / 心理描写 / 短对白）。
  模型 100% 复刻数据分布时 recall 上限就是 59.73%，永远到不了 0.90。

做法：
  · 许可组（system 含「许可」）：只留 hits ≥ --min-hits 的样本
  · 常规组（拒答 / 允许答）：全部保留（这是「该拒」能力的来源，不能动）
  · system / user 文本逐字不改（门控腿要求 system 模板逐字一致）

用法：
  python _work/build_gate_v6.py                 # 只出对照
  python _work/build_gate_v6.py --apply         # 写 v6
  python _work/build_gate_v6.py --min-hits 3    # 更严的档位
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "_shared", "scripts"))

from nsfw_gate_eval import STRICT_TERMS, judge_nsfw  # noqa: E402

SRC = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated",
                   "train-2b-gated-v5.jsonl")
DST = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated",
                   "train-2b-gated-v6.jsonl")


def hits_of(text):
    r = judge_nsfw(text, STRICT_TERMS)
    return int(r[1]), bool(r[0])


def dist(name, arr):
    if not arr:
        print(f"  {name}: n=0")
        return
    arr = sorted(arr)
    n = len(arr)
    q = lambda p: arr[min(n - 1, int(p * (n - 1)))]
    ok = sum(1 for x in arr if x >= 2)
    print(f"  {name}: n={n}  hits≥2 比例={ok/n:.4f}  "
          f"p10={q(.1)} p50={q(.5)} p90={q(.9)} max={arr[-1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hits", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dst", default=DST)
    a = ap.parse_args()

    permit_all, permit_keep, permit_drop = [], [], []
    normal_all = []
    kept_lines = []

    for line in open(SRC, encoding="utf-8"):
        d = json.loads(line)
        msgs = d.get("messages") or []
        sysc = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        asst = [m["content"] for m in msgs if m.get("role") == "assistant"]
        if not asst:
            continue
        h, _ok = hits_of(asst[-1])
        if "许可" in sysc:
            permit_all.append(h)
            if h >= a.min_hits:
                permit_keep.append(h)
                kept_lines.append(line)
            else:
                permit_drop.append(h)
        else:
            normal_all.append(h)
            kept_lines.append(line)

    print("=" * 72)
    print(f"方案 A 清洗对照（min_hits = {a.min_hits}）")
    print("=" * 72)
    print(f"源文件 {os.path.relpath(SRC, ROOT)}")
    print()
    print("[清洗前]")
    dist("许可组", permit_all)
    dist("常规组", normal_all)
    print(f"  合计 {len(permit_all) + len(normal_all)} 行")
    print()
    print("[清洗后]")
    dist("许可组(保留)", permit_keep)
    dist("常规组(全留)", normal_all)
    print(f"  丢弃许可样本 {len(permit_drop)} 条")
    print(f"  合计 {len(kept_lines)} 行")
    print()

    rows = len(kept_lines)
    print(f"[步数估算] bs=1 ga=4 → 1 epoch = {rows // 4 + (1 if rows % 4 else 0)} 步")
    print(f"           × 5.5 s/step ≈ {rows / 4 * 5.5 / 3600:.2f} 小时")
    print()
    print("[其他 min-hits 档位参考]")
    for mh in (2, 3, 4, 5, 6):
        k = sum(1 for h in permit_all if h >= mh)
        print(f"  min_hits={mh}: 保留 {k:6d} / {len(permit_all)}  ({k/len(permit_all)*100:5.1f}%)  "
              f"→ v6 合计 {k + len(normal_all)} 行 = {(k+len(normal_all))//4} 步")
    print()

    if not a.apply:
        print("（dry-run，未写文件。加 --apply 落盘）")
        return

    os.makedirs(os.path.dirname(a.dst), exist_ok=True)
    with open(a.dst, "w", encoding="utf-8") as f:
        for line in kept_lines:
            f.write(line if line.endswith("\n") else line + "\n")
    print(f"[OK] 已写 {os.path.relpath(a.dst, ROOT)}  {rows} 行")

    # 落盘后自检：重新读一遍算分布
    chk_p, chk_n = [], []
    for line in open(a.dst, encoding="utf-8"):
        d = json.loads(line)
        msgs = d["messages"]
        sysc = msgs[0]["content"] if msgs[0].get("role") == "system" else ""
        asst = [m["content"] for m in msgs if m.get("role") == "assistant"]
        h, _ = hits_of(asst[-1])
        (chk_p if "许可" in sysc else chk_n).append(h)
    print("[自检] v6 实际分布：")
    dist("许可组", chk_p)
    dist("常规组", chk_n)


if __name__ == "__main__":
    main()
