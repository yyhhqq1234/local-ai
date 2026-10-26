#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5_auto.py —— V5 全自动编排（无人值守），Python 版

为什么是 Python 而不是 bash：
  本机没有 bash（Get-Command bash → NO_BASH），v5_auto.sh 的语法无法在开机前验证。
  无人值守的前提是"脚本本身先被验证过"，所以重写成 Python：本机可 `py_compile`。

设计（对应 PLAN §0.6 的 PR 硬性规定）：
  · 每步自己断言（rc + 内容 + 尺寸），FAIL 立即停
  · 每步自动写 PR-<step>.md，把实测数字填进去，不留空
  · 需要人判断的点全部预置分支（PLAN §5 D1/D2），不等人
  · marker 断点续跑

用法（云端）：
  python3 tools/v5_auto.py                 # 全跑
  python3 tools/v5_auto.py --skip-train    # 已有 out-v5/adapter，从 merge 起
  python3 tools/v5_auto.py --from S4       # 从量化链起
  python3 tools/v5_auto.py --dry-run       # 只打印将执行什么
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

R = Path("/root/autodl-tmp/kitty-rev")
KV = R
PY = "/root/miniconda3/bin/python"
MK = R / "logs/v5/.markers"
PRD = R / "logs/v5"
LOG = R / "logs/v5/AUTO-V5.log"
BASE = R / "base/Huihui"
AD = R / "out-v5/adapter"
MERGED = R / "merged-v5"
MMP = R / "gguf/v5-mmproj-q8.gguf"
MIX = R / "data/intent3/v5-mix/train.jsonl"
NIN = R / "ninfer-v5"
NAME = "qwen3.8-27b-kittyrev-v5-iq2s-mtp"
OUT = NIN / f"{NAME}.ninfer"
PORT = 18080
SIZE_GATE = 11274289152  # 10.5 GiB

T0 = time.time()


# ---------------------------------------------------------------- 基础设施
def log(msg: str) -> None:
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def elapsed_h() -> float:
    return (time.time() - T0) / 3600


def free_gb() -> int:
    try:
        st = shutil.disk_usage("/root/autodl-tmp")
        return int(st.free / 1e9)
    except Exception:
        return -1


def has(step: str) -> bool:
    return (MK / f"{step}.ok").exists()


def ok(step: str, detail: str) -> None:
    MK.mkdir(parents=True, exist_ok=True)
    (MK / f"{step}.ok").write_text(detail, encoding="utf-8")
    log(f"[{step}] PASS {detail}")


def write_pr(step: str, verdict: str, lines: list[str]) -> None:
    PRD.mkdir(parents=True, exist_ok=True)
    f = PRD / f"PR-{step}.md"
    body = [
        f"# PR-{step} — 自动生成 {time.strftime('%F %T')}",
        "",
        "## 元信息",
        "```text",
        f"步号      {step}",
        f"时刻      {time.strftime('%F %T')}",
        "执行者    v5_auto.py（无人值守）",
        f"累计耗时  {elapsed_h():.2f} h",
        f"磁盘剩余  {free_gb()} G",
        "```",
        "",
        "## Q1 本步实际结果",
        "```text",
        *lines,
        "```",
        "",
        "## Q2/Q3 判定",
        "```text",
    ]
    if verdict == "PROCEED":
        body += [
            "结论：PROCEED —— 判据全部满足，按 PLAN §0.2 进下一步",
            "计划假设：未被推翻",
            "⚠ 注意：本文件由 v5_auto.py 自动生成，属**执行者自述**，不是 §0.6 的 PR 裁决。",
            "   §0.6 的裁决是 PR-T<n>.md（lead 决策 + reviewer 独立结论两份），二者不可互相替代。",
        ]
    elif verdict in ("SKIP", "WARN"):
        body += [
            f"结论：{verdict} —— 本步**未真正验证**，只是不阻塞主链",
            "⚠ 这类 marker 不许当 PASS 用（不许把存在性当正确性）",
            "   需要 lead 决定是补测还是记为未覆盖",
        ]
    elif verdict == "DRY":
        body += ["结论：DRY —— dry-run，未执行任何动作"]
    else:
        body += [
            "结论：FAIL —— 已停在当前步，后续未执行",
            "处置：按 PLAN §5 D1/D2 的预置分支；预置分支无解则保留现状等操作者",
        ]
    body += ["```", "", "## Q4 下一步", "见 `logs/v5/TEAM-PLAN-V5.md` §0.2。", ""]
    f.write_text("\n".join(body), encoding="utf-8")
    log(f"[PR] {f} ({verdict})")


class StepFail(Exception):
    def __init__(self, step: str, reason: str):
        super().__init__(reason)
        self.step = step
        self.reason = reason


def run(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> int:
    log("[run] " + " ".join(cmd))
    with open(LOG, "a", encoding="utf-8") as f:
        try:
            p = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                               stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
            return p.returncode
        except subprocess.TimeoutExpired:
            log(f"[run] TIMEOUT after {timeout}s")
            return 124


def need(path: Path, step: str, what: str) -> None:
    if not path.exists():
        raise StepFail(step, f"缺{what}: {path}")


# ---------------------------------------------------------------- 各步
def s1_train(dry: bool) -> list[str]:
    need(MIX, "S1", "训练集")
    need(BASE, "S1", "base 目录")
    rows = sum(1 for _ in open(MIX, encoding="utf-8"))
    log(f"[S1] 训练集 {rows} 行")
    cmd = [
        PY, "scripts/train_kitty.py", "--size", "27b", "--stage", "sft",
        "--base", str(BASE), "--text-only", "--data", str(MIX),
        "--ctx", "2048", "--bs", "1", "--ga", "16",
        "--epochs", "1.5", "--lr", "1e-4",
        "--lora-r", "16", "--lora-alpha", "32",
        "--all-gpu", "--out", "out-v5",
        "--dl-workers", "4", "--pin-memory", "--prefetch", "2",
        "--skip-kbit-prepare",
    ]
    if dry:
        log("[dry] " + " ".join(cmd))
        return ["DRY-RUN：未执行训练"]
    rc = run(cmd, cwd=KV)
    if rc != 0:
        raise StepFail("S1", f"训练 rc={rc}（日志尾部看 Traceback/OOM）")
    am = AD / "adapter_model.safetensors"
    if not am.exists():
        raise StepFail("S1", "训练无 adapter 产物")
    sz = am.stat().st_size
    if sz < 100_000_000:
        raise StepFail("S1", f"adapter 太小 {sz}")
    ok("S1", f"adapter={sz}")
    return [f"rc=0", f"训练集={rows} 行", f"adapter={sz} B", f"耗时={elapsed_h():.2f} h"]


def s2_merge(dry: bool) -> list[str]:
    need(AD / "adapter_model.safetensors", "S2", "adapter")
    if dry:
        log(f"[dry] tensor_merge --base {BASE} --adapter {AD} --out {MERGED} --stream")
        return ["DRY-RUN：未执行 merge"]
    rc = run([PY, "-u", str(KV / "tools/tensor_merge.py"),
              "--base", str(BASE), "--adapter", str(AD),
              "--out", str(MERGED), "--stream"])
    if rc != 0:
        raise StepFail("S2", f"merge rc={rc}")
    shards = sorted(MERGED.glob("*.safetensors"))
    if len(shards) != 18:
        raise StepFail("S2", f"片数 {len(shards)} != 18")
    # merge 不拷 index（COPY_EXTRA 老 bug），必须补
    for name in ("model.safetensors.index.json", "vocab.json",
                 "video_preprocessor_config.json", "added_tokens.json"):
        src, dst = BASE / name, MERGED / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            log(f"[S2] 补拷 {name}")
    need(MERGED / "model.safetensors.index.json", "S2", "index.json（convert 必需）")
    ok("S2", f"shards={len(shards)}")
    return ["rc=0", f"shards={len(shards)}", "index 已补拷"]


def s3_mmproj(dry: bool) -> list[str]:
    conv = None
    for c in (R / "ninfer-all-master/convert_hf_to_gguf.py", R / "lc/convert_hf_to_gguf.py"):
        if c.exists():
            conv = c
            break
    if conv is None:
        raise StepFail("S3", "找不到 convert_hf_to_gguf.py")
    if MMP.exists():
        log("[S3] mmproj 已存在，跳过合成")
    elif dry:
        log(f"[dry] {PY} {conv} {MERGED} --mmproj --outtype q8_0 --outfile {MMP}")
        return ["DRY-RUN：未执行 mmproj"]
    else:
        rc = run([PY, str(conv), str(MERGED), "--mmproj", "--outtype", "q8_0",
                  "--outfile", str(MMP)], timeout=3600)
        if rc != 0:
            raise StepFail("S3", f"mmproj rc={rc}")
    need(MMP, "S3", "mmproj 产物")
    sz = MMP.stat().st_size
    if sz < 300_000_000:
        raise StepFail("S3", f"mmproj 太小 {sz}（可能没转 vision）")
    if sz > 700_000_000:
        raise StepFail("S3", f"mmproj 太大 {sz}（可能没量化成 q8_0）")
    ok("S3", f"mmproj={sz}")
    return ["rc=0", f"mmproj={sz} B（q8_0，预期 0.42-0.46 GB）"]


def s4_quant(dry: bool) -> list[str]:
    need(MMP, "S4", "mmproj（S3 未完成）")
    if dry:
        log(f"[dry] chain_repair.py --from M1  (MERGED={MERGED})")
        return ["DRY-RUN：未执行量化链"]
    # B3 决策（2026-10-24 12:50，chain-op 提出）：带 --free-merged
    #   不带：峰值 55.6(merged) + 53.8(bf16) + 29(q8) + 9.6(iq2s) ≈ 148 G → 200 G 盘遇 v4 残留会爆
    #   带  ：M1.5 后删 merged → 峰值 ≈ 92 G
    #   代价：S5 的 serve_4bit_base --model MERGED 失效 → S5 自动 SKIP（拒答率本机补测）
    rc = run([PY, "-u", str(KV / "tools/chain_repair.py"), "--from", "M1",
              "--free-merged"], cwd=R)
    if rc != 0:
        raise StepFail("S4", f"chain rc={rc}（看日志哪一门红）")
    need(OUT, "S4", "产物 .ninfer")
    sz = OUT.stat().st_size
    magic = OUT.open("rb").read(4).hex()
    if magic != "47475546":
        raise StepFail("S4", f"magic={magic}（期望 47475546）")
    if sz >= SIZE_GATE:
        raise StepFail("S4", f"体积 {sz} >= 10.5 GiB")
    ok("S4", f"bytes={sz} magic=GGUF")
    return [f"rc=0", f"size={sz} B = {sz/1073741824:.3f} GiB", "magic=GGUF",
            "三元断言：rc + magic + size 全过"]


def s5_refusal(dry: bool) -> list[str]:
    probe = KV / "scripts/refusal_probe.py"
    serve = KV / "scripts/serve_4bit_base.py"
    if not probe.exists() or not serve.exists():
        log("[S5][WARN] 缺 refusal_probe.py / serve_4bit_base.py，跳过（不阻塞）")
        return ["SKIP：脚本缺失，拒答率留本机补测"]
    if dry:
        log(f"[dry] serve_4bit_base + refusal_probe on :{PORT}")
        return ["DRY-RUN：未起服务"]
    import urllib.request
    proc = subprocess.Popen(
        [PY, str(serve), "--model", str(MERGED), "--port", str(PORT),
         "--name", "v5", "--thinking"],
        stdout=open(LOG, "a", encoding="utf-8"), stderr=subprocess.STDOUT)
    up = False
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=3)
            up = True
            break
        except Exception:
            time.sleep(5)
    try:
        if not up:
            log("[S5][WARN] 4bit 服务未起来，跳过拒答率（不阻塞交付）")
            return ["SKIP：4bit 服务未就绪"]
        outjson = PRD / "refusal-v5.json"
        rc = run([PY, str(probe), "--mode", "text",
                  "--base", f"http://127.0.0.1:{PORT}", "--model", "v5",
                  "--out", str(outjson)], timeout=3600)
        if rc != 0:
            log(f"[S5][WARN] refusal_probe rc={rc}，不阻塞")
            return [f"WARN：refusal_probe rc={rc}"]
        ok("S5", "refusal measured")
        return [f"拒答率已测 → {outjson}"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()


STEPS = [
    ("S1", "训练（base + v5-mix, 1.5ep）", s1_train),
    ("S2", "merge(v5 adapter)", s2_merge),
    ("S3", "mmproj(vision q8_0)", s3_mmproj),
    ("S4", "量化链 M1→M6（含 vision）", s4_quant),
    ("S5", "拒答率（可跳过）", s5_refusal),
]


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-train", action="store_true")
    ap.add_argument("--from", dest="from_step", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    log(f"===== V5 AUTO start{' (dry-run)' if a.dry_run else ''} =====")
    log(f"[disk] free={free_gb()}G")

    started = False
    for sid, title, fn in STEPS:
        if a.from_step and not started:
            if sid != a.from_step:
                log(f"[skip] {sid}（--from {a.from_step}）")
                continue
            started = True
        if a.skip_train and sid == "S1":
            log("[skip] S1（--skip-train）")
            continue
        if has(sid):
            log(f"[skip] {sid}（marker 已存在）")
            continue

        log(f"----- {sid} {title} -----")
        try:
            detail = fn(a.dry_run)
        except StepFail as e:
            write_pr(e.step, "FAIL", [f"原因：{e.reason}", f"耗时={elapsed_h():.2f} h"])
            log(f"[STOP] {e.step} :: {e.reason}")
            return 1
        except Exception as e:  # noqa: BLE001
            write_pr(sid, "FAIL", [f"异常：{type(e).__name__}: {e}"])
            log(f"[STOP] {sid} 异常 {type(e).__name__}: {e}")
            return 1
        # 自述 PR 的结论必须与实际情况一致：SKIP/WARN/DRY 不许写成 PROCEED
        # （watchdog 2026-10-24 指出：S5 三处 [WARN] 不阻塞，若仍写 PROCEED 就是伪 PASS）
        head = (detail[0] if detail else "").strip()
        if head.startswith("SKIP"):
            v = "SKIP"
        elif head.startswith("WARN"):
            v = "WARN"
        elif head.startswith("DRY-RUN"):
            v = "DRY"
        else:
            v = "PROCEED"
        write_pr(sid, v, detail)

    # 收口报告
    rep = PRD / "REPORT-V5-AUTO.md"
    lines = [
        f"# V5 全自动执行报告 {time.strftime('%F %T')}",
        "",
        "```text",
        f"总耗时   {elapsed_h():.2f} h",
        f"产物     {OUT}",
    ]
    if OUT.exists():
        sz = OUT.stat().st_size
        lines.append(f"体积     {sz} B ({sz/1073741824:.3f} GiB)")
    lines.append("门禁     " + " ".join(sorted(p.stem for p in MK.glob("*.ok"))))
    lines += [
        "```",
        "",
        "## PR 清单",
        *[f"- {p.name}" for p in sorted(PRD.glob("PR-*.md"))],
        "",
        "## 下一步（本机）",
        "```text",
        "1 get_multi 回传 .ninfer + conversion.json",
        "2 起本机引擎 → judge7_v4.py + probe_kitty.py",
        "3 拒答率与 v4r 对比（若 S5 已测直接用）",
        "4 控制台关机（容器内关不掉，已定论）",
        "```",
    ]
    rep.write_text("\n".join(lines), encoding="utf-8")
    log(f"[report] {rep}")
    log("===== V5 AUTO DONE =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
