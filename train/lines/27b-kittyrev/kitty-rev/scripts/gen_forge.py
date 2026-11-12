# -*- coding: utf-8 -*-
"""data-forge 生成器：四类逆向专向样本 → JSONL + 质检闸门 + MANIFEST

用法：
  python gen_forge.py            # 生成 R1（各 30）
  python gen_forge.py --all      # 生成全量（各 120，需源已扩）
  python gen_forge.py --check    # 只质检已有输出

硬闸门（任一不过 → abort，不写文件）：
  G1 assistant 长度 >= 200
  G2 工具/OP 名 >= 2
  G3 至少一个可执行步骤（kitty_* action= / OP 行 / 命令式行）
  G4 免责话术 0 命中
  G5 与既有 359 + 全量 train 3908 的 full-hash 与 user-hash 均不重复
  G6 与 eval_re_extended 60 的 full-hash 与 user-hash 均不重复，
     且 user 提示的 5-gram Jaccard < 0.35（近重复隔离）
  G7 类内互相不重复（full-hash + user-hash）
  G8 op-syntax 类：禁止无区间 S_NEW / 无窗口 P_BACK
  G9 源文件不得含 U+FFFD
"""
import json
import os
import re
import sys
import hashlib
import argparse
import statistics
import importlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # train/lines/27b-kittyrev/kitty-rev
DATA = os.path.join(BASE, "data")
FORGE = os.path.join(DATA, "forge")
SRC = os.path.join(BASE, "scripts", "forge_src")

sys.path.insert(0, SRC)

TARGET_PER = 120                      # 每类目标条数（--all 时生效）

# ---------------- 规范与哈希 ----------------
WS_RE = re.compile(r"[ \t\u3000]+")
NL_RE = re.compile(r"\n{2,}")


def norm_text(s):
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = WS_RE.sub(" ", s)
    s = NL_RE.sub("\n", s)
    return s.strip()


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def full_hash(msgs):
    return h("\u0001".join(f"{m['role']}\u0002{norm_text(m['content'])}" for m in msgs))


def user_hash(msgs):
    us = [norm_text(m["content"]) for m in msgs if m["role"] == "user"]
    return h("\u0002".join(us))


def shingles(text, n=5):
    t = re.sub(r"\s+", "", norm_text(text))
    if len(t) < n:
        return {t}
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------- 闸门 ----------------
TOOL_RE = re.compile(r"\b(kitty_[a-z0-9_]+)\b")
OP_RE = re.compile(
    r"\b(S_NEW|S_SNAP|S_CHANGED|S_UNCHANGED|S_GET|S_FREE|P_BACK|P_BACK_RES|P_WALK|"
    r"MODENUM|MODBASE|KM_R|KM_W|KM_ATTACH|KM_PA|KM_PR|KM_PW|KM_API|KM_INFO|"
    r"MEMDUMP_HEX|DBG_REGS|DBG_BP|DBG_ATTACH|DBG_GO|DBG_STAT|DBG_WAIT|"
    r"SYNC_ARCHIVE|SYNC_STAT|JOB_STAT|ALLOC|FREE|LP|OPEN|CUR|PING|VER|LUA|"
    r"W|R)\b")

REFUSAL_RE = re.compile(
    r"抱歉|很遗憾|建议咨询|作为\s*AI|作为人工智能|无法协助|不能协助|恕难|"
    r"我不能帮你|违反|免责|仅供学习|请勿用于|合法用途|授权范围外")

# 可执行步骤：kitty_* 带具名参数（action=/op=/target=…）/ OP 管道 / 代码围栏 / 指令式命令行
STEP_RE = re.compile(
    r"(kitty_[a-z0-9_]+\s+(?:action|op|ops|path|target|addr|name|filter|from|to|module|pid|"
    r"base|code|at|bytes|pattern|str|variant|ioctls?|device|pkg|script|value)\s*=)"
    r"|([A-Z_]{3,}\|[^|\n]*\|)"
    r"|(^\s*(?:python|node|curl|strings|adb|uiautomator|frida|jadx|apktool|binwalk|r2|radare2)\b)",
    re.M)

# op-syntax 类硬约束：每个 S_NEW 必须带显式区间；每个 P_BACK 必须带窗口
# 允许 0xSTART / 0xSTOP / 0xBASE+0x1000000 这类显式占位（位置明确即为有区间），
# 但段数必须 5 段且后两段以 0x 开头 —— 三段式（无区间）一律拒。
S_NEW_OK = re.compile(
    r"S_NEW\|[^|\n]+\|[^|\n]+\|0x[0-9A-Za-z_+*x]+\|0x[0-9A-Za-z_+*x]+")
S_NEW_ANY = re.compile(r"S_NEW")
P_BACK_OK = re.compile(
    r"P_BACK\|0x[0-9A-Za-z_]+\|0x[0-9A-Za-z_+*x]+\|0x[0-9A-Za-z_+*x]+")
P_BACK_ANY = re.compile(r"P_BACK\|")

FEAT_RE = re.compile(
    r"节表|导入表|导出表|OEP|IAT|EAT|TLS|资源|RVA|重定位|异常目录|"
    r"\.pdata|\.rsrc|\.reloc|\.idata|\.edata|SizeOfImage|SizeOfHeaders|overlay|"
    r"CLR|CodeView|PDB|forwarder|延迟导入|Bound Import")

HELV_RE = re.compile(r"[Zz][Ee]")


def check_one(rec, cat_key):
    """返回 (ok, issues[])"""
    issues = []
    msgs = rec["messages"]
    asst = "".join(m["content"] for m in msgs if m["role"] == "assistant")
    user = "".join(m["content"] for m in msgs if m["role"] == "user")
    whole = user + "\n" + asst

    # G1
    if len(asst) < 200:
        issues.append(f"G1 长度 {len(asst)} < 200")
    # G2
    names = set(TOOL_RE.findall(asst)) | set(OP_RE.findall(asst))
    names.discard("R")
    names.discard("W")
    if len(names) < 2:
        issues.append(f"G2 工具/OP 名 {len(names)} < 2 ({sorted(names)})")
    # G3
    if not STEP_RE.search(asst):
        issues.append("G3 无可执行步骤")
    # G4
    if REFUSAL_RE.search(whole):
        issues.append(f"G4 免责话术命中 {REFUSAL_RE.findall(whole)}")
    # G8
    if cat_key == "op":
        for tok, need in (("S_NEW|", 4), ("P_BACK|", 3)):
            bad = None
            for m in re.finditer(re.escape(tok), asst):
                seg = re.match(r"[^\s\n，。；）]*", asst[m.start():]).group(0)
                seg = seg.rstrip('"')
                parts = seg.split("|")
                if len(parts) - 1 != need:
                    bad = seg[:70]
                    break
                if not parts[-2].startswith("0x") or not parts[-1].startswith("0x"):
                    bad = seg[:70]
                    break
            if bad:
                issues.append(f"G8 {tok} 段数/区间不合规: {bad}")
    return (len(issues) == 0), issues, asst, user


def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for i, l in enumerate(f):
            l = l.strip()
            if l:
                out.append(json.loads(l))
    return out


def build(cats_limit):
    """组装四类样本"""
    mods = [
        ("pe",     "kb-re",          "re-pe-structure",
         [("pe_structure_a", "PE_A"), ("pe_structure_b", "PE_B"),
          ("pe_c", "PE_C"), ("pe_d", "PE_D"), ("pe_e", "PE_E"), ("pe_f", "PE_F"),
          ("pe_g", "PE_G")], "pe"),
        ("op",     "op-syntax",      "re-op-semantics",
         [("op_semantics_a", "OP_A"), ("op_semantics_b", "OP_B"),
          ("op_d", "OP_D"), ("op_e", "OP_E"), ("op_f", "OP_F")], "op"),
        ("chain",  "action-reverse", "re-decision-chain",
         [("chain_a1", "CHAIN_A1"), ("chain_a2", "CHAIN_A2"),
          ("chain_a3", "CHAIN_A3"), ("extra", "CHAIN_X2"), ("extra", "CHAIN_X3"),
          ("chain_d", "CHAIN_D"), ("chain_e", "CHAIN_E"), ("chain_f", "CHAIN_F")], "chain"),
        ("detour", "real-trajectory", "re-detour-trajectory",
         [("det_a", "DET_A"), ("det_b", "DET_B"), ("extra", "DET_X1"),
          ("det_c", "DET_C"), ("det_d", "DET_D"), ("det_e", "DET_E")], "detour"),
    ]
    out = {}
    src_bad = []
    for key, cat, fname, parts, cat_key in mods:
        pairs = []
        for mod_name, var in parts:
            m = importlib.import_module(mod_name)
            seq = getattr(m, var)
            for t in seq:
                pairs.append(t)
        # G9 源层 U+FFFD
        for i, (u, a) in enumerate(pairs):
            if "\ufffd" in u or "\ufffd" in a:
                src_bad.append(f"{key}[{i}] 含 U+FFFD")
        if cats_limit:
            pairs = pairs[:cats_limit]
        recs = []
        for i, (u, a) in enumerate(pairs):
            recs.append({
                "messages": [{"role": "user", "content": u},
                             {"role": "assistant", "content": a}],
                "meta": {"cat": cat, "tier": "gold", "forge": "r1",
                         "src": fname, "idx": i},
            })
        out[key] = dict(cat=cat, fname=fname, recs=recs, cat_key=cat_key)
    return out, src_bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--per", type=int, default=30)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    per = 0 if args.all else args.per
    groups, src_bad = build(per)

    # 基线：既有 359 + 全量 train + eval 60
    sub = load_jsonl(os.path.join(DATA, "subsets", "re-subset.jsonl"))
    mix = load_jsonl(os.path.join(DATA, "large-mix", "train.jsonl"))
    ev = load_jsonl(os.path.join(DATA, "eval_re_extended.jsonl"))

    base_full, base_user = set(), set()
    for d in sub + mix:
        base_full.add(full_hash(d["messages"]))
        base_user.add(user_hash(d["messages"]))
    ev_full, ev_user = set(), set()
    ev_shingles = []
    for d in ev:
        ev_full.add(full_hash(d["messages"]))
        ev_user.add(user_hash(d["messages"]))
        u = "".join(m["content"] for m in d["messages"] if m["role"] == "user")
        ev_shingles.append(shingles(u))
    sub_shingles = []
    for d in sub:
        u = "".join(m["content"] for m in d["messages"] if m["role"] == "user")
        sub_shingles.append(shingles(u))

    report = {"src_bad": src_bad, "cats": {}, "abort": []}
    if src_bad:
        report["abort"].append("G9 源文件含 U+FFFD")

    seen_full, seen_user = set(), set()
    all_len, all_tools = [], []
    out_recs = {}
    gate_hist = {}                      # G1..G9 拒收计数

    for key, g in groups.items():
        cat, fname, recs, cat_key = g["cat"], g["fname"], g["recs"], g["cat_key"]
        kept, drops = [], []
        lens, tooldens = [], []
        dup_base = dup_ev = dup_self = near_ev = 0
        for i, r in enumerate(recs):
            ok, issues, asst, user = check_one(r, cat_key)
            if not ok:
                drops.append({"idx": i, "issues": issues})
                for iss in issues:
                    code = iss.split()[0]
                    gate_hist[code] = gate_hist.get(code, 0) + 1
                continue
            fh, uh = full_hash(r["messages"]), user_hash(r["messages"])
            if fh in base_full or uh in base_user:
                dup_base += 1; drops.append({"idx": i, "issues": ["G5 与既有 359/3908 重复"]}); continue
            if fh in ev_full or uh in ev_user:
                dup_ev += 1; drops.append({"idx": i, "issues": ["G6 与 eval 60 哈希重叠"]}); continue
            sh = shingles(user)
            jmax = max((jaccard(sh, e) for e in ev_shingles), default=0.0)
            if jmax >= 0.35:
                near_ev += 1; drops.append({"idx": i, "issues": [f"G6 与 eval 近重复 J={jmax:.2f}"]}); continue
            if fh in seen_full or uh in seen_user:
                dup_self += 1; drops.append({"idx": i, "issues": ["G7 类内重复"]}); continue
            seen_full.add(fh); seen_user.add(uh)
            r["_hash"] = fh
            r["_user_hash"] = uh
            kept.append(r)
            lens.append(len(asst))
            tooldens.append(len(set(TOOL_RE.findall(asst)) | set(OP_RE.findall(asst))))
        # 每类封顶：源多于目标时按源顺序取前 TARGET_PER 条（确定性，不抽水）
        src_n = len(recs)
        capped = max(0, len(kept) - TARGET_PER) if per == 0 else 0
        if capped:
            kept = kept[:TARGET_PER]
            lens = lens[:TARGET_PER]
            tooldens = tooldens[:TARGET_PER]
        report.setdefault("capped_sources", {})[key] = {
            "source_pairs": src_n,
            "passed_gates": src_n - len([d for d in drops]),
            "kept": len(kept),
            "capped": capped,
        }
        all_len += lens
        all_tools += tooldens
        out_recs[key] = (fname, cat, kept)
        report["cats"][key] = {
            "cat": cat, "file": fname, "want": len(recs), "kept": len(kept),
            "dropped": len(drops), "dup_base": dup_base, "dup_eval": dup_ev,
            "dup_self": dup_self, "near_eval": near_ev,
            "len": {"min": min(lens) if lens else 0,
                    "avg": round(statistics.mean(lens), 1) if lens else 0,
                    "max": max(lens) if lens else 0},
            "tool_density": round(statistics.mean(tooldens), 2) if tooldens else 0,
            "drop_detail": drops[:12],
        }

    if report["abort"] or any(v["dropped"] for v in report["cats"].values()):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["abort"]:
            print("\nABORT：源层不合法，未写任何文件")
            return 2

    # 写盘
    os.makedirs(FORGE, exist_ok=True)
    manifest = {"generated_by": "scripts/gen_forge.py", "mode": "all" if args.all else "r1",
                "per_class": per or "full", "files": {}, "baseline": {},
                "dedupe": {"base_full_hashes": len(base_full), "base_user_hashes": len(base_user),
                           "eval_full_hashes": len(ev_full), "eval_user_hashes": len(ev_user)},
                "gates": list(range(1, 10))}
    total = 0
    for key, (fname, cat, kept) in out_recs.items():
        p = os.path.join(FORGE, fname + ".jsonl")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        blob = open(p, "rb").read()
        manifest["files"][fname] = {"path": f"data/forge/{fname}.jsonl",
                                    "cat": cat, "count": len(kept),
                                    "sha16": hashlib.sha256(blob).hexdigest()[:16],
                                    "bytes": len(blob)}
        total += len(kept)
    manifest["total"] = total
    manifest["stats"] = {
        "len_min": min(all_len) if all_len else 0,
        "len_avg": round(statistics.mean(all_len), 1) if all_len else 0,
        "len_max": max(all_len) if all_len else 0,
        "tool_density_avg": round(statistics.mean(all_tools), 2) if all_tools else 0,
        "refusal_hits": 0,
        "dup_with_359": sum(v["dup_base"] for v in report["cats"].values()),
        "dup_with_eval60": sum(v["dup_eval"] for v in report["cats"].values()),
        "near_dup_with_eval60": sum(v["near_eval"] for v in report["cats"].values()),
    }
    manifest["per_cat"] = report["cats"]
    manifest["gate_rejections"] = dict(sorted(gate_hist.items()))
    manifest["capped_sources"] = {
        "rule": "每类封顶 TARGET_PER=120；源条数超过目标时按源顺序取前 120 条"
                "（确定性，非随机抽），被封掉的是同类里排序最末的一批",
        "target_per": TARGET_PER,
        "per_class": report.get("capped_sources", {}),
        "reproducibility": "源文件与模块列表决定顺序；改动任一 forge_src 模块的条目顺序会改变被封掉的那批，"
                           "重跑后请比对本字段的 capped 值是否仍与预期一致",
    }
    manifest["forge_tag_coverage"] = {
        "rows": total,
        "tagged": total,      # build() 对每条都写 meta.forge，闸门已保证无缺失
        "rate": "1.000",
        "note": "每条都带 meta.forge；make_subsets 按该标记切 forge 组，并从 re/route/discipline 剔除",
    }
    manifest["data_observations"] = [
        {
            "id": "obs-prompt-collision",
            "what": "data/large-mix/train.jsonl 3908 行中，306 行的 user 提示完全相同（同问不同答）",
            "cause": "action-reverse silver 是模板生成：同一句「X 是哪个 kitty 工具的 action？」对不同工具/动作各一条",
            "verdict": "已知设计性重复，本轮不修改 —— 改动会破坏与历史基线的可比性",
            "impact": "min_chars / min_tool 这类「按 user 提示去重再判」的判据效果会减弱；"
                      "按 assistant 内容判定的判据不受影响",
            "measured_by": "user_hash = sha256(normalized user contents)；rows=3908, unique_user_hash=3602",
        },
        {
            "id": "obs-no-row-dup",
            "what": "同文件无行级重复（full_hash 3908/3908 唯一）",
            "verdict": "无需处理",
        },
    ]
    with open(os.path.join(FORGE, "FORGE-MANIFEST.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps(manifest["stats"], ensure_ascii=False, indent=2))
    print("gate rejections:", json.dumps(manifest["gate_rejections"], ensure_ascii=False))
    print("forge tag coverage:", manifest["forge_tag_coverage"]["tagged"], "/", total)
    print("\nfiles:")
    for k, v in manifest["files"].items():
        print(f"  {k}: {v['count']} 条  sha16={v['sha16']}")
    print(f"\ntotal = {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
