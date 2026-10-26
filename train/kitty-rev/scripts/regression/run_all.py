#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_all.py -- 静默错回归集总入口。

    python scripts/regression/run_all.py            # 跑全部
    python scripts/regression/run_all.py t3 t6      # 只跑匹配前缀的

每个 `t_*.py` 是一条「不报错但结果错」的历史缺陷，自带最小输入与断言：
退出码 0=PASS / 1=FAIL。纯 CPU，不加载模型，不读真实数据。

这条套件为什么存在
    这七类缺陷的共同点是**没有异常、没有 traceback，只是结果悄悄变了**。
    正常的单元测试抓不到它们（它们从来不掉用例），只有把「当时错在哪」写成可执行
    断言才能防复发。改 train_partial_lora / precompute_activations / plan_layers /
    pick_checkpoint 之后跑一遍这个，10 秒内知道有没有退化。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# 编码自包含：防「假失败」（与套件要防的「假成功」正好镜像）
#
# 控制台默认 GBK(cp936)：子进程里任何非 GBK 字符的 print 都抛 UnicodeEncodeError
# → 子进程 rc=1 → 被当成 FAIL；汇总行自己也会崩在同一异常上，于是
# 「12/12 PASS」变成「2 条假 FAIL + traceback」。实测（本机）t10/t11 就是这么假红的。
#
# 纪律：不让调用者记得设环境变量。本进程与子进程都在这里钉死 utf-8；
#      子进程用显式 env（不是继承），所以外面传 PYTHONIOENCODING=gbk 也不会漏进去。
# --------------------------------------------------------------------------- #
_REQUIRED = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
_OVERRIDDEN = [f"{k}={os.environ.get(k)}" for k, v in _REQUIRED.items()
               if os.environ.get(k) not in (None, v)]
for _k, _v in _REQUIRED.items():
    os.environ.setdefault(_k, _v)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                        # 非 TextIOWrapper（被重定向/被包裹）时跳过
    pass
CHILD_ENV = dict(os.environ, **_REQUIRED)          # 显式覆盖：子进程只认这份

# --------------------------------------------------------------------------- #
# 环境缺失 ≠ 缺陷（与「假失败 GBK」正好同族的第二种假红）
#
# 套件里有一半脚本要 import torch / transformers（t2-t6 / t18 / t23）。
# 跑在只有 numpy 的解释器上时，它们的 rc=1 是 **ModuleNotFoundError**，
# 但汇总行照样打「12/20 PASS」—— 看上去像 8 条代码缺陷，实际是换了把螺丝刀。
# 这里把这种 rc=1 识别成 ENVN（环境缺件），从计分里摘出去并给出该用哪个解释器。
# --------------------------------------------------------------------------- #
_ENV_MODULES = ("torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate",
                "datasets", "tokenizers", "safetensors")


def env_missing(text):
    """从子进程输出里认出「缺哪个第三方包」；不是环境问题则返回 None。"""
    for m in _ENV_MODULES:
        if f"No module named '{m}'" in text:
            return m
    return None


def dep_versions():
    """在当前解释器里探一次依赖版本（落成 [env] 行，别让人猜跑的是哪把螺丝刀）。"""
    out = {"torch": None, "transformers": None}
    code = ("import json\n"
            "d={}\n"
            "for m in ('torch','transformers'):\n"
            "    try:\n"
            "        d[m]=getattr(__import__(m),'__version__',None)\n"
            "    except Exception:\n"
            "        d[m]=None\n"
            "print(json.dumps(d))\n")
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=120, env=CHILD_ENV)
        got = json.loads((p.stdout or "{}").strip().splitlines()[-1])
        for k in out:
            if got.get(k):
                out[k] = str(got[k])
    except Exception:                       # noqa: BLE001
        pass
    return out


def tests():
    return sorted(f for f in os.listdir(HERE)
                  if f.startswith("t") and f.endswith(".py") and f[1].isdigit())


def main():
    # 自证：这一次跑的编码口径是什么。缺了这行，日后又分不清"真 FAIL / 假 FAIL"。
    print(f"[env] PYTHONIOENCODING={CHILD_ENV['PYTHONIOENCODING']} "
          f"PYTHONUTF8={CHILD_ENV['PYTHONUTF8']} "
          f"stdout={getattr(sys.stdout, 'encoding', '?')} "
          f"stderr={getattr(sys.stderr, 'encoding', '?')}"
          + (f"  (父进程环境已纠正: {', '.join(_OVERRIDDEN)})" if _OVERRIDDEN else ""))
    pats = sys.argv[1:]
    picked = [t for t in tests() if not pats or any(t.startswith(p) or p in t for p in pats)]
    if not picked:
        print("[FATAL] 没有匹配的回归脚本", pats)
        return 2

    rows, t_all = [], time.time()
    for name in picked:
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, name)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, env=CHILD_ENV)
        dt = time.time() - t0
        env_mod = env_missing((p.stdout or "") + (p.stderr or ""))
        rows.append((name, p.returncode == 0, dt, p.returncode,
                     (p.stdout or "").strip().splitlines()[-1:] or [""], env_mod))

    width = max(len(r[0]) for r in rows)
    deps = dep_versions()
    print("=" * (width + 32))
    # 口径自证：跑的是哪个解释器、带不带训练栈。缺了这两行，
    # 「X/Y PASS」这个数字就没法解释（#30 就是缺了它，8 条假红没人认出来）。
    print(f"[env] interpreter = {sys.executable}")
    print(f"[env] torch={deps['torch'] or 'NONE'}  transformers={deps['transformers'] or 'NONE'}")
    print("=" * (width + 32))
    print(f"{'test':{width}s}  {'result':8s}  {'time':>6s}")
    print("-" * (width + 32))
    for name, ok, dt, rc, last, env_mod in rows:
        tag = "PASS" if ok else ("ENV-SKIP" if env_mod else "FAIL")
        print(f"{name:{width}s}  {tag:8s}  {dt:5.1f}s")
        if not ok:
            why = (f"本解释器没有 {env_mod}（不是代码缺陷；换带它的解释器重跑）"
                   if env_mod else last[0][:90])
            print(f"{'':{width}s}  └─ rc={rc}  {why}")
    npass = sum(1 for r in rows if r[1])
    nenv = sum(1 for r in rows if (not r[1]) and r[5])
    nfail = len(rows) - npass - nenv
    print("-" * (width + 32))
    tail = f"   总用时 {time.time() - t_all:.1f}s"
    if nenv:
        mods = sorted({r[5] for r in rows if r[5]})
        print(f"{npass}/{len(rows) - nenv} PASS（计分）   ENV-SKIP {nenv} 条"
              f"（缺 {'/'.join(mods)}，已从分母剔除）{tail}")
        print("[env] ENV-SKIP 不是 FAIL：这些脚本要 import torch/transformers。"
              "带训练栈的解释器示例：C:/ProgramData/anaconda3/envs/EmbodiedAssembly2026/python.exe")
    else:
        print(f"{npass}/{len(rows)} PASS{tail}")
    print("=" * (width + 32))
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
