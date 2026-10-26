#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t20_pick_stale_cache.py -- 旧算法产物不许冒充新结果。

缺陷现象
    pick_checkpoint 的候选循环开头：
        if os.path.exists(dst):
            results[name] = json.load(open(dst))
            continue
    —— dst 存在就跳过，**不看它是哪版算法算出来的**。
后果
    val_loss 的算法本轮修过（lo: BatchEncoding 字段数 2 → 真实前缀 token 数）。
    云端若留着上一轮的 logs/pick/*.json，新跑会静默复用旧 span_loss 的数字去排名：
    报告一切正常（有数、有排序、有推荐），选优结论却来自旧算法 —— 比没有结果更危险。
    S3/B 的同类：**代码 ↔ 产物要用版本戳对指纹，不是只判"文件在不在"**。
正确的断言
    ① 旧产物（无 span_scheme / 戳不一致）→ FATAL 非零退出，且提示 --refresh；
    ② 同戳产物 → 正常复用（打印跳过），rc=0；
    ③ --refresh → 忽略旧产物（不 FATAL），走重算路径。
如果这条 FAIL 说明什么
    缓存判定又退回"文件在就跳过"，旧算法产物重新能混进排名。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
# 可选 argv[1]：指向另一份 pick_checkpoint.py（变异对照用）；run_all.py 不传参。
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "pick_checkpoint.py")

fails = []


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    pc = load_mod(SCRIPT, "pick_ckpt_t20")
except Exception as e:
    print(f"\nFAIL: 载入 pick_checkpoint 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

if not hasattr(pc, "SPAN_SCHEME"):
    print("\nFAIL: pick_checkpoint 缺 SPAN_SCHEME（回归脚本的锚点）")
    sys.exit(1)
SCHEME = pc.SPAN_SCHEME
print(f"[info] SPAN_SCHEME={SCHEME}")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


tmp = tempfile.mkdtemp(prefix="rg-t20-")
try:
    row = {"messages": [{"role": "user", "content": "q"},
                        {"role": "assistant", "content": "a"}]}
    files = {}
    for tag in ("re", "kit", "val"):
        p = os.path.join(tmp, f"{tag}.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        files[tag] = p

    out = os.path.join(tmp, "pick")
    os.makedirs(out)
    # adapter 目录**故意不存在**：这样 --refresh 之后走的是 [skip] 分支，
    # 不会去 from_pretrained（本机没有 27B，加载必然失败，会把 rc 污染成 1）。
    cand = os.path.join(tmp, "cand_missing")

    def run(extra=()):
        cmd = [PY, SCRIPT, "--candidates", f"c:{cand}",
               "--re-eval", files["re"], "--kitty-eval", files["kit"],
               "--val-data", files["val"], "--out", out, *extra]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=dict(os.environ, PYTHONUTF8="1",
                                       PYTHONIOENCODING="utf-8"),
                              timeout=120)

    dst = os.path.join(out, "c.json")

    # ① 旧产物：没有 span_scheme（= 上一轮修的之前的格式）
    json.dump({"candidate": "c", "re_pass": 60, "re_total": 60,
               "kitty_pass": 23, "kitty_total": 23, "val_loss": 1.0},
              open(dst, "w", encoding="utf-8"))
    p = run()
    txt = p.stdout + p.stderr
    print(f"[旧产物  ] rc={p.returncode}  {txt.strip().splitlines()[:2]}")
    check("旧产物 → 非零退出", p.returncode != 0, f"rc={p.returncode}")
    check("旧产物 → 提示 span_scheme/FATAL", "span_scheme" in txt and "FATAL" in txt,
          txt.strip().splitlines()[:1])
    check("旧产物 → 提示 --refresh", "--refresh" in txt,
          "逃生口缺失：用户只能猜着删文件")

    # ①b 戳不一致（比如未来又改算法）
    json.dump({"candidate": "c", "span_scheme": "some_older_scheme",
               "re_pass": 60, "re_total": 60, "kitty_pass": 23, "kitty_total": 23,
               "val_loss": 1.0}, open(dst, "w", encoding="utf-8"))
    p = run()
    check("戳不一致 → 非零退出", p.returncode != 0, f"rc={p.returncode}")

    # ② 同戳 → 正常复用
    json.dump({"candidate": "c", "span_scheme": SCHEME,
               "re_pass": 60, "re_total": 60, "kitty_pass": 23, "kitty_total": 23,
               "val_loss": 1.0}, open(dst, "w", encoding="utf-8"))
    p = run()
    txt = p.stdout + p.stderr
    print(f"[同戳    ] rc={p.returncode}  {[l for l in txt.splitlines() if '跳过' in l][:1]}")
    check("同戳 → rc=0 复用", p.returncode == 0, f"rc={p.returncode}")
    check("同戳 → 打跳过日志", "跳过" in txt, txt.strip().splitlines()[-1:])
    if os.path.exists(os.path.join(out, "_summary.json")):
        s = json.load(open(os.path.join(out, "_summary.json"), encoding="utf-8"))
        check("同戳 → 排名用上了缓存", s.get("best") == "c", f"best={s.get('best')}")

    # ③ --refresh → 不 FATAL，走重算（adapter 不存在 → skip）
    p = run(["--refresh"])
    txt = p.stdout + p.stderr
    print(f"[refresh ] rc={p.returncode}  {[l for l in txt.splitlines() if '忽略' in l][:1]}")
    check("--refresh → rc=0", p.returncode == 0, f"rc={p.returncode}")
    check("--refresh → 忽略旧结果", "忽略旧结果" in txt, txt.strip().splitlines()[:2])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 旧算法产物被拦、同戳可复用、--refresh 有逃生口"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
