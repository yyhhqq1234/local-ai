#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pin_arch.py -- merge 后 / convert 前把 config.json 的 architectures 钉成纯文本架构。

为什么必须有这一步（v4 雷区 c）
    Huihui 基座是 **VL 包装模型**（Qwen3_5ForConditionalGeneration，含 333 个 vision
    张量）。merge（纯 text）出来的目录里只剩 text 张量，但 config.json 的
    `architectures` 仍然是 `["Qwen3_5ForConditionalGeneration"]`。
    `convert_hf_to_gguf.py` 按 `architectures` 选转换分支 —— 于是它走 VL 分支：
      · 少/多写张量（v./visual./mm. 前缀）、
      · 或者干脆抛 KeyError 后你换参数重试，**换成了 text 分支但没意识到**；
      · 两种结局都是「产物能写出来、inspect 也能过」，只有张量数/前缀能暴露。
    所以 convert 之前必须把两个 architectures 都钉住：
        config["architectures"]              = ["Qwen3_5ForCausalLM"]
        config["text_config"]["architectures"] = ["Qwen3_5ForCausalLM"]

为什么不备份（体积 ×2）
    merged 目录 ~52 GiB，config.json 只有几 KB —— 但**约定性地不留 .bak**：
    带 .bak 的 config 会被 `convert_*` / 打包 / `du -sh` 当成第二份配置读进去
    （已踩过 pack 里多出一个 config 的同类事故）。安全靠**回读校验 + 幂等**：
      · 写前算 sha16，写后重新 json.load 回读逐字段比对，不等就原地 FATAL；
      · 已经是目标值 → 不写盘、不动 mtime，第二次跑 md5 保持不变（幂等可证）。
    原子替换用 `os.replace(tmp, dst)`，中途崩溃只会留下 `config.json.tmp.<pid>`
    （本脚本退出前会清掉；崩溃残留在下一次运行时被识别并删除，不是 .bak）。

判据（不是"跑通了"，是"内容对了"）
    · `--check`：已经是目标值 → rc=0；需要 pin → rc=1；config 缺失/坏 → rc=2
    · 正常 pin 后打印 `[pin] before=... after=... sha16=... → ...`
    · `--index`：统计 `model.safetensors.index.json` 的 weight_map 里视觉张量数，
      纯文本 merge 必须 = 0（这是「merge 真的是纯 text」的**产物特征**判据，
      不看你 merge 命令写了什么参数）

用法
    python scripts/pin_arch.py --dir /root/autodl-tmp/kitty-rev/merged-cfg/Qwen3.8-27B-kittyrev
    python scripts/pin_arch.py --dir <dir> --check          # 只验不写（CI/七步闸门用）
    python scripts/pin_arch.py --dir <dir> --index --json    # 附带视觉张量统计
"""
import argparse
import hashlib
import json
import os
import sys

DEFAULT_ARCH = "Qwen3_5ForCausalLM"


# --------------------------------------------------------------------------- #
# 纯函数（回归集 t24 直接调用，不需要磁盘/模型）
# --------------------------------------------------------------------------- #
def sha16(path, cap=None):
    """sha256 前 16 位。cap 给定时只读前 N 字节（大文件指纹用）。"""
    h = hashlib.sha256()
    left = cap
    with open(path, "rb") as f:
        while True:
            n = 1 << 20 if left is None else min(1 << 20, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()[:16]


def pin_cfg(cfg, arch=DEFAULT_ARCH, text_arch=None):
    """纯函数：把 architectures 钉住，返回 (changed, before)。

    changed: [(字段路径, 旧值, 新值)]；already-pinned 时为空列表。
    before : {"architectures": 旧值, "text_config.architectures": 旧值}
    不修改入参以外的状态（就地修改 cfg，但 before 已先取好）。
    """
    text_arch = text_arch or arch
    before = {"architectures": cfg.get("architectures"),
              "text_config.architectures": (cfg.get("text_config") or {}).get("architectures")}
    changed = []
    if cfg.get("architectures") != [arch]:
        changed.append(("architectures", before["architectures"], [arch]))
        cfg["architectures"] = [arch]
    tc = cfg.get("text_config")
    if not isinstance(tc, dict):
        # text-only merged 目录的正常形态是「没有 text_config」或「有但不完整」。
        # 两种都要能把字段写进去：写不进去 = convert 侧依然可能按 VL 分支走。
        tc = {} if tc is None else dict(tc)
        cfg["text_config"] = tc
    if tc.get("architectures") != [text_arch]:
        changed.append(("text_config.architectures",
                        before["text_config.architectures"], [text_arch]))
        tc["architectures"] = [text_arch]
    return changed, before


def vision_tensor_count(index_obj):
    """index weight_map 里视觉/多模态前缀的张量名计数（纯文本 merge 必须 0）。"""
    wm = (index_obj or {}).get("weight_map") or {}
    bad = []
    for k in wm:
        if k.startswith(("visual.", "vision_tower.", "mm.", "model.visual.",
                         "model.vision_tower.", "model.mm.")) or ".visual." in k:
            bad.append(k)
    return len(bad), bad[:8]


def readback_ok(path, arch=DEFAULT_ARCH, text_arch=None):
    """回读校验：返回 (ok, 实测值字典, 错误串)。"""
    text_arch = text_arch or arch
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except Exception as e:                                  # noqa: BLE001
        return False, {}, f"回读失败（{type(e).__name__}: {e}）"
    a = got.get("architectures")
    b = (got.get("text_config") or {}).get("architectures")
    ok = (a == [arch] and b == [text_arch])
    return ok, {"architectures": a, "text_config.architectures": b}, "" if ok else \
        f"回读值不符：architectures={a!r} text_config.architectures={b!r}"


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="pin merged 模型的 architectures（幂等、无 .bak）")
    ap.add_argument("--dir", required=True, help="merged 模型目录（含 config.json）")
    ap.add_argument("--arch", default=DEFAULT_ARCH, help=f"顶层架构名（默认 {DEFAULT_ARCH}）")
    ap.add_argument("--text-arch", default=None, help="text_config.architectures（默认同 --arch）")
    ap.add_argument("--check", action="store_true", help="只校验不写：已 pinned rc=0，需 pin rc=1")
    ap.add_argument("--index", action="store_true", help="附带统计视觉张量数（纯文本 merge 应为 0）")
    ap.add_argument("--json", action="store_true", help="额外打印一行 JSON 结果")
    a = ap.parse_args()

    cfg_path = os.path.join(a.dir, "config.json")
    if not os.path.isdir(a.dir):
        print(f"[FATAL] 目录不存在：{a.dir}")
        return 2
    if not os.path.isfile(cfg_path):
        print(f"[FATAL] 缺 {cfg_path} —— merge 没写配置就去 convert 是静默错源头（坑 c）")
        return 2

    # 崩溃残留：本脚本只认 config.json.tmp.* 为自己的，其余一律不碰
    for name in os.listdir(a.dir):
        if name.startswith("config.json.tmp."):
            try:
                os.remove(os.path.join(a.dir, name))
                print(f"[clean] 删除上次崩溃残留 {name}")
            except OSError as e:
                print(f"[warn] 残留 {name} 删不掉（{e}）；不影响本次 pin，"
                      f"但打包/convert 可能把它当第二份配置")
    baks = [n for n in os.listdir(a.dir) if ".bak" in n and n.startswith("config")]
    if baks:
        print(f"[warn] 目录里有配置备份 {baks} —— 打包/convert 可能把它当第二份配置读入；"
              f"本脚本不会创建也不会删除，请你确认后自行清理")

    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    sha_before = sha16(cfg_path)
    changed, before = pin_cfg(cfg, a.arch, a.text_arch)

    vis = None
    idx_path = os.path.join(a.dir, "model.safetensors.index.json")
    if a.index:
        if os.path.isfile(idx_path):
            with open(idx_path, encoding="utf-8") as f:
                vis = vision_tensor_count(json.load(f))
            print(f"[index] 视觉张量数={vis[0]}  {'✓ 纯文本' if vis[0] == 0 else '✗ 仍有视觉张量：' + str(vis[1])}")
        else:
            print(f"[index] 缺 {idx_path}（跳过视觉张量统计）")

    if not changed:
        ok, got, err = readback_ok(cfg_path, a.arch, a.text_arch)
        print(f"[pin] 已 pinned，幂等跳过（sha16={sha_before} {got}）{'' if ok else ' ' + err}")
        if a.json:
            print(json.dumps({"changed": [[c[0], c[1], c[2]] for c in changed],
                              "sha16_before": sha_before, "sha16_after": sha_before,
                              "state": "already", "vision_tensors": None if vis is None else vis[0]},
                             ensure_ascii=False))
        return 0 if ok else 2

    print(f"[pin] before={before}")
    if a.check:
        print(f"[FATAL] 未 pinned：需要把 {[c[0] for c in changed]} 改成 {a.arch!r}。"
              f"convert 会按旧架构走 VL 分支（坑 c）。去掉 --check 执行 pin")
        if a.json:
            print(json.dumps({"changed": [[c[0], c[1], c[2]] for c in changed],
                              "state": "need_pin", "sha16_before": sha_before},
                             ensure_ascii=False))
        return 1

    tmp = f"{cfg_path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, cfg_path)                     # 原子；不留 .bak

    ok, got, err = readback_ok(cfg_path, a.arch, a.text_arch)
    sha_after = sha16(cfg_path)
    print(f"[pin] after ={got}   sha16 {sha_before} → {sha_after}")
    if not ok:
        print(f"[FATAL] 写后回读不一致（{err}）—— 写盘被截断或被并发改写")
        if a.json:
            print(json.dumps({"changed": [[c[0], c[1], c[2]] for c in changed],
                              "state": "readback_fail", "err": err}, ensure_ascii=False))
        return 2
    leftovers = [n for n in os.listdir(a.dir) if n.startswith("config.json.tmp.") or
                 (".bak" in n and n.startswith("config"))]
    if leftovers:
        print(f"[FATAL] 目录里出现备份/临时文件 {leftovers}（本脚本不留 .bak，体积 ×2 禁止）")
        return 2
    print(f"[pin] OK  changed={[c[0] for c in changed]}  幂等可重跑（第二次 sha16 不变）")
    if a.json:
        print(json.dumps({"changed": [[c[0], c[1], c[2]] for c in changed],
                          "state": "pinned", "sha16_before": sha_before, "sha16_after": sha_after,
                          "vision_tensors": None if vis is None else vis[0]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
