#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t29_shell_gates.py -- 七步与 iq2s 的成功判据必须落在产物特征上。

缺陷现象
    run_after_expand.sh / iq2s_final.sh 全靠 `set -e` + `ls -lh` + `du -sh`：
      · merge 的 skip 判据是「config.json 在不在」（中断残留会被当完成）
      · quant 没有 --imatrix、没有 ssm_*=q8_0（rc=0，产物被下游 recipe 拒）
      · 全链没有 pin architectures（convert 会走 VL 分支）
      · ninfer 只 `inspect | head -12` 瞟一眼，没有断言
后果
    命令全绿、日志好看，交付物是错的（张量数/格式/前缀不对）——
    这就是本项目 19 个静默错里最贵的一类。
正确的断言（本脚本就是那条断言）
    ① 七步每一步都调用 verify_expand.py 闸门（step 1/2/3/5/6/7）
    ② merge 后、convert 前调用 pin_arch.py
    ③ quant 带 --imatrix 与逐条 --tensor-type blk.N.ssm_alpha/beta=q8_0
    ④ 没有 --tensor-type-file（实测会失败）
    ⑤ merge 的幂等判据包含 shard 数（不是只看 config.json）
    ⑥ .ninfer 用 --components text
    ⑦ 变异对照：把上面任意一条删掉，检查函数必须报红（证明断言不是空跑）
如果这条 FAIL 说明什么
    闸门接线被删/被绕过，链路又回到「只看 exit code」。
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
F_SEVEN = os.path.join(KITTY, "deploy", "cloud", "run_after_expand.sh")
F_IQ2S = os.path.join(KITTY, "deploy", "iq2s_final.sh")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_comments(s):
    """去掉整行注释再检查 —— 「--tensor-type-file 实测会失败」这类说明不该被当成
    本脚本真的在用它（假阳性会让这条回归被改成永远绿）。"""
    return "\n".join(ln for ln in s.splitlines() if not ln.lstrip().startswith("#"))


def problems_seven(s):
    """run_after_expand.sh 的判据缺口清单（空 = 合格）。"""
    out = []
    if "verify_expand.py" not in s:
        out.append("没有接 verify_expand.py")
    for st in ("1", "2", "3", "5", "6", "7"):
        if f"gate {st}" not in s:
            out.append(f"步骤 {st} 没有 gate 调用")
    if "pin_arch.py" not in s:
        out.append("没有 pin architectures")
    if "--imatrix" not in s:
        out.append("quant 缺 --imatrix（IQ2_S 必需）")
    if '--tensor-type "blk.' not in s:
        out.append("quant 缺逐条 --tensor-type ssm_*")
    if "--tensor-type-file" in s:
        out.append("又用回了 --tensor-type-file（实测失败）")
    if "nshard" not in s or "-ge 18" not in s:
        out.append("merge 幂等判据没有 shard 数（中断残留会被当完成）")
    if "--components text" not in s:
        out.append("convert 缺 --components text（可能走 VL 分支）")
    # ②b imatrix：没有这一步 = 一键链会在 quant 处 FATAL（v3 是手工跑的）
    if "imatrix)" not in s:
        out.append("没有 imatrix 步（IQ2_S 必需，v3 手工跑的那步没进一键链）")
    # gate 2b 允许**委托**：七步调 make_imatrix.sh --gate，判据在 helper 里。
    # 委托时 helper 必须真的跑 verify_expand --step 2b（两者缺一即报）。
    if "gate 2b" in s:
        pass
    elif "make_imatrix.sh" in s and "--gate" in s:
        helper = os.path.join(KITTY, "deploy", "cloud", "make_imatrix.sh")
        if not os.path.isfile(helper):
            out.append("七步调 make_imatrix.sh --gate，但 helper 不存在")
        else:
            h = open(helper, encoding="utf-8", errors="replace").read()
            if "--step 2b" not in h:
                out.append("make_imatrix.sh --gate 没跑 verify_expand --step 2b")
    else:
        out.append("imatrix 步没有 gate 2b（存在/够大/不早于 bf16.gguf）")
    if "CALIB" not in s:
        out.append("imatrix 步没有 calib 前置（不许随便塞一段文本）")
    # ⑦ act-cache 目录名契约：v4 叫 act-cache-v4，本地硬编码 act-cache
    if ".act-cache-dir-name" not in s:
        out.append("pack 没写 .act-cache-dir-name（本地 local_train.ps1 会死在缺 act-cache）")
    return out


def problems_iq2s(s):
    out = []
    if "pin_arch.py" not in s:
        out.append("convert 前没有 pin architectures")
    if "--tensor-type-file" in s:
        out.append("又用回了 --tensor-type-file（实测失败）")
    if 'TT+=(--tensor-type "blk.' not in s:
        out.append("没有逐条 --tensor-type ssm_*")
    if "--imatrix" not in s:
        out.append("quant 缺 --imatrix")
    if "--step 3" not in s:
        out.append("IQ2_S 后没有 verify step 3（格式分布没判）")
    if "--step 5" not in s:
        out.append(".ninfer 后没有 verify step 5（objects/tensors 没判）")
    return out


s7, sq = strip_comments(read(F_SEVEN)), strip_comments(read(F_IQ2S))

# ①②③④⑤⑥ 真实文件必须零缺口
p7 = problems_seven(s7)
check("①-⑥ run_after_expand.sh 判据齐全", p7 == [], "；".join(p7))
pq = problems_iq2s(sq)
check("①-⑥ iq2s_final.sh 判据齐全", pq == [], "；".join(pq))

# 逐条点名（便于日后定位是哪一条被删）
for st in ("1", "2", "3", "5", "6", "7"):
    check(f"  七步 step {st} 有闸门", f"gate {st}" in s7)
check("  quant 用 --tensor-type 逐条（64 层 × 2）",
      'for i in $(seq 0 63)' in s7 and "ssm_beta.weight=q8_0" in s7)
check("  gate 失败即 exit（不是 return 0）",
      "exit 1" in s7 and "[FATAL] 步骤 $st 的产物特征不合格" in s7)

# ⑦ 变异对照：删掉任意一条，检查函数必须变红
OLD_SEVEN = """#!/usr/bin/env bash
set -euo pipefail
merge)
  if [ -f "$MERGED/config.json" ]; then echo "[skip] merged 已存在"; else
    $PY "$ROOT/scripts/merge.py" --size 27b --adapter "$ADAPTER" --dest "$MERGED"
  fi
  du -sh "$MERGED"
  ;;
quant)
  "$LC/build/bin/llama-quantize" "$GGUF/qwen38_27b_kittyrev_bf16.gguf" \\
      "$GGUF/qwen38_27b_kittyrev_iq2s.gguf" IQ2_S 16 2>&1 | tail -6
  ls -lh "$GGUF"/qwen38_27b_kittyrev_iq2s.gguf
  ;;
"""
op = problems_seven(OLD_SEVEN)
check("⑦ 旧版七步（只看 exit code）必被报红", len(op) >= 6, f"{len(op)} 项：{op[:4]}")
for must in ("没有接 verify_expand.py", "没有 pin architectures",
             "没有 imatrix 步（IQ2_S 必需，v3 手工跑的那步没进一键链）",
             "quant 缺 --imatrix（IQ2_S 必需）"):
    check(f"⑦ 旧版被抓：{must}", must in op)

OLD_IQ2S = """#!/usr/bin/env bash
set -euo pipefail
"$PY" - > /root/tt.txt <<'PY'
for i in range(64):
    print(f"blk.{i}.ssm_alpha.weight q8_0")
PY
"$LC/build/bin/llama-quantize" --imatrix "$R/imatrix.dat" \\
  --tensor-type-file /root/tt.txt \\
  "$R/gguf/bf16.gguf" "$R/gguf/iq2s.gguf" IQ2_S 16
ls -lh "$R/ninfer/"*.ninfer
"""
oq = problems_iq2s(OLD_IQ2S)
check("⑦ 旧版 iq2s（tensor-type-file + 无 pin）必被报红", len(oq) >= 4, f"{len(oq)} 项：{oq}")
check("⑦ 旧版被抓：--tensor-type-file", "又用回了 --tensor-type-file（实测失败）" in oq)

# bash 语法（改过的脚本必须还能被 bash 解析；CRLF 也会在这里暴露）
import subprocess
for f in (F_SEVEN, F_IQ2S):
    p = subprocess.run(["bash", "-n", f], capture_output=True, text=True)
    check(f"bash -n {os.path.basename(f)}", p.returncode == 0,
          (p.stderr or "").strip()[:100])
    raw = open(f, "rb").read()
    ncr = raw.count(b"\x0d")
    check(f"{os.path.basename(f)} 无 CRLF（在 Linux 上会猝死）", ncr == 0, "CR=" + str(ncr))

print("\nPASS: 七步/iq2s 的判据都在产物特征上，删一条即被这条回归抓住"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
