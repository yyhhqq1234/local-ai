"""遍历一次训练的 checkpoint，用泛化集选最优 —— 不靠 train loss 猜

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么需要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-10-28 RE r2 实测：train loss 从 3.84 一路降到 0.3731，但泛化命中率是
基座 0% → 1 遍 50% → 2 遍 91.7% → 3 遍 83.3%。**loss 最低的 final 不是最好的。**
只有泛化集能选出真正的峰点。

做法：训练结束后，对 output_dir 下每个 checkpoint-<step> 依次跑 12 条泛化题，
按「编造升序 → 命中率降序 → step 升序」排序，给出最优 checkpoint。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python select_best_ckpt.py --run train/lines/9b-oxcoder/out/re-stage1-r3
  python select_best_ckpt.py --run train/lines/9b-oxcoder/out/re-stage1-r3 --steps 400,800,1200
  python select_best_ckpt.py --run train/lines/9b-oxcoder/out/re-stage1-r3 --include-final
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)


def find_ckpts(run_dir, only_steps=None, include_final=False):
    out = []
    for d in glob.glob(os.path.join(run_dir, "checkpoint-*")):
        m = re.search(r"checkpoint-(\d+)$", d)
        if not m:
            continue
        step = int(m.group(1))
        if only_steps and step not in only_steps:
            continue
        # 必须有 adapter 权重
        if not os.path.isfile(os.path.join(d, "adapter_model.safetensors")):
            continue
        out.append((step, d))
    if include_final:
        fd = os.path.join(run_dir, "final")
        if os.path.isdir(fd):
            out.append((10 ** 9, fd))   # final 排最后
    out.sort(key=lambda x: x[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="训练输出目录（含 checkpoint-*）")
    ap.add_argument("--steps", default="", help="只评这些 step，逗号分隔")
    ap.add_argument("--include-final", action="store_true", dest="inc_final")
    ap.add_argument("--out", default=None, help="汇总 JSON 路径")
    args = ap.parse_args()

    if not os.path.isdir(args.run):
        sys.exit("[FATAL] 目录不存在: %s" % args.run)

    only = None
    if args.steps:
        only = {int(x) for x in args.steps.split(",") if x.strip()}

    ckpts = find_ckpts(args.run, only, args.inc_final)
    if not ckpts:
        sys.exit("[FATAL] 没找到任何可用 checkpoint（需含 adapter_model.safetensors）")

    print("=" * 84)
    print("checkpoint 泛化选优 —— %s" % args.run)
    print("候选 %d 个：" % len(ckpts) + ", ".join(
        ("final" if s == 10 ** 9 else str(s)) for s, _ in ckpts))
    print("=" * 84)

    # 延迟导入：只要跑评测时才加载 torch
    import eval_re_generalize as G

    results = []
    for step, path in ckpts:
        label = "final" if step == 10 ** 9 else "ckpt-%d" % step
        print()
        print("──────── %s ────────" % label)
        try:
            model, tok = G.load_model(path)
            r = G.run(model, tok, label, 300)
            del model
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            r["step"] = step
            r["path"] = path
            results.append(r)
        except Exception as e:
            print("  [ERR] %s 评测失败: %s" % (label, e))
            results.append({"tag": label, "step": step, "path": path,
                            "error": str(e), "acc": -1, "hit": -1, "fake": 999})

    # 排序：编造升序 → 命中率降序 → step 升序（同等效果取更早的）
    ok = [r for r in results if "error" not in r]
    ok.sort(key=lambda r: (r["fake"], -r["acc"], r["step"]))

    print()
    print("=" * 84)
    print("排名（编造升序 → 命中率降序 → step 升序）")
    print("=" * 84)
    print("%-12s %-9s %-6s %-6s %-6s %-8s" % ("checkpoint", "命中率", "选错", "编造", "回避", "L1/L2/L3"))
    for i, r in enumerate(ok, 1):
        lv = r["by_level"]
        trio = "%d/%d/%d" % (lv.get("L1", {}).get("hit", 0),
                             lv.get("L2", {}).get("hit", 0),
                             lv.get("L3", {}).get("hit", 0))
        star = "  ← 最优" if i == 1 else ""
        print("%-12s %-9s %-6d %-6d %-6d %-8s%s"
              % (r["tag"], "%.1f%%" % (r["acc"] * 100),
                 r["wrong"], r["fake"], r["none"], trio, star))

    if ok:
        best = ok[0]
        print()
        print("  ★ 选定：%s  → %s" % (best["tag"], best["path"]))
        print("     命中 %.1f%%，编造 %d，L1/L2/L3 = %d/%d/%d"
              % (best["acc"] * 100, best["fake"],
                 best["by_level"].get("L1", {}).get("hit", 0),
                 best["by_level"].get("L2", {}).get("hit", 0),
                 best["by_level"].get("L3", {}).get("hit", 0)))
        print()
        print("  采用方式（三选一）：")
        if best["step"] != 10 ** 9:
            print("    ① 直接用该 checkpoint 目录：%s" % best["path"])
            print("    ② 快照到独立目录（防后续轮转）：")
            print("       mkdir -p %s-best && cp %s/{adapter_model.safetensors,adapter_config.json} %s-best/"
                  % (args.run, best["path"], args.run))
            print("    ③ 与 final 对比后决定是否改写 RE-BASELINE.md")
        else:
            print("    final 就是最优，直接用")

    out = args.out or os.path.join(args.run, "ckpt-select.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"run": args.run, "best": ok[0] if ok else None,
                   "all": results}, f, ensure_ascii=False, indent=2)
    print()
    print("  明细 → %s" % out)


if __name__ == "__main__":
    main()
