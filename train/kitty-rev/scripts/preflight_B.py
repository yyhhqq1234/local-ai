#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""preflight_B.py — B 组 8 条前置断言一键核查（凌晨不用人逐条核）

为什么要有它
  执行卡 tmp/deliver/B-EVAL-EXEC-CARD.md 的 8 条断言是"人能读"的；凌晨没人读。
  本脚本把 8 条变成机器判定，并区分三种状态：
    PASS    断言成立，可以继续
    FAIL    条件已具备但值不对 → 坏了（必须人介入）
    PENDING 条件尚未到点（如训练还没到 pick，pick.md 本来就不该存在）→ 不算坏
  这个区分是核心：把 PENDING 当 FAIL 会让凌晨白停，把 FAIL 当 PENDING 会让坏产物过闸。

判定（对应执行卡 §2；被测对象每次打印绝对路径 + md5/bytes，自证在验什么）
  1 C 四产物 md5          logs/base-only/{re60,bench40,kitty23,refusal-100}.json
  2 eval_bare(std) md5    tmp/eval_bare.py            = c9412673747cc10c65b46a6a8f4b80c6
  3 eval_bare(re60) md5   tmp/eval_bare.re60.py       = 1b6ddc2831cc97ea8fd4b7b0374078dc
                          （--remote 时追加：远端副本是否存在）
  4 refusal_probe 本地 md5 scripts/refusal_probe.py   = 5eb7a9cfda17fb193ad0d04106710b0f
  5 refusal_probe 远端 md5（仅 --remote）= 同上
  6 pick.md 三行           [PICK] adapter= / [PICK] candidate= / [pick] adapter sha16=
                          文件不存在 → PENDING（训练未到点）；存在但行数/内容不对 → FAIL
  7 serve@18001           端口空闲 → PENDING（runB_all 自己起 serve 并断言模型名）
                          端口被占且 /v1/models 含 huihui-base → PASS；名字不符 → FAIL（会评错模型）
  8 batch 结论            --batch>1 时 verdict.json 必须存在且 PASS；batch=1 → PENDING（不需要）

退出码
  0 = 全 PASS（可跑 B 组）
  1 = 有 FAIL（坏了，人介入）
  2 = 无 FAIL 但有 PENDING（还没到点，等）
  3 = 脚本自身错误（文件/参数）

用法
  C:\\ProgramData\\anaconda3\\python.exe scripts\\preflight_B.py                # 只核本地
  C:\\ProgramData\\anaconda3\\python.exe scripts\\preflight_B.py --remote       # 加核远端三项
  C:\\ProgramData\\anaconda3\\python.exe scripts\\preflight_B.py --batch 4 --remote
  C:\\ProgramData\\anaconda3\\python.exe scripts\\preflight_B.py --selftest     # 3 个反例必须被捕获
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.request

KV = r"D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev"
PY = r"C:\ProgramData\anaconda3\python.exe"
REMOTE_PY = os.path.join(KV, "deploy", "remote.py")
RKV = "/root/autodl-tmp/kitty-rev/kitty-rev"

C_DIR = os.path.join(KV, "logs", "base-only")
EVAL_BARE = os.path.join(KV, "tmp", "eval_bare.py")
EVAL_BARE_RE60 = os.path.join(KV, "tmp", "eval_bare.re60.py")
PROBE_LOCAL = os.path.join(KV, "scripts", "refusal_probe.py")
PICKMD = os.path.join(KV, "logs", "v4", "pick.md")
BC_DIR = os.path.join(KV, "logs", "v4", "eval-B", "batchcheck")
VERDICT = os.path.join(BC_DIR, "verdict.json")

SUITES = ("re60", "bench40", "kitty23", "refusal-100")
C_MD5 = {
    "re60": "db1f4b9f0412ccaf5614dbf2dfcb34e1",
    "bench40": "3084611bb64f0350c8d733e02fe99460",
    "kitty23": "d6bc2c6f8598cf6714bf661d484eb135",
    "refusal-100": "278b13e1f7ef6925678b6af009b5e30b",
}
BARE_STD_MD5 = "c9412673747cc10c65b46a6a8f4b80c6"
BARE_RE60_MD5 = "1b6ddc2831cc97ea8fd4b7b0374078dc"
PROBE_MD5 = "842c9e37ba53e22a771f70da0fbe5d38"
PORT = 18001
B_MODEL = "huihui-base"
PICK_PATTERNS = (r"^\[PICK\] adapter=", r"^\[PICK\] candidate=", r"^\[pick\] adapter sha16=")

PASS, FAIL, PENDING = "PASS", "FAIL", "PENDING"


# ---------------------------------------------------------------- 基础

class Ctx(object):
    def __init__(self, remote=False, batch=1, allow_stub=False):
        self.remote = remote
        self.batch = batch
        self.c_dir = C_DIR
        self.eval_bare = EVAL_BARE
        self.eval_bare_re60 = EVAL_BARE_RE60
        self.probe = PROBE_LOCAL
        self.pickmd = PICKMD
        self.verdict = VERDICT
        self.c_md5 = dict(C_MD5)
        self.stub = allow_stub          # selftest：不碰远端、不探测端口外的副作用
        self.remote_py = REMOTE_PY      # 边界测试可指向不存在的路径，模拟 ssh 不通


def md5_of(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def size_of(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def subject(path):
    m = md5_of(path)
    if m is None:
        return "被测对象：%s  [不存在]" % path
    return "被测对象：%s  md5=%s  %d 字节" % (path, m, size_of(path))


def remote_cmd(cmd, timeout=45, rpy=None):
    """→ (rc, stdout)；rc=-1 表示根本连不上（ssh/paramiko 失败）。"""
    rpy = rpy or REMOTE_PY
    try:
        p = subprocess.run([PY, rpy, "--cmd", cmd, "--timeout", str(timeout)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:                                   # noqa: BLE001
        return -1, "remote.py 失败：%s" % e


def port_free_local(port=PORT):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        try:
            s.close()
        except OSError:
            pass


def models_local(port=PORT, timeout=3):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % port, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return [str(m.get("id")) for m in d.get("data", [])]
    except Exception:                                        # noqa: BLE001
        return None


# ---------------------------------------------------------------- 8 条断言

def check1_c_artifacts(ctx):
    rows, bad = [], []
    for s in SUITES:
        p = os.path.join(ctx.c_dir, s + ".json")
        got, want = md5_of(p), ctx.c_md5.get(s)
        rows.append({"suite": s, "path": p, "md5": got, "bytes": size_of(p), "want": want,
                     "ok": bool(got) and got == want})
        if not (got and got == want):
            bad.append(s)
    ev = {"files": rows,
          "why": "缺文件或 md5 不符：%s（C 产物被改过就会 FAIL，这是设计意图）" % bad if bad else "四份齐、md5 全部命中"}
    return "1", "C 四产物 md5", FAIL if bad else PASS, rows[0]["path"], ev


def check2_bare_std(ctx):
    got = md5_of(ctx.eval_bare)
    ev = {"md5": got, "want": BARE_STD_MD5, "bytes": size_of(ctx.eval_bare),
          "why": "bench40/kitty23 用的标准尺" + ("" if got == BARE_STD_MD5 else " 不符")}
    return "2", "eval_bare(std) md5", PASS if got == BARE_STD_MD5 else FAIL, ctx.eval_bare, ev


def check3_bare_re60(ctx):
    got = md5_of(ctx.eval_bare_re60)
    ev = {"md5": got, "want": BARE_RE60_MD5, "bytes": size_of(ctx.eval_bare_re60),
          "why": "re60 专用尺（C 组就是它出的）"}
    st = PASS if got == BARE_RE60_MD5 else FAIL
    if st == FAIL and not os.path.isfile(ctx.eval_bare_re60):
        ev["hint"] = "从 tmp/audit/eval_bare.old-1b6ddc28.py 复制到 tmp/eval_bare.re60.py（HERE 深度必须为 tmp/）"
    if ctx.remote:
        rc, out = remote_cmd("md5sum %s/tmp/eval_bare.re60.py 2>/dev/null || echo REMOTE_MISSING" % RKV,
                             rpy=ctx.remote_py)
        rmd = ""
        for ln in out.splitlines():
            if "REMOTE_MISSING" in ln:
                rmd = "MISSING"
                break
            if "/tmp/eval_bare.re60.py" in ln:
                rmd = ln.split()[0]
        if rc != 0 or (not rmd and "/tmp/eval_bare.re60.py" not in out):
            ev["remote"] = "环境不可达(rc=%s)" % rc
            ev["remote_note"] = "远端核不了不影响本地尺子判定；真跑前必须恢复连通并复跑本项"
        else:
            ev["remote"] = rmd
            if rmd == "MISSING":
                ev["remote_note"] = "远端缺 → runB_all 真跑时自动 push 并断言（dry-run 只回显）"
            elif rmd != BARE_RE60_MD5:
                ev["why"] += "；远端副本 md5=%s 不符" % rmd
                st = FAIL
    return "3", "eval_bare(re60) md5", st, ctx.eval_bare_re60, ev


def check4_probe_local(ctx):
    got = md5_of(ctx.probe)
    ev = {"md5": got, "want": PROBE_MD5, "bytes": size_of(ctx.probe),
          "why": "本地 842c9e37（=5eb7a9cf + --dump-answers；判分与 5eb7a9cf/云端 6a778e16 前 462 行逐字节一致）"}
    return "4", "refusal_probe 本地 md5", PASS if got == PROBE_MD5 else FAIL, ctx.probe, ev


def check5_probe_remote(ctx):
    if not ctx.remote:
        return "5", "refusal_probe 远端 md5", PENDING, ctx.probe, \
               {"why": "未开 --remote，未核远端（开 --remote 才查）"}
    rc, out = remote_cmd("md5sum %s/scripts/refusal_probe.py 2>/dev/null || echo REMOTE_MISSING" % RKV,
                         rpy=ctx.remote_py)
    unreachable = (rc != 0) or ("refusal_probe.py" not in out and "REMOTE_MISSING" not in out)
    if unreachable:
        return "5", "refusal_probe 远端 md5", PENDING, RKV + "/scripts/refusal_probe.py", {
            "remote_path": RKV + "/scripts/refusal_probe.py", "rc": rc,
            "why": "环境不可达（remote.py rc=%s）：远端核不了 ≠ 远端坏了，记 PENDING；恢复连通后必须复跑" % rc}
    got = "MISSING"
    for ln in out.splitlines():
        if "/scripts/refusal_probe.py" in ln and "MISSING" not in ln:
            got = ln.split()[0]
    ev = {"remote_path": RKV + "/scripts/refusal_probe.py", "md5": got, "want": PROBE_MD5,
          "rc": rc, "why": "远端必须同一版（runB_all 会备份旧版并 push）"}
    return "5", "refusal_probe 远端 md5", PASS if got == PROBE_MD5 else FAIL, \
           RKV + "/scripts/refusal_probe.py", ev


def check6_pickmd(ctx):
    import re
    p = ctx.pickmd
    if not os.path.isfile(p):
        return "6", "pick.md 三行", PENDING, p, {
            "why": "文件不存在 = 训练还没到 pick（当前 120/915 步），属条件未到，不算坏",
            "hint": "到点后：\"%s\" \"%s\" --get /root/autodl-tmp/kitty-rev/logs/v4/pick.md \"%s\"" % (PY, REMOTE_PY, p)}
    txt = open(p, encoding="utf-8", errors="replace").read()
    hits = {pat: len(re.findall(pat, txt, re.M)) for pat in PICK_PATTERNS}
    missing = [pat for pat, n in hits.items() if n == 0]
    adapter = ""
    m = re.findall(r"^\[PICK\] adapter=(.+)$", txt, re.M)
    if m:
        adapter = m[-1].strip()
    ev = {"path": p, "bytes": size_of(p), "lines_hit": hits, "missing": missing,
          "adapter": adapter}
    if missing:
        ev["why"] = "pick.md 存在但缺行：%s" % missing
        return "6", "pick.md 三行", FAIL, p, ev
    if not adapter:
        ev["why"] = "[PICK] adapter= 为空"
        return "6", "pick.md 三行", FAIL, p, ev
    if ctx.remote:
        rc, out = remote_cmd("stat -c%%s %s/adapter_model.safetensors 2>/dev/null || echo MISSING" % adapter,
                             rpy=ctx.remote_py)
        sz = "MISSING"
        for ln in out.splitlines():
            if ln.strip().isdigit():
                sz = ln.strip()
        ev["adapter_model.safetensors_bytes"] = sz
        if sz == "MISSING":
            ev["why"] = "adapter 目录缺 adapter_model.safetensors"
            return "6", "pick.md 三行", FAIL, p, ev
    ev["why"] = "三行齐、adapter 非空"
    return "6", "pick.md 三行", PASS, p, ev


def check7_serve(ctx):
    subj = "http://127.0.0.1:%d/v1/models" % PORT
    if ctx.stub:
        return "7", "serve@%d 名字对" % PORT, PENDING, subj, {"why": "selftest stub"}
    if ctx.remote:
        rc, out = remote_cmd("ss -lntp 2>/dev/null | grep ':%d ' || echo PORT_FREE" % PORT,
                             rpy=ctx.remote_py)
        if rc != 0 or ("PORT_FREE" not in out and (":%d " % PORT) not in out):
            return "7", "serve@%d 名字对" % PORT, PENDING, subj, {
                "why": "环境不可达（remote.py rc=%s）：既查不到端口也查不到模型名，记 PENDING；"
                       "恢复连通后必须复跑（这不是'端口空闲'，别混同）" % rc}
        busy = "PORT_FREE" not in out
        if not busy:
            return "7", "serve@%d 名字对" % PORT, PENDING, subj, {
                "why": "端口空闲 = serve 还没起（runB_all 自己起并断言 /v1/models 含 %s）；"
                       "此刻算 PASS 会掩盖'起不来'，算 FAIL 会误杀正常等待" % B_MODEL}
        rc2, out2 = remote_cmd(
            "/root/miniconda3/bin/python -c \"import json,urllib.request;"
            "d=json.load(urllib.request.urlopen('http://127.0.0.1:%d/v1/models',timeout=5));"
            "print(','.join(str(m.get('id')) for m in d.get('data',[])))\"" % PORT,
            rpy=ctx.remote_py)
        ids = ""
        for ln in out2.splitlines():
            if ln.strip() and " " not in ln.strip():
                ids = ln.strip()
        ev = {"port_busy": True, "models": ids, "want": B_MODEL,
              "why": "端口已占且模型名一致" if ids and B_MODEL in ids.split(",") else "端口被别的模型占着 → 会评错模型"}
        return "7", "serve@%d 名字对" % PORT, \
               (PASS if ids and B_MODEL in ids.split(",") else FAIL), subj, ev
    # local
    if port_free_local():
        return "7", "serve@%d 名字对" % PORT, PENDING, subj, {
            "why": "本机端口 %d 空闲 = serve 未起（runB_all 自己起并断言）" % PORT}
    ids = models_local()
    ev = {"models": ids, "want": B_MODEL}
    ok = bool(ids) and B_MODEL in ids
    ev["why"] = "名字一致" if ok else "名字不符或取不到 /v1/models"
    return "7", "serve@%d 名字对" % PORT, PASS if ok else FAIL, subj, ev


def check8_batch(ctx):
    subj = ctx.verdict
    if not os.path.isfile(subj):
        if ctx.batch > 1:
            return "8", "batch 结论", FAIL, subj, {
                "why": "--batch %d 已要求提速，但没有取证结论 → 先跑 --batch-check" % ctx.batch}
        return "8", "batch 结论", PENDING, subj, {"why": "batch=1 不需要取证（要提速才跑 --batch-check）"}
    try:
        d = json.load(open(subj, encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        return "8", "batch 结论", FAIL, subj, {"why": "verdict.json 解析失败：%s" % e}
    concl = str(d.get("conclusion", ""))
    ev = {"conclusion": concl, "bytes": size_of(subj), "batch_arg": ctx.batch}
    if "PASS" not in concl:
        ev["why"] = "结论不是 PASS → 只许 batch=1"
        return "8", "batch 结论", FAIL if ctx.batch > 1 else PENDING, subj, ev
    ev["why"] = "等价性已签 PASS" + ("（可用于 batch=%d）" % ctx.batch if ctx.batch > 1 else "（本轮 batch=1）")
    return "8", "batch 结论", PASS, subj, ev


CHECKS = (check1_c_artifacts, check2_bare_std, check3_bare_re60, check4_probe_local,
          check5_probe_remote, check6_pickmd, check7_serve, check8_batch)


# ---------------------------------------------------------------- 运行 / 输出

def run_all(ctx):
    out = []
    for i, fn in enumerate(CHECKS, 1):
        try:
            res = fn(ctx)
        except Exception as e:                               # noqa: BLE001
            res = (str(i), fn.__name__, FAIL, "-", {"why": "检查器异常：%s" % e})
        out.append(res)
    return out


def _disp(subj):
    """被测对象回显：本地存在的文件给 md5+bytes；URL / 远端 POSIX 路径原样给。"""
    if subj.startswith(("http://", "https://")):
        return "被测对象：%s" % subj
    if not os.path.isfile(subj):
        return "被测对象：%s  [本地不存在]" % subj
    return subject(subj)


def report(results):
    print("== B 组前置断言（8 条）==")
    for cid, name, st, subj, ev in results:
        print("[%s/8] %-22s %-8s %s" % (cid, name, st, _disp(subj)))
        print("      证据：%s" % json.dumps(ev, ensure_ascii=False))
    n = {k: sum(1 for r in results if r[2] == k) for k in (PASS, FAIL, PENDING)}
    bad = [r[1] for r in results if r[2] == FAIL]
    pend = [r[1] for r in results if r[2] == PENDING]
    if n[FAIL]:
        tail = "→ 修：%s" % "、".join(bad)
    elif n[PENDING]:
        tail = "→ 等 %s" % "、".join(pend)
    else:
        tail = "→ 可跑 B 组"
    print("[B-PREFLIGHT] PASS=%d FAIL=%d PENDING=%d %s" % (n[PASS], n[FAIL], n[PENDING], tail))
    if n[FAIL]:
        return 1
    if n[PENDING]:
        return 2
    return 0


# ---------------------------------------------------------------- selftest：3 个反例

def run_selftest():
    """证明断言会 FAIL，而不是静默通过。三个反例各自只打坏一条。"""
    base = os.path.join(KV, "tmp", "_preflight_selftest")
    if os.path.isdir(base):
        import shutil
        shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)

    cases = []

    # 反例 1：C 产物 md5 不符（文件在、内容被改）
    cdir = os.path.join(base, "c")
    os.makedirs(cdir)
    for s in SUITES:
        with open(os.path.join(cdir, s + ".json"), "w", encoding="utf-8") as f:
            json.dump({"suite": s, "rows": []}, f)
    ctx = Ctx(allow_stub=True)
    ctx.c_dir = cdir
    ctx.c_md5 = {s: ("deadbeef" * 4) for s in SUITES}        # 故意写错期望值
    cases.append(("C 产物 md5 不符", check1_c_artifacts, ctx, FAIL))

    # 反例 2：pick.md 只有两行（存在但不完整 → 必须 FAIL，不是 PENDING）
    pick = os.path.join(base, "pick.md")
    with open(pick, "w", encoding="utf-8") as f:
        f.write("[PICK] adapter=/root/autodl-tmp/kitty-rev/kitty-rev/out-v4/checkpoint-735\n"
                "[PICK] candidate=ckpt-735\n")
    ctx2 = Ctx(allow_stub=True)
    ctx2.pickmd = pick
    cases.append(("pick.md 只有两行", check6_pickmd, ctx2, FAIL))

    # 反例 3：probe md5 不符（文件在、版本被换）
    probe = os.path.join(base, "refusal_probe.py")
    with open(probe, "w", encoding="utf-8") as f:
        f.write("# not the real probe\n")
    ctx3 = Ctx(allow_stub=True)
    ctx3.probe = probe
    cases.append(("probe md5 不符", check4_probe_local, ctx3, FAIL))

    print("== preflight_B --selftest（3 个反例必须被捕获）==")
    ok = 0
    for i, (name, fn, ctx, want) in enumerate(cases, 1):
        cid, cname, st, subj, ev = fn(ctx)
        good = (st == want)
        print("[selftest %d/3] %-18s 期望 %s → 实得 %-8s %s" % (i, name, want, st,
                                                               "✓ 正确捕获" if good else "✗ 漏判（会静默通过）"))
        print("              证据：%s" % json.dumps(ev, ensure_ascii=False)[:400])
        ok += 1 if good else 0
    print("[selftest] %d/3 %s" % (ok, "ALL PASS" if ok == 3 else "FAILED"))
    return 0 if ok == 3 else 1


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(
        add_help=True,
        epilog="纪律：生产跑法只允许 `[--remote] [--batch N]`。带 --c-dir / --eval-bare* / "
               "--probe / --pickmd / --verdict / --remote-py 的任何调用都是边界测试，"
               "结果不代表基线（脚本会打 [OVERRIDE] 横幅）。")
    ap.add_argument("--remote", action="store_true", help="用 deploy/remote.py 加核远端三项")
    ap.add_argument("--batch", type=int, default=1, help="本轮打算用的 batch（>1 时 verdict.json 必须有 PASS）")
    ap.add_argument("--selftest", action="store_true", help="3 个反例必须被捕获，否则 exit 1")
    # ---- 以下 7 个覆盖开关（--c-dir / --eval-bare / --eval-bare-re60 / --probe /
    # --pickmd / --verdict / --remote-py）**只用于边界测试或排查**，生产跑法一律不带：
    # 带 --c-dir 指向别处 = 断言的 C 产物不是基线；带 --remote-py = 核的不是真远端。
    # 一旦带上，脚本会自动打 [OVERRIDE] 横幅，防止结果被当成生产结论。
    ap.add_argument("--c-dir", default="", help="[边界测试专用] C 四产物目录覆盖（生产禁用）")
    ap.add_argument("--eval-bare", default="", help="[边界测试专用] 标准尺子路径覆盖（生产禁用）")
    ap.add_argument("--eval-bare-re60", default="", help="[边界测试专用] re60 尺子路径覆盖（生产禁用）")
    ap.add_argument("--probe", default="", help="[边界测试专用] 本地 refusal_probe.py 路径覆盖（生产禁用）")
    ap.add_argument("--pickmd", default="", help="[边界测试专用] pick.md 路径覆盖（生产禁用）")
    ap.add_argument("--verdict", default="", help="[边界测试专用] batchcheck/verdict.json 路径覆盖（生产禁用）")
    ap.add_argument("--remote-py", default="", help="[边界测试专用] deploy/remote.py 覆盖；指向不存在路径=模拟 ssh 不通（生产禁用）")
    a = ap.parse_args(argv[1:])

    if a.selftest:
        return run_selftest()

    ctx = Ctx(remote=a.remote, batch=a.batch)
    overrides = []
    if a.c_dir:
        ctx.c_dir = a.c_dir; overrides.append("c-dir=%s" % a.c_dir)
    if a.eval_bare:
        ctx.eval_bare = a.eval_bare; overrides.append("eval-bare=%s" % a.eval_bare)
    if a.eval_bare_re60:
        ctx.eval_bare_re60 = a.eval_bare_re60; overrides.append("eval-bare-re60=%s" % a.eval_bare_re60)
    if a.probe:
        ctx.probe = a.probe; overrides.append("probe=%s" % a.probe)
    if a.pickmd:
        ctx.pickmd = a.pickmd; overrides.append("pickmd=%s" % a.pickmd)
    if a.verdict:
        ctx.verdict = a.verdict; overrides.append("verdict=%s" % a.verdict)
    if a.remote_py:
        ctx.remote_py = a.remote_py; overrides.append("remote-py=%s" % a.remote_py)
    print("== preflight_B · remote=%s · batch=%d ==" % (a.remote, a.batch))
    if overrides:
        print("[OVERRIDE] 检测到 %d 个边界测试开关：%s" % (len(overrides), "、".join(overrides)))
        print("[OVERRIDE] 本次结果**不代表生产基线** —— 生产跑法：python scripts/preflight_B.py [--remote] [--batch N]，不带任何覆盖开关")
    return report(run_all(ctx))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
