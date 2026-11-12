#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t27_verify_expand_soft.py -- 假设值（base_tensors=1199）必须降级成 WARN，且可升硬。

缺陷现象
    verify_expand.py 的 EXPECT["base_tensors"]=1199 是 **v3 base 分片总数**
    （866 text + 333 vision）。v4 换 Huihui + merge 纯 text 之后只有 ~866，
    闸门会 FAIL —— 而产物其实是对的。
    这时人有两条路：① 以为产物坏了去返工；② 直接把期望改成 866
    —— 后者更危险：以后 vision 张量混进 GGUF 也抓不到。
后果
    闸门要么把人骗去返工，要么被改废（从此不再能发现 VL 分支污染）。
正确的断言
    ① 默认（未显式给）→ 数量不符记 WARN，不拉红整步（rec 返回 True）
    ② --set base_tensors=866（= 实测值回填）→ 同一条判据变成 FAIL（硬）
    ③ --expect-file 不存在 → rc=2（打错路径不许退回假设值）
    ④ 未知键 → 只 warn，不改 EXPECT、不崩
    ⑤ 形态：SOFT_KEYS 只含 base_tensors（别把别的判据也顺手放软）
如果这条 FAIL 说明什么
    假设值又被当成硬判据（或反过来全部放软），闸门的区分度没了。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(KITTY, "scripts", "verify_expand.py")
PY = sys.executable
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    V = load_mod(SCRIPT, "verify_expand_t27")
    check("verify_expand 可 import", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 verify_expand 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

check("⑤ SOFT_KEYS 只含 base_tensors", V.SOFT_KEYS == {"base_tensors"}, str(V.SOFT_KEYS))
check("内置默认仍是 1199（历史值，别偷偷改成 866）",
      V.EXPECT["base_tensors"] == 1199, str(V.EXPECT["base_tensors"]))

# ① 未显式 → WARN，且不拉红
V.rows.clear()
V.EXPLICIT.discard("base_tensors")
ok = V.rec("2", "tensor 数", False, "866（期望 1199）", key="base_tensors")
st = V.rows[-1][2]
check("① 数量不符 → status=WARN", st == "WARN", st)
check("① WARN 不拉红整步（rec 返回 True）", ok is True, str(ok))
check("① 提示里给了升级办法", "--set" in V.rows[-1][3], V.rows[-1][3][-40:])
# ③ 出处可追溯：WARN 必须说清这个期望值来自硬编码 / 文件 / --set
check("① WARN 打出期望值出处（默认=内置）", "来自「内置默认" in V.rows[-1][3],
      V.rows[-1][3][-60:])
check("① 出处可查询", V.expect_provenance("base_tensors").startswith("内置默认"),
      V.expect_provenance("base_tensors"))

# ② 显式回填实测值 → 同一条变硬
V.apply_expect_overrides({"base_tensors": 866}, "--set")
check("② 期望值已改成 866", V.EXPECT["base_tensors"] == 866, str(V.EXPECT["base_tensors"]))
check("② --set 后出处变成 --set", V.expect_provenance("base_tensors") == "--set",
      V.expect_provenance("base_tensors"))
V.rows.clear()
ok = V.rec("2", "tensor 数", False, "900（期望 866）", key="base_tensors")
st = V.rows[-1][2]
check("② 显式后同一条判据变 FAIL", st == "FAIL" and ok is False, f"{st} {ok}")
V.rows.clear()
ok = V.rec("2", "tensor 数", True, "866（期望 866）", key="base_tensors")
check("② 命中时仍然 PASS", V.rows[-1][2] == "PASS" and ok is True, V.rows[-1][2])

# ④ 未知键只 warn
before = dict(V.EXPECT)
V.apply_expect_overrides({"no_such_key": 1}, "--expect-file")
check("④ 未知键不改 EXPECT", V.EXPECT == before and "no_such_key" not in V.EXPECT)

# ③ --expect-file 打错 → rc=2；--set 可用（用未定义 step 避免真去扫产物）
tmp = tempfile.mkdtemp(prefix="rg-t27-")
try:
    p = subprocess.run([PY, SCRIPT, "--step", "9", "--root", tmp,
                        "--expect-file", os.path.join(tmp, "nope.json")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONIOENCODING="utf-8"), timeout=60)
    check("③ --expect-file 不存在 → rc=2", p.returncode == 2, f"rc={p.returncode}")
    check("③ 报错说清是 --expect-file 缺失",
          "expect-file" in (p.stdout + p.stderr), (p.stdout + p.stderr).strip()[:80])

    p = subprocess.run([PY, SCRIPT, "--step", "9", "--root", tmp,
                        "--set", "base_tensors=866"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONIOENCODING="utf-8"), timeout=60)
    out = p.stdout + p.stderr
    check("③ --set 生效且 rc=0", p.returncode == 0 and "覆盖 1 项" in out, f"rc={p.returncode}")

    exp = os.path.join(tmp, "expect.json")
    with open(exp, "w", encoding="utf-8") as f:
        json.dump({"base_tensors": 866, "ninfer_objects": 792}, f)
    p = subprocess.run([PY, SCRIPT, "--step", "9", "--root", tmp, "--expect-file", exp],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONIOENCODING="utf-8"), timeout=60)
    out = p.stdout + p.stderr
    check("③ --expect-file 生效（覆盖 2 项）", p.returncode == 0 and "覆盖 2 项" in out,
          out.strip().splitlines()[:2])
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 假设值默认 WARN / 显式回填升硬 / 路径打错 FATAL / 未知键不吞"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
