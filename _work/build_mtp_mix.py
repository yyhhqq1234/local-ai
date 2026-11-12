"""构造 MTP 混合训练集：RE + 门控创作 + 门控常规，按部署用途配比

为什么要混合：
  上一版只用 mix-z-re-v2-cand-train.jsonl（7,562 条 RE）训 600 步
  ⇒ 600 步 bs=1 只吃了前 600 条，全是 RE 格式
  ⇒ 分域评估：RE top-1 0.8288 / 门控 0.0705 / 创作 0.0547

配比（按部署用途）：
  RE 工具调用       40%   kitty 逆向是主线
  门控创作（许可）   30%   NSFW 许可档要能写
  门控常规（拒/答）  20%   该拒的要拒
  跨域/技术问答      10%   通用能力兜底

用法：
  python _work/build_mtp_mix.py                    # 默认 2000 条
  python _work/build_mtp_mix.py --total 1000
"""
import argparse
import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data")

SRC_RE = os.path.join(D, "kitty-reverse", "mix-z-re-v2-cand-train.jsonl")
SRC_GATE = os.path.join(D, "nsfw-gated", "train-2b-gated-v5.jsonl")
SRC_TRAP = os.path.join(D, "eval", "val", "nsfw-gate.jsonl")
OUT = os.path.join(D, "nsfw-gated", "mix-mtp-2k.jsonl")


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=2000)
    ap.add_argument("--re-ratio", type=float, default=0.40)
    ap.add_argument("--permit-ratio", type=float, default=0.30)
    ap.add_argument("--normal-ratio", type=float, default=0.20)
    ap.add_argument("--misc-ratio", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    random.seed(a.seed)
    n_re = int(a.total * a.re_ratio)
    n_permit = int(a.total * a.permit_ratio)
    n_normal = int(a.total * a.normal_ratio)
    n_misc = a.total - n_re - n_permit - n_normal
    print(f"[plan] total={a.total} · RE={n_re} · 门控创作={n_permit} · 门控常规={n_normal} · 跨域={n_misc}")

    # ① RE
    re_rows = list(read_jsonl(SRC_RE))
    random.shuffle(re_rows)
    pick_re = re_rows[:n_re]
    print(f"[src] RE 候选 {len(re_rows)} → 取 {len(pick_re)}")

    # ② 门控：按 system 是否含「许可」分成创作组 / 常规组
    permit, normal = [], []
    for r in read_jsonl(SRC_GATE):
        msgs = r.get("messages") or []
        sysc = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        (permit if "许可" in sysc else normal).append(r)
    random.shuffle(permit)
    random.shuffle(normal)
    pick_permit = permit[:n_permit]
    pick_normal = normal[:n_normal]
    print(f"[src] 门控许可 {len(permit)} → 取 {len(pick_permit)}")
    print(f"[src] 门控常规 {len(normal)} → 取 {len(pick_normal)}")

    # ③ 跨域：val 集的 general + trap（技术问答 / 陷阱题，防 MTP 只会工具调用和创作）
    misc_pool = []
    for r in read_jsonl(SRC_TRAP):
        k = (r.get("meta") or {}).get("kind")
        if k in ("general", "trap"):
            misc_pool.append(r)
    random.shuffle(misc_pool)
    pick_misc = misc_pool[:n_misc]
    if len(pick_misc) < n_misc:                     # 不够就回填常规组
        need = n_misc - len(pick_misc)
        pick_normal += normal[len(pick_normal): len(pick_normal) + need]
        print(f"[warn] 跨域样本只有 {len(pick_misc)}/{n_misc}，回填 {need} 条到常规组")
    print(f"[src] 跨域候选 {len(misc_pool)} → 取 {len(pick_misc)}")

    # ④ 打乱后写盘（关键：不能按域顺序堆，否则前 N 步只吃一个域）
    mix = pick_re + pick_permit + pick_normal + pick_misc
    random.shuffle(mix)
    print(f"[mix] 合计 {len(mix)} 条，已打乱")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in mix:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    sz = os.path.getsize(a.out)
    print(f"[OK] → {os.path.relpath(a.out, ROOT)}  {len(mix)} 行  {sz/2**20:.1f} MiB")

    # 自检：打乱后的前 200 条里三个来源是否混在一起
    def src_of(r):
        msgs = r.get("messages") or []
        sysc = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        if "许可" in sysc:
            return "创作"
        txt = "\n".join(m.get("content", "") for m in msgs)
        if "kitty" in txt.lower() or "进程" in txt or "基址" in txt:
            return "RE"
        return "其他"
    head = [src_of(r) for r in mix[:200]]
    from collections import Counter
    print(f"[check] 前 200 条来源分布: {dict(Counter(head))}")


if __name__ == "__main__":
    main()
