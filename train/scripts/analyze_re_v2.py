#!/usr/bin/env python
"""analyze_re_v2.py — 逆向训练集质量评估（MinHash LSH 去重，2745 条秒级）

用法:
  python train/scripts/analyze_re_v2.py --data train/data/final-re.jsonl
  python train/scripts/analyze_re_v2.py --data train/data/final-re.jsonl --compare train/data/versions/mix-re.20261027-011850.jsonl

维度:
  1 基础统计     条数 / user·assistant 长度 / 轮数
  2 meta 分布    __batch 来源 / __kind 任务类型 / cat / tier 难度 / __round 迭代轮
  3 重复        精确 + MinHash LSH 近似（64 签名 / 16 band × 4 行）
  4 拒绝话术    会反向强化拒绝的样本
  5 工具覆盖     全工具名命中矩阵
  6 领域覆盖     PE/固件/移动/游戏内存/协议/SDK/壳/许可
  7 指令质量     user 前缀模板化、超短指令、超长样本
"""
import argparse
import collections
import hashlib
import json
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REFUSAL_PAT = re.compile(
    r"(我不能|无法协助|不能提供|抱歉[，,]?\s*我|不允许|I cannot|I can't|I'm unable|"
    r"I am unable|I won't|I will not|无法帮助|不便提供)", re.I)

TOOLS = sorted([
    "kitty_ce", "kitty_km", "kitty_dbg", "kitty_x64dbg", "kitty_patch", "kitty_asm",
    "kitty_sym", "kitty_dump", "kitty_ghidra", "kitty_ida", "kitty_idamcp", "kitty_pchain",
    "kitty_acescan", "kitty_prot", "kitty_inject", "kitty_dualview", "kitty_wpb", "kitty_ops",
    "kitty_status", "kitty_drv", "kitty_init", "kitty_net", "kitty_apkscan", "kitty_apktool",
    "kitty_jadx", "kitty_frida", "kitty_il2cppdumper", "kitty_ue4ss", "kitty_uedump",
    "kitty_fmodel", "kitty_gdre", "kitty_lua", "kitty_die", "kitty_assetrip", "kitty_bepinex",
    "kitty_engines", "kitty_variants", "kitty_selftest", "kitty_loop", "kitty_trail",
    "kitty_settings", "kitty_rea", "kitty_rea_binary", "kitty_rea_android", "kitty_rea_method",
    "kitty_rea_function", "kitty_rea_trace", "kitty_rea_callpath", "kitty_rea_javascript",
    "MODENUM", "S_NEW", "S_GET", "S_CHANGED", "P_BACK", "P_WALK", "MEMDUMP_HEX",
    "KM_R", "KM_W", "KM_PA", "KM_PR", "KM_ATTACH", "R|", "W|", "SYNC_ARCHIVE",
])

DOMAINS = {
    "PE/ELF": ["PE ", "PE头", ".text", "节表", "IAT", "ELF", "入口点", "RVA", "重定位", "导入表"],
    "固件": ["固件", "firmware", "squashfs", "uboot", "JTAG", "UART", "binwalk", "UBI"],
    "移动": ["APK", "smali", "Frida", "Xposed", "JNI", "dex", "AArch64", "jadx"],
    "游戏内存": ["血量", "指针链", "基址", "实体列表", "视角", "内存扫描", "偏移", "W2S"],
    "网络协议": ["抓包", "pcap", "帧", "握手", "重放", "TCP", "UDP", "mitm"],
    "SDK/引擎": ["il2cpp", "Unity", "Unreal", "UE4", "UE5", "Mono", "GNames", "GUObjectArray"],
    "加壳/反调试": ["加壳", "脱壳", "anti-debug", "反调试", "OLLVM", "VMP", "混淆", "UPX"],
    "许可/授权": ["license", "许可", "注册机", "卡密", "激活", "校验", "序列号"],
    "内核/驱动": ["驱动", "内核", "Dbg", "PTE", "SSDT", "IRP", "KM_"],
    "CTF": ["CTF", "pwn", "逆向题", "flag"],
}

NGRAM = 3
SIG_K = 64
BANDS, ROWS = 16, 4


def norm(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def grams(t: str):
    t = norm(t)
    return {hashlib.blake2b(t[i:i + NGRAM].encode(), digest_size=8).digest()
            for i in range(max(0, len(t) - NGRAM + 1))}


def minhash(gset):
    if not gset:
        return ()
    return tuple(sorted(gset)[:SIG_K])


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"[BAD JSON] {path}:{ln} {e}")
    return rows


def report(path, rows, compare=None):
    n = len(rows)
    print(f"\n{'='*66}\n{path}\n样本数 {n}\n{'='*66}")

    full, u_lens, a_lens, turns = [], [], [], []
    for r in rows:
        msgs = r.get("messages") or []
        full.append("\x00".join(m.get("content", "") for m in msgs))
        u_lens.append(sum(len(m.get("content", "")) for m in msgs if m.get("role") == "user"))
        a_lens.append(sum(len(m.get("content", "")) for m in msgs if m.get("role") == "assistant"))
        turns.append(len(msgs))

    def q(xs, name):
        xs = sorted(xs)
        p = lambda f: xs[min(len(xs) - 1, int(len(xs) * f))]
        print(f"  {name:12} min {xs[0]:5}  p25 {p(.25):5}  med {p(.5):5}  "
              f"p75 {p(.75):6}  p95 {p(.95):6}  max {xs[-1]:6}  mean {sum(xs)//len(xs):5}")

    print("\n[1] 长度与轮数")
    q(u_lens, "user 字符")
    q(a_lens, "assistant")
    q(turns, "消息数")
    print(f"  多轮(>2 消息) {sum(1 for t in turns if t > 2)}/{n} "
          f"({sum(1 for t in turns if t>2)/n:.1%})")

    # meta 分布
    print("\n[2] meta 分布")
    for key, label, top in [("__batch", "来源批次", 8), ("__kind", "任务类型", 8),
                            ("cat", "类别", 8), ("tier", "难度档", 6),
                            ("__round", "迭代轮", 8), ("src", "src", 6),
                            ("forge", "forge 源", 6)]:
        c = collections.Counter(str((r.get("meta") or {}).get(key)) for r in rows)
        c.pop("None", None)
        if c:
            tot = sum(c.values())
            items = ", ".join(f"{k}={v}" for k, v in c.most_common(top))
            print(f"  {label:10} 覆盖 {tot}/{n}  {items}")

    # 重复
    print("\n[3] 重复")
    exact = n - len(set(full))
    sigs = [minhash(grams(x)) for x in full]
    buckets = collections.defaultdict(list)
    for i, s in enumerate(sigs):
        if not s:
            continue
        for b in range(BANDS):
            seg = s[b * ROWS:(b + 1) * ROWS]
            if len(seg) < ROWS:
                continue
            buckets[(b, hash(seg))].append(i)
    cand = set()
    for ids in buckets.values():
        if len(ids) > 1:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    cand.add((ids[i], ids[j]))
    pairs = []
    for i, j in cand:
        gi, gj = grams(full[i]), grams(full[j])
        if gi and gj:
            jac = len(gi & gj) / len(gi | gj)
            if jac >= 0.8:
                pairs.append((round(jac, 3), i, j))
    pairs.sort(reverse=True)
    print(f"  精确重复 {exact} 条   近似重复(Jaccard≥0.8) {len(pairs)} 对"
          f"   [MinHash LSH 候选 {len(cand)}，比较完 {len(cand)}]")
    for s, i, j in pairs[:5]:
        print(f"    {s}  #{i} vs #{j}  | {full[i][:36]!r}")

    # 拒绝话术
    print("\n[4] 拒绝话术（会强化拒绝）")
    hits = []
    for i, r in enumerate(rows):
        for m in (r.get("messages") or []):
            if m.get("role") == "assistant":
                mm = REFUSAL_PAT.search(m.get("content", ""))
                if mm:
                    hits.append((i, mm.group(0)))
                    break
    print(f"  命中 {len(hits)}/{n} ({len(hits)/n:.2%})")
    for i, kw in hits[:6]:
        print(f"    #{i} {kw!r}")

    # 工具覆盖
    print("\n[5] 工具覆盖")
    blob = "\n".join(full)
    hit = [(t, blob.count(t)) for t in TOOLS]
    hit.sort(key=lambda x: -x[1])
    used = [(t, c) for t, c in hit if c > 0]
    zero = [t for t, c in hit if c == 0]
    print(f"  命中 {len(used)}/{len(TOOLS)} 种")
    print("  前列: " + ", ".join(f"{t}={c}" for t, c in used[:12]))
    if zero:
        print(f"  未出现({len(zero)}): {', '.join(zero)}")

    # 领域
    print("\n[6] 领域覆盖")
    for dom, kws in DOMAINS.items():
        cnt = sum(1 for x in full if any(k in x for k in kws))
        kwc = sum(blob.count(k) for k in kws)
        bar = "#" * min(24, int(cnt / max(1, n) * 60))
        print(f"  {dom:12} 关键词 {kwc:5}   样本 {cnt:4} ({cnt/n:5.1%}) {bar}")

    # 指令质量
    print("\n[7] 指令质量")
    pref = collections.Counter()
    for r in rows:
        for m in (r.get("messages") or []):
            if m.get("role") == "user":
                pref[norm(m.get("content", ""))[:12]] += 1
                break
    dup = sum(c for _, c in pref.most_common() if c > 1)
    print(f"  user 前缀重复覆盖 {dup}/{n} ({dup/n:.1%})")
    for p, c in pref.most_common(5):
        if c > 1:
            print(f"    {c:4}  {p!r}")
    short = sum(1 for x in u_lens if x < 20)
    print(f"  user <20 字符: {short} ({short/n:.1%})")
    verylong = sum(1 for x in a_lens if x > 3000)
    print(f"  assistant >3000 字符: {verylong} ({verylong/n:.1%})  [超 ctx 2048 token 会截断]")

    # 对比
    if compare:
        crows = load(compare)
        print(f"\n[8] 对比 {compare}")
        print(f"  条数        {len(compare and crows)} → {n}  ({n/max(len(crows),1):.1f}x)")
        cu = sorted(sum(len(m.get('content','')) for m in (r.get('messages') or []) if m.get('role')=='user') for r in crows)
        ca = sorted(sum(len(m.get('content','')) for m in (r.get('messages') or []) if m.get('role')=='assistant') for r in crows)
        ct = [len(r.get('messages') or []) for r in crows]
        print(f"  user med    {cu[len(cu)//2]} → {sorted(u_lens)[len(u_lens)//2]}")
        print(f"  assistant med {ca[len(ca)//2]} → {sorted(a_lens)[len(a_lens)//2]}")
        print(f"  多轮占比    {sum(1 for x in ct if x>2)/max(len(ct),1):.1%} → {sum(1 for t in turns if t>2)/n:.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--compare", default=None)
    a = ap.parse_args()
    report(a.data, load(a.data), a.compare)
    return 0


if __name__ == "__main__":
    sys.exit(main())
